"""Command-line interface for Agent Worklog."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import typer

from agent_worklog import config_store
from agent_worklog.config import AppSettings
from agent_worklog.errors import (
    ConfigurationError,
    HarnessSourceError,
    NoSessionsError,
    ReportOutputError,
)
from agent_worklog.harnesses.base import HarnessSessionSource
from agent_worklog.harnesses.claude_code.source import ClaudeCodeFileSource
from agent_worklog.harnesses.codex.source import CodexSource
from agent_worklog.harnesses.opencode.source import OpenCodeCliSource
from agent_worklog.harnesses.opencode.stats import collect_usage_stats, usage_days
from agent_worklog.logging import ConsoleReporter
from agent_worklog.models.time_range import DateRange
from agent_worklog.process import CommandRunner
from agent_worklog.progress import ProgressReporter
from agent_worklog.renderers.markdown import DetailLevel, MarkdownRenderer
from agent_worklog.renderers.usage import render_activity_usage
from agent_worklog.repositories.resolver import RepositoryResolver
from agent_worklog.security.redactor import redact_text
from agent_worklog.services.doctor import run_doctor
from agent_worklog.services.report import ReportService
from agent_worklog.services.scan import ScanResult, ScanService
from agent_worklog.summarizers.openai_compatible import OpenAICompatibleSummarizer
from agent_worklog.summarizers.rule_based import RuleBasedSummarizer


class Harness(StrEnum):
    OPENCODE = "opencode"
    CLAUDE_CODE = "claude-code"
    CODEX = "codex"


# A module-level singleton, per ruff B008: an Enum-typed `typer.Option(...)` call
# isn't recognized as an immutable default, so it must be constructed once here
# and shared, rather than called inline in each command's signature.
_HARNESS_OPTION = typer.Option(
    Harness.OPENCODE,
    "--harness",
    help="Coding-agent harness to read sessions from.",
)

_DETAIL_OPTION = typer.Option(
    DetailLevel.FULL,
    "--detail",
    help="How much detail the report contains: full (default) or brief.",
)

app = typer.Typer(
    no_args_is_help=True,
    help="Turn coding-agent sessions into repository-based engineering reports.",
)


def _load_settings() -> AppSettings:
    """Load settings, layering the settings file below the environment.

    pydantic-settings gives environment variables precedence over `_env_file`,
    which is the order `config set` promises: the file holds defaults, an
    exported variable overrides them for one shell.
    """

    path = config_store.config_file_path()
    try:
        return AppSettings(_env_file=path)  # type: ignore[call-arg]
    except Exception as exc:  # Pydantic aggregates configuration failures.
        # Name the file when there is one: a parse error otherwise says what is
        # wrong without saying where the value came from.
        hint = f"; settings come from the environment and {path}" if path.exists() else ""
        # Pydantic's validation errors echo the offending input verbatim (e.g.
        # `input_value='sk-proj-...'`), so a bad value in a setting the model
        # DOES own — a base URL with an embedded password, an API key typed
        # into the wrong field — must not reach stdout unredacted.
        raise ConfigurationError(redact_text(f"{exc}{hint}")) from exc


def _now_in_timezone(timezone: str) -> datetime:
    try:
        return datetime.now(ZoneInfo(timezone))
    except ZoneInfoNotFoundError as exc:
        raise ConfigurationError(f"unknown timezone: {timezone}") from exc


def _parse_iso_datetime(value: str, *, timezone: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise typer.BadParameter(f"invalid ISO datetime: {value}") from exc
    if parsed.tzinfo is None:
        try:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
        except ZoneInfoNotFoundError as exc:
            raise ConfigurationError(f"unknown timezone: {timezone}") from exc
    return parsed


def _resolve_period(
    *,
    days: int | None,
    period: str | None,
    since: str | None,
    until: str | None,
    timezone: str,
    now: datetime,
) -> DateRange:
    """Resolve the requested period against a single clock read for the command."""

    selectors = sum(value is not None for value in (days, period, since))
    if selectors != 1:
        raise typer.BadParameter("provide exactly one of --days, --period, or --since")
    if until is not None and since is None:
        raise typer.BadParameter("--until requires --since")
    if days is not None:
        if days < 1:
            raise typer.BadParameter("--days must be at least 1")
        return DateRange.from_days(days=days, now=now)
    if period is not None:
        if period != "last-week":
            raise typer.BadParameter("--period accepts only 'last-week'")
        return DateRange.previous_week(now=now)
    assert since is not None
    start = _parse_iso_datetime(since, timezone=timezone)
    end = _parse_iso_datetime(until, timezone=timezone) if until else now
    return DateRange(since=start, until=end)


def _default_output_path(settings: AppSettings, period: DateRange) -> Path:
    filename = f"worklog-{period.since:%Y-%m-%d}_{period.until:%Y-%m-%d}.md"
    return settings.report.output_directory / filename


def _require_enabled_harness(settings: AppSettings, harness: Harness) -> None:
    """Refuse a harness its configuration has turned off.

    A privacy tool must not advertise an off switch that does nothing: reading
    `~/.claude/projects` or `~/.codex` is exactly the kind of thing an operator
    may need to forbid for a whole machine.

    Each enum member's name is the settings field name, so a new harness needs
    no edit here.
    """

    if not getattr(settings.harnesses, harness.name.lower()).enabled:
        variable = f"AGENT_WORKLOG_HARNESSES__{harness.name}__ENABLED"
        raise ConfigurationError(
            f"harness {harness.value} is disabled by configuration; "
            f"set {variable}=true to use it"
        )


def _build_scan_service(
    settings: AppSettings,
    period: DateRange,
    root_only: bool = False,
    *,
    harness: Harness = Harness.OPENCODE,
    progress: ProgressReporter | None = None,
) -> ScanService:
    _require_enabled_harness(settings, harness)
    git_runner = CommandRunner(timeout_seconds=5.0)
    source: HarnessSessionSource
    if harness is Harness.CLAUDE_CODE:
        source = ClaudeCodeFileSource(
            projects_directory=settings.harnesses.claude_code.projects_directory,
            root_only=root_only,
        )
    elif harness is Harness.CODEX:
        source = CodexSource(
            home_directory=settings.harnesses.codex.home_directory,
            root_only=root_only,
        )
    else:
        cli_settings = settings.harnesses.opencode.cli
        source = OpenCodeCliSource(
            runner=CommandRunner(timeout_seconds=cli_settings.timeout_seconds),
            executable=cli_settings.executable,
            root_only=root_only,
        )
    return ScanService(
        source=source,
        period=period,
        resolver=RepositoryResolver(runner=git_runner),
        progress=progress,
    )


def _usage_provider(
    settings: AppSettings,
    period: DateRange,
    harness: Harness,
    now: datetime,
) -> tuple[Callable[[ScanResult], str], int | None]:
    """Return the harness usage provider and the window it covers, if narrower."""

    if harness in {Harness.CLAUDE_CODE, Harness.CODEX}:
        # Usage rides on the already-filtered activities, so the window is exact
        # and needs no "wider than the period" caveat.
        return partial(render_activity_usage, harness=harness.value), None

    cli_settings = settings.harnesses.opencode.cli
    stats_runner = CommandRunner(timeout_seconds=cli_settings.timeout_seconds)
    days = usage_days(period, now)

    def collect(_scan: ScanResult) -> str:
        return collect_usage_stats(
            runner=stats_runner,
            executable=cli_settings.executable,
            days=days,
        )

    return collect, days


def _build_report_service(
    settings: AppSettings,
    period: DateRange,
    output_path: Path,
    no_llm: bool,
    root_only: bool = False,
    *,
    now: datetime,
    harness: Harness = Harness.OPENCODE,
    detail: DetailLevel = DetailLevel.FULL,
    progress: ProgressReporter | None = None,
) -> ReportService:
    """Build the report service around the command's single clock read."""

    summarizer = RuleBasedSummarizer()
    api_key = os.environ.get(settings.llm.api_key_env)
    if settings.llm.enabled and not no_llm and api_key:
        summarizer = OpenAICompatibleSummarizer(
            model=settings.llm.model,
            api_key=api_key,
            base_url=settings.llm.base_url,
            timeout_seconds=settings.llm.timeout_seconds,
            fallback=RuleBasedSummarizer(),
        )

    usage_provider, days = _usage_provider(settings, period, harness, now)

    return ReportService(
        scan_service=_build_scan_service(
            settings,
            period,
            root_only,
            harness=harness,
            progress=progress,
        ),
        summarizer=summarizer,
        renderer=MarkdownRenderer(),
        period=period,
        output_path=output_path,
        now_factory=lambda: now,
        usage_provider=usage_provider,
        usage_days=days,
        detail=detail,
        progress=progress,
    )


def _handle_expected_error(exc: Exception, *, code: int) -> None:
    typer.echo(f"Error: {exc}")
    raise typer.Exit(code=code)


def _validate_output_mode(*, quiet: bool, verbose: bool) -> None:
    if quiet and verbose:
        raise typer.BadParameter("--quiet and --verbose cannot be used together")


@app.command()
def doctor(
    harness: Harness = _HARNESS_OPTION,
    verbose: bool = typer.Option(False, "--verbose"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Validate the selected harness and Git dependencies."""

    _validate_output_mode(quiet=quiet, verbose=verbose)
    reporter = ConsoleReporter(quiet=quiet, verbose=verbose)
    try:
        settings = _load_settings()
        _require_enabled_harness(settings, harness)
        runner = CommandRunner(
            timeout_seconds=settings.harnesses.opencode.cli.timeout_seconds
        )
        result = run_doctor(settings, runner=runner, harness=harness.value)
    except ConfigurationError as exc:
        _handle_expected_error(exc, code=3)
        return
    for check in result.checks:
        reporter.doctor_check(check.name, check.ok, check.detail)
    if not result.ok:
        raise typer.Exit(code=5)


@app.command()
def scan(
    days: int | None = typer.Option(None, "--days"),
    period: str | None = typer.Option(None, "--period"),
    since: str | None = typer.Option(None, "--since"),
    until: str | None = typer.Option(None, "--until"),
    root_only: bool = typer.Option(
        False,
        "--root-only",
        help="Exclude child/subagent sessions.",
    ),
    harness: Harness = _HARNESS_OPTION,
    verbose: bool = typer.Option(False, "--verbose"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Find coding-agent sessions and group them by Git repository."""

    _validate_output_mode(quiet=quiet, verbose=verbose)
    reporter = ConsoleReporter(quiet=quiet, verbose=verbose)
    try:
        settings = _load_settings()
        now = _now_in_timezone(settings.report.timezone)
        selected_period = _resolve_period(
            days=days,
            period=period,
            since=since,
            until=until,
            timezone=settings.report.timezone,
            now=now,
        )
        with reporter.progress() as progress:
            result = _build_scan_service(
                settings,
                selected_period,
                root_only,
                harness=harness,
                progress=progress,
            ).scan()
            if result.loaded_session_count == 0:
                raise NoSessionsError(
                    f"no {harness.value} activity found in the requested period"
                )
    except ConfigurationError as exc:
        _handle_expected_error(exc, code=3)
        return
    except NoSessionsError as exc:
        _handle_expected_error(exc, code=4)
        return
    except HarnessSourceError as exc:
        _handle_expected_error(exc, code=5)
        return
    reporter.scan_result(result)


@app.command()
def report(
    days: int | None = typer.Option(None, "--days"),
    period: str | None = typer.Option(None, "--period"),
    since: str | None = typer.Option(None, "--since"),
    until: str | None = typer.Option(None, "--until"),
    root_only: bool = typer.Option(
        False,
        "--root-only",
        help="Exclude child/subagent sessions.",
    ),
    output: Annotated[Path | None, typer.Option("--output")] = None,
    dry_run: bool = typer.Option(False, "--dry-run"),
    no_llm: bool = typer.Option(False, "--no-llm"),
    force: bool = typer.Option(False, "--force"),
    harness: Harness = _HARNESS_OPTION,
    detail: DetailLevel = _DETAIL_OPTION,
    verbose: bool = typer.Option(False, "--verbose"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Generate a Markdown engineering worklog."""

    _validate_output_mode(quiet=quiet, verbose=verbose)
    reporter = ConsoleReporter(quiet=quiet, verbose=verbose)
    try:
        settings = _load_settings()
        now = _now_in_timezone(settings.report.timezone)
        selected_period = _resolve_period(
            days=days,
            period=period,
            since=since,
            until=until,
            timezone=settings.report.timezone,
            now=now,
        )
        output_path = output or _default_output_path(settings, selected_period)
        with reporter.progress() as progress:
            service = _build_report_service(
                settings,
                selected_period,
                output_path,
                no_llm,
                root_only,
                now=now,
                harness=harness,
                detail=detail,
                progress=progress,
            )
            result = service.generate(force=force, dry_run=dry_run)
            if not result.report.repositories:
                raise NoSessionsError(
                    f"no {harness.value} activity found in the requested period"
                )
    except ConfigurationError as exc:
        _handle_expected_error(exc, code=3)
        return
    except NoSessionsError as exc:
        _handle_expected_error(exc, code=4)
        return
    except HarnessSourceError as exc:
        _handle_expected_error(exc, code=5)
        return
    except ReportOutputError as exc:
        _handle_expected_error(exc, code=7)
        return

    if dry_run:
        typer.echo(result.content, nl=False)
    elif quiet:
        reporter.output_path(result.output_path)
    else:
        reporter.message(f"Report written to {result.output_path}")
        if verbose:
            for warning in result.report.warnings:
                reporter.message(f"Warning: {warning}")


config_app = typer.Typer(
    no_args_is_help=True,
    help="Show and edit the settings file.",
)
app.add_typer(config_app, name="config")


@config_app.command("path")
def config_path() -> None:
    """Print the settings file location."""

    typer.echo(str(config_store.config_file_path()))


@config_app.command("list")
def config_list() -> None:
    """Show every setting, the value in force, and where it comes from."""

    path = config_store.config_file_path()
    try:
        rows = config_store.describe_settings(path)
    except ConfigurationError as exc:
        _handle_expected_error(exc, code=3)
        return
    ConsoleReporter().settings_table(rows, path=path)


def _default_restored(setting: config_store.SettingKey, removed: bool) -> str:
    if removed:
        return f"Removed {setting.key}; using default: {setting.default}"
    return f"{setting.key} was not set; already using default: {setting.default}"


def _warn_if_shadowed(
    reporter: ConsoleReporter, setting: config_store.SettingKey
) -> None:
    """Say so when an exported variable overrides what was just written.

    The environment wins over the file, so without this the command reports
    success on a change the next run will ignore.
    """

    if os.environ.get(setting.variable) is not None:
        reporter.message(
            f"Note: {setting.variable} is set in the environment "
            "and takes precedence."
        )


@config_app.command("set")
def config_set(key: str, value: str) -> None:
    """Set one setting. An empty value restores its default."""

    reporter = ConsoleReporter()
    path = config_store.config_file_path()
    try:
        if value == "":
            # Every setting is optional, so "no value" is a real answer: drop
            # the entry rather than storing an empty string the model would
            # then have to interpret.
            setting, removed = config_store.unset_value(key, path=path)
            reporter.message(_default_restored(setting, removed))
        else:
            setting = config_store.set_value(key, value, path=path)
            reporter.message(f"{setting.key} = {value} ({path})")
    except ConfigurationError as exc:
        _handle_expected_error(exc, code=3)
        return
    _warn_if_shadowed(reporter, setting)


@config_app.command("unset")
def config_unset(key: str) -> None:
    """Remove one setting so its default applies again."""

    reporter = ConsoleReporter()
    try:
        setting, removed = config_store.unset_value(key)
    except ConfigurationError as exc:
        _handle_expected_error(exc, code=3)
        return
    reporter.message(_default_restored(setting, removed))
    _warn_if_shadowed(reporter, setting)
