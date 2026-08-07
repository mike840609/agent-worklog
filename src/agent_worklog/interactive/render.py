"""Pure Rich rendering for the interactive Agent Worklog screens."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

from agent_worklog.interactive.models import ReportDraft
from agent_worklog.interactive.selection import SelectionMark, SelectionState
from agent_worklog.models.time_range import DateRange
from agent_worklog.security.redactor import redact_text
from agent_worklog.services.scan import ScanResult


@dataclass(frozen=True)
class VisibleRow:
    kind: str
    repository_id: str
    session_id: str | None = None


_MAIN_OPTIONS = ["Generate Report", "Browse Sessions", "Check Setup", "Settings"]
_SETUP_OPTIONS = [
    "Review sessions",
    "Harness",
    "Period",
    "Detail",
    "Subagents",
    "Narrative",
    "Sanitize",
    "Dry run",
    "Back",
]
_RESULT_OPTIONS = ["Back to main menu", "Generate another report", "Print report path"]
_MARKERS = {
    SelectionMark.ALL: "●",
    SelectionMark.NONE: "○",
    SelectionMark.PARTIAL: "◐",
}


def _option(label: str, index: int, selected: int) -> str:
    return f"{'❯' if index == selected else ' '} {label}"


def _period_label(period: DateRange) -> str:
    return f"{period.since:%b %d} – {period.until:%b %d}"


def _harness_label(harness: str) -> str:
    return {
        "opencode": "OpenCode",
        "claude-code": "Claude Code",
        "codex": "Codex",
    }.get(harness, harness)


def _bool_label(value: bool, enabled: str, disabled: str) -> str:
    return enabled if value else disabled


def render_main_menu(console: Console, *, selected: int) -> None:
    console.print("Agent Worklog")
    console.print("Turn coding-agent sessions into engineering reports")
    console.print()
    for index, label in enumerate(_MAIN_OPTIONS):
        console.print(_option(label, index, selected))
    console.print()
    console.print("↑↓ / jk Navigate   Enter Select   q Quit")


def render_report_setup(console: Console, draft: ReportDraft, *, selected: int) -> None:
    console.print("Generate Report")
    console.print()
    console.print(f"Harness      {_harness_label(draft.harness)}")
    console.print(f"Period       {_period_label(draft.period)}")
    console.print(f"Detail       {draft.detail.value.title()}")
    console.print(
        f"Subagents    {_bool_label(draft.include_subagents, 'Included', 'Excluded')}"
    )
    console.print(f"Narrative    {_bool_label(draft.narrative, 'Enabled', 'Disabled')}")
    console.print(f"Sanitize     {_bool_label(draft.sanitize, 'On', 'Off')}")
    console.print(f"Dry run      {_bool_label(draft.dry_run, 'On', 'Off')}")
    console.print()
    for index, label in enumerate(_SETUP_OPTIONS):
        console.print(_option(label, index, selected))
    console.print()
    console.print("↑↓ / jk Navigate   Enter Edit   r Review   b Back")


def build_visible_rows(
    scan: ScanResult,
    expanded_repositories: set[str],
) -> list[VisibleRow]:
    rows: list[VisibleRow] = []
    for repository_id, sessions in scan.sessions_by_repository.items():
        rows.append(VisibleRow(kind="repository", repository_id=repository_id))
        if repository_id not in expanded_repositories:
            continue
        rows.extend(
            VisibleRow(
                kind="session",
                repository_id=repository_id,
                session_id=item.session.session_id,
            )
            for item in sessions
        )
    return rows


def _repository_display_name(scan: ScanResult, repository_id: str) -> str:
    sessions = scan.sessions_by_repository[repository_id]
    if not sessions:
        return repository_id
    return redact_text(sessions[0].repository.display_name)


def _session_title(scan: ScanResult, session_id: str) -> str:
    for item in scan.resolved_sessions:
        if item.session.session_id == session_id:
            return redact_text(item.session.title or session_id)
    return session_id


def render_session_review(
    console: Console,
    selection: SelectionState,
    *,
    expanded_repositories: set[str],
    cursor: int,
    message: str | None = None,
) -> None:
    console.print(
        f"Review Sessions   {selection.selected_count} / {selection.total_count} selected"
    )
    if message:
        console.print(message)
    console.print()
    rows = build_visible_rows(selection.scan, expanded_repositories)
    for index, row in enumerate(rows):
        prefix = "❯" if index == cursor else " "
        if row.kind == "repository":
            expanded = row.repository_id in expanded_repositories
            arrow = "▼" if expanded else "▶"
            mark = _MARKERS[selection.repository_mark(row.repository_id)]
            selected = sum(
                item.session.session_id in selection.selected_session_ids
                for item in selection.scan.sessions_by_repository[row.repository_id]
            )
            total = len(selection.scan.sessions_by_repository[row.repository_id])
            name = _repository_display_name(selection.scan, row.repository_id)
            console.print(f"{prefix} {arrow} {mark} {name}   {selected} / {total}")
        else:
            assert row.session_id is not None
            mark = "●" if row.session_id in selection.selected_session_ids else "○"
            console.print(f"{prefix}     {mark} {_session_title(selection.scan, row.session_id)}")
    console.print()
    console.print("↑↓ / jk Navigate   Space Toggle   Enter Expand")
    console.print("a All   n None   g Generate   b Back   q Main menu")


def render_session_browser(
    console: Console,
    scan: ScanResult,
    *,
    expanded_repositories: set[str],
    cursor: int,
) -> None:
    console.print(f"Browse Sessions   {scan.loaded_session_count} sessions")
    console.print()
    rows = build_visible_rows(scan, expanded_repositories)
    for index, row in enumerate(rows):
        prefix = "❯" if index == cursor else " "
        if row.kind == "repository":
            expanded = row.repository_id in expanded_repositories
            arrow = "▼" if expanded else "▶"
            name = _repository_display_name(scan, row.repository_id)
            count = len(scan.sessions_by_repository[row.repository_id])
            console.print(f"{prefix} {arrow} {name}   {count}")
        else:
            assert row.session_id is not None
            console.print(f"{prefix}     {_session_title(scan, row.session_id)}")
    console.print()
    console.print("↑↓ / jk Navigate   Enter Expand   b Back   q Main menu")


def render_report_result(
    console: Console,
    *,
    period: DateRange,
    repository_count: int,
    session_count: int,
    output_path: Path | None,
    selected: int,
) -> None:
    console.print("✓ Report generated")
    console.print()
    console.print(f"Period         {_period_label(period)}")
    console.print(f"Repositories   {repository_count}")
    console.print(f"Sessions       {session_count}")
    console.print(f"Output         {output_path if output_path is not None else 'Dry run'}")
    console.print()
    for index, label in enumerate(_RESULT_OPTIONS):
        console.print(_option(label, index, selected))
    console.print()
    console.print("↑↓ / jk Navigate   Enter Select   q Main menu")


def render_recoverable_error(
    console: Console,
    *,
    title: str,
    detail: str,
    options: list[str],
    selected: int,
) -> None:
    console.print(f"✗ {title}")
    console.print(redact_text(detail))
    console.print()
    for index, label in enumerate(options):
        console.print(_option(label, index, selected))
    console.print()
    console.print("↑↓ / jk Navigate   Enter Select   b Back   q Main menu")
