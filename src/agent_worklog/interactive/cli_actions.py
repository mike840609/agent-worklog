"""Adapters from the interactive controller to existing CLI service builders.

Imports of :mod:`agent_worklog.cli` stay inside callbacks so the Typer module can
import ``build_interactive_actions`` without creating an import cycle.
"""

from __future__ import annotations

from agent_worklog.interactive.controller import (
    InteractiveActions,
    InteractiveReportResult,
)
from agent_worklog.interactive.models import ReportDraft
from agent_worklog.logging import ConsoleReporter
from agent_worklog.models.time_range import DateRange
from agent_worklog.process import CommandRunner
from agent_worklog.services.scan import ScanResult


def _new_draft() -> ReportDraft:
    from agent_worklog import cli

    settings = cli._load_settings()
    now = cli._now_in_timezone(settings.report.timezone)
    enabled = cli._enabled_harnesses(settings)
    harness = cli.Harness.OPENCODE if cli.Harness.OPENCODE in enabled else enabled[0]
    return ReportDraft(
        harness=harness.value,
        period=DateRange.previous_week(now=now),
    )


def _choose_harness(current: str) -> str:
    from agent_worklog import cli

    settings = cli._load_settings()
    return cli._ask_harness(settings).value


def _choose_period(current: DateRange) -> DateRange:
    from agent_worklog import cli

    settings = cli._load_settings()
    now = cli._now_in_timezone(settings.report.timezone)
    return cli._ask_period(settings.report.timezone, now)


def _scan(draft: ReportDraft) -> ScanResult:
    from agent_worklog import cli

    settings = cli._load_settings()
    harness = cli.Harness(draft.harness)
    reporter = ConsoleReporter()
    with reporter.progress() as progress:
        service = cli._build_scan_service(
            settings,
            draft.period,
            not draft.include_subagents,
            harness=harness,
            sanitize=draft.sanitize,
            progress=progress,
        )
        return service.scan()


def _generate(
    draft: ReportDraft,
    scan: ScanResult,
    force: bool,
) -> InteractiveReportResult:
    from agent_worklog import cli

    settings = cli._load_settings()
    now = cli._now_in_timezone(settings.report.timezone)
    harness = cli.Harness(draft.harness)
    output_path = cli._default_output_path(settings, draft.period)
    reporter = ConsoleReporter()
    with reporter.progress() as progress:
        service = cli._build_report_service(
            settings,
            draft.period,
            output_path,
            no_llm=not draft.narrative,
            root_only=not draft.include_subagents,
            now=now,
            harness=harness,
            sanitize=draft.sanitize,
            detail=draft.detail,
            progress=progress,
        )
        result = service.generate(force=force, dry_run=draft.dry_run, scan=scan)
    return InteractiveReportResult(
        output_path=None if draft.dry_run else result.output_path,
        content=result.content,
        repository_count=len(scan.sessions_by_repository),
        session_count=scan.loaded_session_count,
    )


def _doctor(harness_name: str) -> list[str]:
    from agent_worklog import cli

    settings = cli._load_settings()
    harness = cli.Harness(harness_name)
    cli._require_enabled_harness(settings, harness)
    runner = CommandRunner(
        timeout_seconds=settings.harnesses.opencode.cli.timeout_seconds
    )
    result = cli.run_doctor(settings, runner=runner, harness=harness.value)
    return [
        f"{'OK' if check.ok else 'ERROR'} {check.name}: {check.detail}"
        for check in result.checks
    ]


def _edit_settings() -> None:
    from agent_worklog import cli

    cli.config_init()


def build_interactive_actions() -> InteractiveActions:
    """Build the controller callbacks from the CLI's existing service seams."""

    return InteractiveActions(
        new_draft=_new_draft,
        choose_harness=_choose_harness,
        choose_period=_choose_period,
        scan=_scan,
        generate=_generate,
        doctor=_doctor,
        edit_settings=_edit_settings,
    )
