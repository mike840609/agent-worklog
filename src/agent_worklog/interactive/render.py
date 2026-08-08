"""Pure Rich rendering for the interactive Agent Worklog screens."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from pathlib import Path

from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from agent_worklog.interactive.density import (
    is_subagent,
    last_activity_at,
    repository_meta,
    scan_volume,
    session_meta,
    volume_label,
)
from agent_worklog.interactive.models import ReportDraft
from agent_worklog.interactive.selection import SelectionMark, SelectionState, noise_reason
from agent_worklog.models.repository import ResolvedSession
from agent_worklog.models.session import AgentSession
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
# Three glyphs sit side by side carrying three unrelated meanings, so colour is
# what tells them apart. Plain ANSI names only, to follow the terminal's theme.
_MARK_STYLES = {
    SelectionMark.ALL: "green",
    SelectionMark.NONE: "dim",
    SelectionMark.PARTIAL: "yellow",
}
_CURSOR_STYLE = "bold cyan"
# The expansion arrow recedes behind the glyphs that carry a decision.
_EXPANSION_STYLE = "dim"
_ROW_GAP = 3
_MIN_TITLE_CELLS = 12
# Aware, so it orders against the aware UTC timestamps the harnesses record.
_UNDATED = datetime.min.replace(tzinfo=UTC)


def main_menu_options() -> list[str]:
    """Return the main-menu actions in display order."""

    return list(_MAIN_OPTIONS)


def report_setup_options() -> list[str]:
    """Return report-setup actions in display order."""

    return list(_SETUP_OPTIONS)


def _option(label: str, index: int, selected: int) -> str:
    return f"{'❯' if index == selected else ' '} {label}"


def _print_viewport_line(
    console: Console,
    value: str,
    *,
    style: str = "",
) -> None:
    """Print exactly one display line, truncating rather than wrapping."""

    console.print(
        Text(value, style=style),
        no_wrap=True,
        overflow="ellipsis",
    )


def _print_viewport_text(console: Console, text: Text) -> None:
    """Print a pre-composed row, truncating rather than wrapping."""
    console.print(text, no_wrap=True, overflow="ellipsis")


def session_row_meta(
    session: AgentSession,
    tz: tzinfo | None,
    reason: str | None = None,
) -> str:
    """Compose the dim right-hand metadata for one session row."""
    facts = " · ".join(fact for fact in (session_meta(session, tz), reason) if fact)
    if not is_subagent(session):
        return facts
    return f"[sub] {facts}" if facts else "[sub]"


def _cursor_glyph(active: bool) -> tuple[str, str]:
    """The cursor holds column 0 on both row kinds, so the left edge never moves."""

    return ("❯", _CURSOR_STYLE) if active else (" ", "")


def _expansion_glyph(expanded: bool) -> tuple[str, str]:
    return ("▼" if expanded else "▶", _EXPANSION_STYLE)


def _mark_glyph(mark: SelectionMark) -> tuple[str, str]:
    return _MARKERS[mark], _MARK_STYLES[mark]


@dataclass(frozen=True)
class _ListRow:
    """One tree row, decomposed so both kinds lay out against the same columns."""

    lead: Text
    title: str
    meta: str
    selected: bool


def _meta_column_width(rows: list[_ListRow], *, console_width: int) -> int:
    """Width of the metadata column every visible row shares.

    Measured across both kinds, because a per-kind width is exactly how the
    repository and session rows drifted onto different columns. The cap keeps
    the widest lead's title above its floor: one very long session's metadata
    would otherwise starve every title on screen, the whole column with it.
    """

    widest_meta = max((cell_len(row.meta) for row in rows), default=0)
    widest_lead = max((row.lead.cell_len for row in rows), default=0)
    affordable = console_width - widest_lead - _ROW_GAP - _MIN_TITLE_CELLS
    return min(widest_meta, max(0, affordable))


def _list_row(row: _ListRow, *, meta_width: int, console_width: int) -> Text:
    """Left-align the title in a fixed column, with dim metadata in its own column.

    The title absorbs truncation so the metadata column holds still: a ragged
    left edge on the titles is what makes a long list hard to scan. Metadata too
    wide for the shared column is dropped rather than squeezed, so a narrow
    terminal never leaves a row as an ellipsis with no name in it. The lead
    arrives pre-styled, its glyphs already separated by role.
    """
    row_style = "bold" if row.selected else ""
    text = row.lead.copy()
    if not row.meta or cell_len(row.meta) > meta_width:
        text.append(row.title, style=row_style)
        return text
    body = Text(row.title, style=row_style)
    body.truncate(
        console_width - row.lead.cell_len - meta_width - _ROW_GAP,
        overflow="ellipsis",
        pad=True,
    )
    text.append_text(body)
    text.append(" " * _ROW_GAP)
    text.append(row.meta, style="dim")
    return text


def _print_list_rows(console: Console, rows: list[_ListRow]) -> None:
    """Print a tree, every row laid against the one metadata column it shares."""

    width = console.size.width
    meta_width = _meta_column_width(rows, console_width=width)
    for row in rows:
        _print_viewport_text(console, _list_row(row, meta_width=meta_width, console_width=width))


def _print_option_line(console: Console, label: str, index: int, selected: int) -> None:
    _print_viewport_line(
        console,
        _option(label, index, selected),
        style="bold" if index == selected else "",
    )


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
    """Content lines available while reserving the terminal's final display row."""

    return max(0, terminal_height - 7)


def render_main_menu(console: Console, *, selected: int) -> None:
    _print_viewport_line(console, "Agent Worklog", style="bold")
    _print_viewport_line(
        console,
        "Turn coding-agent sessions into engineering reports",
        style="dim",
    )
    console.print()
    for index, label in enumerate(_MAIN_OPTIONS):
        _print_option_line(console, label, index, selected)
    console.print()
    _print_viewport_line(
        console,
        "↑↓ / jk Navigate   Enter Select   1-4 Select   ? Help   q Quit",
        style="dim",
    )


def render_report_setup(console: Console, draft: ReportDraft, *, selected: int) -> None:
    _print_viewport_line(console, "Generate Report", style="bold")
    console.print()
    _print_viewport_line(console, f"Harness      {_harness_label(draft.harness)}")
    _print_viewport_line(console, f"Period       {_period_label(draft.period)}")
    _print_viewport_line(console, f"Detail       {draft.detail.value.title()}")
    _print_viewport_line(
        console,
        f"Subagents    {_bool_label(draft.include_subagents, 'Included', 'Excluded')}",
    )
    _print_viewport_line(
        console,
        f"Narrative    {_bool_label(draft.narrative, 'Enabled', 'Disabled')}",
    )
    sanitize = (
        _bool_label(draft.sanitize, "On", "Off")
        if draft.harness == "opencode"
        else "N/A"
    )
    _print_viewport_line(console, f"Sanitize     {sanitize}")
    _print_viewport_line(console, f"Dry run      {_bool_label(draft.dry_run, 'On', 'Off')}")
    console.print()
    for index, label in enumerate(_SETUP_OPTIONS):
        style = "dim" if label == "Sanitize" and draft.harness != "opencode" else ""
        if index == selected:
            style = "bold" if not style else f"bold {style}"
        _print_viewport_line(console, _option(label, index, selected), style=style)
    console.print()
    _print_viewport_line(
        console,
        "↑↓ / jk Navigate   ←→ / hl Change   Enter Edit   r Review   ? Help   b Back   q Main menu",
        style="dim",
    )


def _session_recency(session: AgentSession) -> datetime:
    """Undated sessions sort last, and never reach a ``None`` comparison."""

    timestamp = last_activity_at(session)
    return _UNDATED if timestamp is None else timestamp


def _repository_recency(sessions: list[ResolvedSession]) -> datetime:
    return max((_session_recency(item.session) for item in sessions), default=_UNDATED)


def _ordered_repositories(scan: ScanResult) -> list[tuple[str, list[ResolvedSession]]]:
    """Order repositories by most recent activity first, then by display name.

    Recency alone is a partial order, so equal timestamps would otherwise settle
    into whatever order the scan happened to yield. Sorting is stable, so the
    name pass runs first and the recency pass keeps it as the tie-break. The id
    joins that key because redaction can map two distinct repositories onto the
    same display name, which would leave the order arbitrary again.
    """

    by_name = sorted(
        scan.sessions_by_repository.items(),
        key=lambda item: (_repository_display_name(scan, item[0]), item[0]),
    )
    return sorted(by_name, key=lambda item: _repository_recency(item[1]), reverse=True)


def _ordered_sessions(sessions: list[ResolvedSession]) -> list[ResolvedSession]:
    """Order a repository's sessions by most recent activity first, then by id."""

    by_id = sorted(sessions, key=lambda item: item.session.session_id)
    return sorted(by_id, key=lambda item: _session_recency(item.session), reverse=True)


def build_visible_rows(
    scan: ScanResult,
    expanded_repositories: set[str],
) -> list[VisibleRow]:
    rows: list[VisibleRow] = []
    for repository_id, sessions in _ordered_repositories(scan):
        rows.append(VisibleRow(kind="repository", repository_id=repository_id))
        if repository_id not in expanded_repositories:
            continue
        rows.extend(
            VisibleRow(
                kind="session",
                repository_id=repository_id,
                session_id=item.session.session_id,
            )
            for item in _ordered_sessions(sessions)
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


def _sessions_by_id(scan: ScanResult) -> dict[str, AgentSession]:
    return {
        item.session.session_id: item.session for item in scan.resolved_sessions
    }


def build_filtered_rows(
    scan: ScanResult,
    expanded_repositories: set[str],
    *,
    query: str,
) -> list[VisibleRow]:
    """Build tree rows filtered by repository name or session title."""

    needle = query.strip().casefold()
    if not needle:
        return build_visible_rows(scan, expanded_repositories)

    titles = _session_titles(scan)
    rows: list[VisibleRow] = []
    for repository_id, sessions in _ordered_repositories(scan):
        repository_matches = needle in _repository_display_name(scan, repository_id).casefold()
        matching_sessions = [
            item
            for item in sessions
            if needle in titles[item.session.session_id].casefold()
        ]
        if not repository_matches and not matching_sessions:
            continue
        rows.append(VisibleRow(kind="repository", repository_id=repository_id))
        visible_sessions = sessions if repository_matches else matching_sessions
        rows.extend(
            VisibleRow(
                kind="session",
                repository_id=repository_id,
                session_id=item.session.session_id,
            )
            for item in _ordered_sessions(visible_sessions)
        )
    return rows


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
    capacity = max(0, terminal_height - reserved_lines - 4)
    if capacity == 0:
        return [], 0, len(rows)
    if len(rows) <= capacity:
        return list(enumerate(rows)), 0, 0
    cursor = min(max(cursor, 0), len(rows) - 1)
    start = min(max(0, cursor - capacity // 2), len(rows) - capacity)
    end = start + capacity
    return list(enumerate(rows[start:end], start=start)), start, len(rows) - end


def _render_search_status(console: Console, query: str, searching: bool) -> None:
    if searching or query:
        label = f"Search: {query}{'_' if searching else ''}"
        _print_viewport_line(console, label, style="dim")


def _scan_warning_label(scan: ScanResult) -> str | None:
    if not scan.warnings and not scan.failed_session_count:
        return None
    parts = []
    if scan.failed_session_count:
        parts.append(f"{scan.failed_session_count} session(s) failed to load")
    if scan.warnings:
        parts.append(f"{len(scan.warnings)} warning(s)")
    return "⚠ " + "   ".join(parts)


def _review_header(selection: SelectionState) -> str:
    """Compose the Review Sessions title, volume clause included.

    A scan can legitimately be all tool-call activity, and a ``0 / 0 msgs``
    suffix is noise, so the clause is dropped rather than shown empty.
    """
    counts = f"Review Sessions   {selection.selected_count} / {selection.total_count} selected"
    if not selection.total_volume:
        return counts
    volume = f"{selection.selected_volume} / {volume_label(selection.total_volume)}"
    return f"{counts} · {volume}"


def render_session_review(
    console: Console,
    selection: SelectionState,
    *,
    expanded_repositories: set[str],
    cursor: int,
    message: str | None = None,
    query: str = "",
    searching: bool = False,
) -> None:
    _print_viewport_line(console, _review_header(selection), style="bold")
    warning_label = _scan_warning_label(selection.scan)
    if warning_label:
        _print_viewport_line(console, warning_label, style="yellow")
    if message:
        _print_viewport_line(console, message)
    _render_search_status(console, query, searching)
    console.print()
    rows = build_filtered_rows(selection.scan, expanded_repositories, query=query)
    visible, hidden_above, hidden_below = _visible_window(
        rows,
        cursor=cursor,
        terminal_height=console.size.height,
        reserved_lines=(7 if message else 6)
        + (1 if warning_label else 0)
        + (1 if searching or query else 0),
    )
    if hidden_above:
        _print_viewport_line(console, f"↑ {hidden_above} more", style="dim")
    titles = _session_titles(selection.scan)
    sessions = _sessions_by_id(selection.scan)
    metas = {
        row.session_id: session_row_meta(
            sessions[row.session_id],
            selection.scan.period.since.tzinfo,
            noise_reason(sessions[row.session_id]),
        )
        for _, row in visible
        if row.session_id is not None
    }
    tree: list[_ListRow] = []
    for index, row in visible:
        cursor_here = index == cursor
        if row.kind == "repository":
            expanded = row.repository_id in expanded_repositories or bool(query)
            mark = selection.repository_mark(row.repository_id)
            selected = sum(
                item.session.session_id in selection.selected_session_ids
                for item in selection.scan.sessions_by_repository[row.repository_id]
            )
            total = len(selection.scan.sessions_by_repository[row.repository_id])
            name = _repository_display_name(selection.scan, row.repository_id)
            tree.append(
                _ListRow(
                    lead=Text.assemble(
                        _cursor_glyph(cursor_here),
                        " ",
                        _expansion_glyph(expanded),
                        " ",
                        _mark_glyph(mark),
                        " ",
                    ),
                    title=f"{name}   {selected} / {total}",
                    meta=repository_meta(row.repository_id, selection.scan),
                    selected=cursor_here,
                )
            )
        else:
            assert row.session_id is not None
            mark = (
                SelectionMark.ALL
                if row.session_id in selection.selected_session_ids
                else SelectionMark.NONE
            )
            tree.append(
                _ListRow(
                    lead=Text.assemble(
                        _cursor_glyph(cursor_here),
                        "     ",
                        _mark_glyph(mark),
                        " ",
                    ),
                    title=titles[row.session_id],
                    meta=metas[row.session_id],
                    selected=cursor_here,
                )
            )
    _print_list_rows(console, tree)
    if hidden_below:
        _print_viewport_line(console, f"↓ {hidden_below} more", style="dim")
    console.print()
    _print_viewport_line(
        console,
        "↑↓ / jk Navigate   ←→ / hl Collapse/Expand   Space Toggle",
        style="dim",
    )
    _print_viewport_line(
        console,
        "a All   n None   g Generate   R Rescan   / Search   ? Help   b Back",
        style="dim",
    )


def _browser_header(scan: ScanResult) -> str:
    """Compose the Browse Sessions title: a scan total, with no selection to compare it to."""
    sessions = f"Browse Sessions   {scan.loaded_session_count} sessions"
    volume = scan_volume(scan)
    if not volume:
        return sessions
    return f"{sessions} · {volume_label(volume)}"


def render_session_browser(
    console: Console,
    scan: ScanResult,
    *,
    expanded_repositories: set[str],
    cursor: int,
    query: str = "",
    searching: bool = False,
) -> None:
    _print_viewport_line(console, _browser_header(scan), style="bold")
    warning_label = _scan_warning_label(scan)
    if warning_label:
        _print_viewport_line(console, warning_label, style="yellow")
    _render_search_status(console, query, searching)
    console.print()
    rows = build_filtered_rows(scan, expanded_repositories, query=query)
    visible, hidden_above, hidden_below = _visible_window(
        rows,
        cursor=cursor,
        terminal_height=console.size.height,
        reserved_lines=5 + (1 if warning_label else 0) + (1 if searching or query else 0),
    )
    if hidden_above:
        _print_viewport_line(console, f"↑ {hidden_above} more", style="dim")
    titles = _session_titles(scan)
    sessions = _sessions_by_id(scan)
    metas = {
        row.session_id: session_row_meta(
            sessions[row.session_id],
            scan.period.since.tzinfo,
        )
        for _, row in visible
        if row.session_id is not None
    }
    tree: list[_ListRow] = []
    for index, row in visible:
        cursor_here = index == cursor
        if row.kind == "repository":
            expanded = row.repository_id in expanded_repositories or bool(query)
            name = _repository_display_name(scan, row.repository_id)
            count = len(scan.sessions_by_repository[row.repository_id])
            tree.append(
                _ListRow(
                    lead=Text.assemble(
                        _cursor_glyph(cursor_here),
                        " ",
                        _expansion_glyph(expanded),
                        " ",
                    ),
                    title=f"{name}   {count}",
                    meta=repository_meta(row.repository_id, scan),
                    selected=cursor_here,
                )
            )
        else:
            assert row.session_id is not None
            tree.append(
                _ListRow(
                    lead=Text.assemble(_cursor_glyph(cursor_here), "      "),
                    title=titles[row.session_id],
                    meta=metas[row.session_id],
                    selected=cursor_here,
                )
            )
    _print_list_rows(console, tree)
    if hidden_below:
        _print_viewport_line(console, f"↓ {hidden_below} more", style="dim")
    console.print()
    _print_viewport_line(
        console,
        "↑↓ / jk Navigate   ←→ / hl Collapse/Expand   R Rescan   / Search   ? Help   b Back",
        style="dim",
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
    _print_viewport_line(
        console,
        "✓ Dry run complete" if dry_run else "✓ Report generated",
        style="bold",
    )
    console.print()
    _print_viewport_line(console, f"Period         {_period_label(period)}")
    _print_viewport_line(console, f"Repositories   {repository_count}")
    _print_viewport_line(console, f"Sessions       {session_count}")
    output = "Not written (dry run)" if dry_run else str(output_path)
    _print_viewport_line(console, f"Output         {output}")
    console.print()
    for index, label in enumerate(report_result_options(dry_run=dry_run)):
        _print_option_line(console, label, index, selected)
    console.print()
    _print_viewport_line(
        console,
        "↑↓ / jk Navigate   Enter Select   ? Help   q Main menu",
        style="dim",
    )


def render_report_preview(console: Console, *, content: str, offset: int) -> None:
    """Render a literal, scrollable dry-run report preview."""

    _print_viewport_line(console, "Report Preview", style="bold")
    console.print()
    lines = content.splitlines() or [""]
    capacity = report_preview_capacity(console.size.height)
    max_start = max(0, len(lines) - capacity) if capacity else len(lines)
    start = min(max(offset, 0), max_start)
    end = min(len(lines), start + capacity)
    if start:
        _print_viewport_line(console, f"↑ {start} more", style="dim")
    for line in lines[start:end]:
        _print_viewport_line(console, line)
    if end < len(lines):
        _print_viewport_line(console, f"↓ {len(lines) - end} more", style="dim")
    _print_viewport_line(
        console,
        "↑↓ / jk Scroll   PgUp/PgDn Page   g/G Top/Bottom   ? Help   b Back",
        style="dim",
    )


def _detail_window(
    lines: list[str],
    *,
    offset: int,
    capacity: int,
) -> tuple[list[str], int, int]:
    if capacity <= 0 or not lines:
        return [], 0, len(lines)
    offset = min(max(offset, 0), max(0, len(lines) - 1))
    hidden_above = offset
    indicator_slots = 1 if hidden_above else 0
    body_capacity = max(0, capacity - indicator_slots)
    end = min(len(lines), offset + body_capacity)
    hidden_below = len(lines) - end
    if hidden_below and body_capacity > 0:
        body_capacity -= 1
        end = min(len(lines), offset + body_capacity)
        hidden_below = len(lines) - end
    return lines[offset:end], hidden_above, hidden_below


def recoverable_error_detail_capacity(terminal_height: int, option_count: int) -> int:
    """Rows available for error detail while actions remain visible."""

    return max(0, terminal_height - option_count - 6)


def render_recoverable_error(
    console: Console,
    *,
    title: str,
    detail: str,
    options: list[str],
    selected: int,
    detail_offset: int = 0,
) -> None:
    _print_viewport_line(console, f"✗ {title}", style="bold")
    console.print()
    lines = redact_text(detail).splitlines() or [""]
    visible, hidden_above, hidden_below = _detail_window(
        lines,
        offset=detail_offset,
        capacity=recoverable_error_detail_capacity(console.size.height, len(options)),
    )
    if hidden_above:
        _print_viewport_line(console, f"↑ {hidden_above} more detail lines", style="dim")
    for line in visible:
        _print_viewport_line(console, line)
    if hidden_below:
        _print_viewport_line(console, f"↓ {hidden_below} more detail lines", style="dim")
    console.print()
    for index, label in enumerate(options):
        _print_option_line(console, label, index, selected)
    console.print()
    _print_viewport_line(
        console,
        "↑↓ / jk Navigate   PgUp/PgDn Detail   Enter Select   ? Help   b Back",
        style="dim",
    )


def render_help(console: Console) -> None:
    """Render the shared keyboard shortcut reference."""

    _print_viewport_line(console, "Keyboard shortcuts", style="bold")
    console.print()
    for line in (
        "↑↓ / jk        Move selection or scroll one line",
        "←→ / hl        Collapse / expand tree rows or change setup values",
        "Enter / Space  Activate / toggle",
        "PgUp / PgDn    Scroll error details or report preview by a page",
        "g / G          Jump to top / bottom in report preview",
        "R              Rescan sessions",
        "/              Search repositories and session titles",
        "?              Open this help",
        "b / Esc        Back",
        "q              Main menu / quit from main menu",
        "Ctrl-C         Cancel the current operation and go back",
    ):
        _print_viewport_line(console, line)
    console.print()
    _print_viewport_line(console, "b / Esc / Enter Back", style="dim")
