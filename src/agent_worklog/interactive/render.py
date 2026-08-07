"""Pure Rich rendering for the interactive Agent Worklog screens."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.text import Text

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
_DRY_RUN_RESULT_OPTIONS = ["Preview report", "Back to main menu", "Generate another report"]
_MARKERS = {
    SelectionMark.ALL: "●",
    SelectionMark.NONE: "○",
    SelectionMark.PARTIAL: "◐",
}


def _option(label: str, index: int, selected: int) -> Text:
    return Text(
        f"{'❯' if index == selected else ' '} {label}",
        style="bold" if index == selected else "",
    )


def _viewport_text(value: str, *, style: str = "") -> Text:
    """Render one viewport line without letting terminal width change its height."""

    return Text(value, style=style, no_wrap=True, overflow="ellipsis")


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


def report_result_options(*, dry_run: bool) -> list[str]:
    """Return the actions shown on the result screen."""

    return list(_DRY_RUN_RESULT_OPTIONS if dry_run else _RESULT_OPTIONS)


def report_preview_capacity(terminal_height: int) -> int:
    """Content lines available while keeping the preview within the viewport."""

    return max(1, terminal_height - 6)


def render_main_menu(console: Console, *, selected: int) -> None:
    console.print(Text("Agent Worklog", style="bold"))
    console.print(Text("Turn coding-agent sessions into engineering reports", style="dim"))
    console.print()
    for index, label in enumerate(_MAIN_OPTIONS):
        console.print(_option(label, index, selected))
    console.print()
    console.print(Text("↑↓ / jk Navigate   Enter Select   1-4 Select   q Quit", style="dim"))


def render_report_setup(console: Console, draft: ReportDraft, *, selected: int) -> None:
    console.print(Text("Generate Report", style="bold"))
    console.print()
    console.print(Text(f"Harness      {_harness_label(draft.harness)}"))
    console.print(Text(f"Period       {_period_label(draft.period)}"))
    console.print(Text(f"Detail       {draft.detail.value.title()}"))
    console.print(
        Text(
            f"Subagents    {_bool_label(draft.include_subagents, 'Included', 'Excluded')}"
        )
    )
    console.print(
        Text(f"Narrative    {_bool_label(draft.narrative, 'Enabled', 'Disabled')}")
    )
    sanitize = (
        _bool_label(draft.sanitize, "On", "Off")
        if draft.harness == "opencode"
        else "N/A"
    )
    console.print(Text(f"Sanitize     {sanitize}"))
    console.print(Text(f"Dry run      {_bool_label(draft.dry_run, 'On', 'Off')}"))
    console.print()
    for index, label in enumerate(_SETUP_OPTIONS):
        style = "dim" if label == "Sanitize" and draft.harness != "opencode" else None
        option = _option(label, index, selected)
        if style is not None:
            option.stylize(style)
        console.print(option)
    console.print()
    console.print(
        Text("↑↓ / jk Navigate   Enter Edit   r Review   b Back   q Main menu", style="dim")
    )


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


def _session_titles(scan: ScanResult) -> dict[str, str]:
    return {
        item.session.session_id: redact_text(item.session.title or item.session.session_id)
        for item in scan.resolved_sessions
    }


def _visible_window(
    rows: list[VisibleRow],
    *,
    cursor: int,
    terminal_height: int,
    reserved_lines: int,
) -> tuple[list[tuple[int, VisibleRow]], int, int]:
    """Keep the active row visible without allowing long scans to flood the terminal."""

    if not rows:
        return [], 0, 0
    capacity = max(1, terminal_height - reserved_lines - 3)
    if len(rows) <= capacity:
        return list(enumerate(rows)), 0, 0
    cursor = min(max(cursor, 0), len(rows) - 1)
    start = min(max(0, cursor - capacity // 2), len(rows) - capacity)
    end = start + capacity
    return list(enumerate(rows[start:end], start=start)), start, len(rows) - end


def render_session_review(
    console: Console,
    selection: SelectionState,
    *,
    expanded_repositories: set[str],
    cursor: int,
    message: str | None = None,
) -> None:
    console.print(
        _viewport_text(
            f"Review Sessions   {selection.selected_count} / {selection.total_count} selected",
            style="bold",
        )
    )
    if message:
        console.print(_viewport_text(message))
    console.print()
    rows = build_visible_rows(selection.scan, expanded_repositories)
    visible, hidden_above, hidden_below = _visible_window(
        rows,
        cursor=cursor,
        terminal_height=console.size.height,
        reserved_lines=6 if message else 5,
    )
    if hidden_above:
        console.print(_viewport_text(f"↑ {hidden_above} more", style="dim"))
    titles = _session_titles(selection.scan)
    for index, row in visible:
        prefix = "❯" if index == cursor else " "
        style = "bold" if index == cursor else ""
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
            console.print(
                _viewport_text(
                    f"{prefix} {arrow} {mark} {name}   {selected} / {total}",
                    style=style,
                )
            )
        else:
            assert row.session_id is not None
            mark = "●" if row.session_id in selection.selected_session_ids else "○"
            console.print(
                _viewport_text(
                    f"{prefix}     {mark} {titles[row.session_id]}",
                    style=style,
                )
            )
    if hidden_below:
        console.print(_viewport_text(f"↓ {hidden_below} more", style="dim"))
    console.print()
    console.print(
        _viewport_text("↑↓ / jk Navigate   Space Toggle   Enter Expand", style="dim")
    )
    console.print(
        _viewport_text("a All   n None   g Generate   b Back   q Main menu", style="dim")
    )


def render_session_browser(
    console: Console,
    scan: ScanResult,
    *,
    expanded_repositories: set[str],
    cursor: int,
) -> None:
    console.print(
        _viewport_text(f"Browse Sessions   {scan.loaded_session_count} sessions", style="bold")
    )
    console.print()
    rows = build_visible_rows(scan, expanded_repositories)
    visible, hidden_above, hidden_below = _visible_window(
        rows,
        cursor=cursor,
        terminal_height=console.size.height,
        reserved_lines=4,
    )
    if hidden_above:
        console.print(_viewport_text(f"↑ {hidden_above} more", style="dim"))
    titles = _session_titles(scan)
    for index, row in visible:
        prefix = "❯" if index == cursor else " "
        style = "bold" if index == cursor else ""
        if row.kind == "repository":
            expanded = row.repository_id in expanded_repositories
            arrow = "▼" if expanded else "▶"
            name = _repository_display_name(scan, row.repository_id)
            count = len(scan.sessions_by_repository[row.repository_id])
            console.print(
                _viewport_text(f"{prefix} {arrow} {name}   {count}", style=style)
            )
        else:
            assert row.session_id is not None
            console.print(
                _viewport_text(f"{prefix}     {titles[row.session_id]}", style=style)
            )
    if hidden_below:
        console.print(_viewport_text(f"↓ {hidden_below} more", style="dim"))
    console.print()
    console.print(
        _viewport_text("↑↓ / jk Navigate   Enter Expand   b Back   q Main menu", style="dim")
    )


def render_report_result(
    console: Console,
    *,
    period: DateRange,
    repository_count: int,
    session_count: int,
    output_path: Path | None,
    selected: int,
    dry_run: bool = False,
) -> None:
    console.print(Text("✓ Dry run complete" if dry_run else "✓ Report generated", style="bold"))
    console.print()
    console.print(Text(f"Period         {_period_label(period)}"))
    console.print(Text(f"Repositories   {repository_count}"))
    console.print(Text(f"Sessions       {session_count}"))
    output = "Not written (dry run)" if dry_run else str(output_path)
    console.print(Text(f"Output         {output}"))
    console.print()
    for index, label in enumerate(report_result_options(dry_run=dry_run)):
        console.print(_option(label, index, selected))
    console.print()
    console.print(Text("↑↓ / jk Navigate   Enter Select   q Main menu", style="dim"))


def render_report_preview(console: Console, *, content: str, offset: int) -> None:
    """Render a literal, scrollable dry-run report preview."""

    console.print(_viewport_text("Report Preview", style="bold"))
    console.print()
    lines = content.splitlines() or [""]
    capacity = report_preview_capacity(console.size.height)
    max_start = max(0, len(lines) - capacity)
    start = min(max(offset, 0), max_start)
    end = min(len(lines), start + capacity)
    if start:
        console.print(_viewport_text(f"↑ {start} more", style="dim"))
    for line in lines[start:end]:
        console.print(_viewport_text(line))
    if end < len(lines):
        console.print(_viewport_text(f"↓ {len(lines) - end} more", style="dim"))
    console.print(_viewport_text("↑↓ / jk Scroll   b Back   q Main menu", style="dim"))


def render_recoverable_error(
    console: Console,
    *,
    title: str,
    detail: str,
    options: list[str],
    selected: int,
) -> None:
    console.print(Text(f"✗ {title}", style="bold"))
    console.print(Text(redact_text(detail)))
    console.print()
    for index, label in enumerate(options):
        console.print(_option(label, index, selected))
    console.print()
    console.print(Text("↑↓ / jk Navigate   Enter Select   b Back   q Main menu", style="dim"))
