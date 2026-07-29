"""Command-line interface for Agent Worklog."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import typer

from agent_worklog.config import AppSettings
from agent_worklog.errors import (
    ConfigurationError,
    HarnessSourceError,
    NoSessionsError,
    ReportOutputError,
)
from agent_worklog.harnesses.opencode.cli_runner import CommandRunner
from agent_worklog.harnesses.opencode.source import OpenCodeCliSource
from agent_worklog.harnesses.opencode.stats import collect_usage_stats, usage_days
from agent_worklog.logging import ConsoleReporter
from agent_worklog.models.time_range import DateRange
from agent_worklog.renderers.markdown import MarkdownRenderer
from agent_worklog.repositories.resolver import RepositoryResolver
from agent_worklog.services.doctor import run_doctor
from agent_worklog.services.report import ReportService
from agent_worklog.services.scan import ScanService
from agent_worklog.summarizers.openai_compatible import OpenAICompatibleSummarizer
from agent_worklog.summarizers.rule_based import RuleBasedSummarizer

app = typer.Typer(
    no_args_is_help=True,
    help="Turn coding-agent sessions into repository-based engineering reports.",
)


def _load_settings() -> AppSettings:
    try:
        return AppSettings()
    except Exception as exc:  # Pydantic aggregates configuration failures.
        raise ConfigurationError(str(exc)) from exc


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


def _build_scan_service(
    settings: AppSettings,
    period: DateRange,
    root_only: bool = False,
) -> ScanService:
    cli_settings = settings.harnesses.opencode.cli
    source_runner = CommandRunner(timeout_seconds=cli_settings.timeout_seconds)
    git_runner = CommandRunner(timeout_seconds=5.0)
    return ScanService(
        source=OpenCodeCliSource(
            runner=source_runner,
            executable=cli_settings.executable,
            root_only=root_only,
        ),
        period=period,
        resolver=RepositoryResolver(runner=git_runner),
    )


def _build_report_service(
    settings: AppSettings,
    period: DateRange,
    output_path: Path,
    no_llm: bool,
    root_only: bool = False,
    *,
    now: datetime,
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
    cli_settings = settings.harnesses.opencode.cli
    stats_runner = CommandRunner(timeout_seconds=cli_settings.timeout_seconds)
    days = usage_days(period, now)
    return ReportService(
        scan_service=_build_scan_service(settings, period, root_only),
        summarizer=summarizer,
        renderer=MarkdownRenderer(),
        period=period,
        output_path=output_path,
        now_factory=lambda: now,
        usage_provider=lambda: collect_usage_stats(
            runner=stats_runner,
            executable=cli_settings.executable,
            days=days,
        ),
        usage_days=days,
    )


def _handle_expected_error(exc: Exception, *, code: int) -> None:
    typer.echo(f"Error: {exc}")
    raise typer.Exit(code=code)


def _validate_output_mode(*, quiet: bool, verbose: bool) -> None:
    if quiet and verbose:
        raise typer.BadParameter("--quiet and --verbose cannot be used together")


@app.command()
def doctor(
    verbose: bool = typer.Option(False, "--verbose"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Validate OpenCode and Git dependencies."""

    _validate_output_mode(quiet=quiet, verbose=verbose)
    reporter = ConsoleReporter(quiet=quiet, verbose=verbose)
    try:
        settings = _load_settings()
        runner = CommandRunner(
            timeout_seconds=settings.harnesses.opencode.cli.timeout_seconds
        )
        result = run_doctor(settings, runner=runner)
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
    verbose: bool = typer.Option(False, "--verbose"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Find OpenCode sessions and group them by Git repository."""

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
        result = _build_scan_service(settings, selected_period, root_only).scan()
        if result.loaded_session_count == 0:
            raise NoSessionsError("no OpenCode activity found in the requested period")
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
        service = _build_report_service(
            settings,
            selected_period,
            output_path,
            no_llm,
            root_only,
            now=now,
        )
        result = service.generate(force=force, dry_run=dry_run)
        if not result.report.repositories:
            raise NoSessionsError("no OpenCode activity found in the requested period")
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
