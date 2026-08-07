"""State-machine controller for the terminal-native Agent Worklog experience."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Self

from rich.console import Console

from agent_worklog.errors import AgentWorklogError, HarnessSourceError
from agent_worklog.interactive.input import Key, KeyPress
from agent_worklog.interactive.models import ReportDraft, Screen
from agent_worklog.interactive.render import (
    build_visible_rows,
    render_main_menu,
    render_recoverable_error,
    render_report_setup,
    render_session_browser,
    render_session_review,
)
from agent_worklog.interactive.selection import SelectionState
from agent_worklog.models.time_range import DateRange
from agent_worklog.renderers.markdown import DetailLevel
from agent_worklog.services.scan import ScanResult


class KeySource(Protocol):
    """Minimal input contract; one context restores terminal mode after each key."""

    def __enter__(self) -> Self: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    def read_key(self) -> KeyPress: ...


@dataclass(frozen=True)
class InteractiveReportResult:
    output_path: Path | None
    content: str
    repository_count: int
    session_count: int


@dataclass(frozen=True)
class InteractiveActions:
    """Business-logic seams supplied by `cli.py`, keeping this module cycle-free."""

    new_draft: Callable[[], ReportDraft]
    choose_harness: Callable[[str], str]
    choose_period: Callable[[DateRange], DateRange]
    scan: Callable[[ReportDraft], ScanResult]
    generate: Callable[[ReportDraft, ScanResult, bool], InteractiveReportResult]
    doctor: Callable[[str], list[str]]
    edit_settings: Callable[[], None]


@dataclass
class _ErrorState:
    kind: str
    title: str
    detail: str
    selected: int = 0


@dataclass
class _State:
    screen: Screen = Screen.MAIN
    main_cursor: int = 0
    setup_cursor: int = 0
    browser_cursor: int = 0
    review_cursor: int = 0
    draft: ReportDraft | None = None
    browser_scan: ScanResult | None = None
    selection: SelectionState | None = None
    expanded_repositories: set[str] | None = None
    error: _ErrorState | None = None

    def expansions(self) -> set[str]:
        if self.expanded_repositories is None:
            self.expanded_repositories = set()
        return self.expanded_repositories


def _read_key(input_source: KeySource) -> KeyPress:
    """Read exactly one key while guaranteeing terminal restoration before actions run."""

    with input_source:
        return input_source.read_key()


def _char(key: KeyPress, value: str) -> bool:
    return key.char is not None and key.char.casefold() == value


def _move(cursor: int, key: KeyPress, count: int) -> int:
    if count <= 0:
        return 0
    up = key.key is Key.UP or _char(key, "k")
    down = key.key is Key.DOWN or _char(key, "j")
    if up:
        return max(0, cursor - 1)
    if down:
        return min(count - 1, cursor + 1)
    return cursor


def _clear_if_terminal(console: Console) -> None:
    if console.is_terminal:
        console.clear()


def _new_report(state: _State, actions: InteractiveActions) -> None:
    state.draft = actions.new_draft()
    state.setup_cursor = 0
    state.selection = None
    state.expanded_repositories = set()
    state.screen = Screen.REPORT_SETUP


def _begin_browse(state: _State, actions: InteractiveActions) -> None:
    draft = actions.new_draft()
    draft.set_harness(actions.choose_harness(draft.harness))
    if draft.harness != "opencode":
        draft.set_sanitize(False)
    draft.set_period(actions.choose_period(draft.period))
    try:
        scan = actions.scan(draft)
    except AgentWorklogError as exc:
        state.draft = draft
        state.error = _ErrorState(
            kind="browse-source",
            title=f"Could not read {draft.harness} sessions",
            detail=str(exc),
        )
        state.screen = Screen.RECOVERABLE_ERROR
        return
    if scan.loaded_session_count == 0:
        state.draft = draft
        state.error = _ErrorState(
            kind="browse-empty",
            title="No sessions found",
            detail="No activity matched the selected harness and period.",
        )
        state.screen = Screen.RECOVERABLE_ERROR
        return
    state.browser_scan = scan
    state.browser_cursor = 0
    state.expanded_repositories = set()
    state.screen = Screen.SESSION_BROWSER


def _review(state: _State, actions: InteractiveActions) -> None:
    assert state.draft is not None
    draft = state.draft
    if draft.scan is None:
        try:
            scan = actions.scan(draft)
        except AgentWorklogError as exc:
            state.error = _ErrorState(
                kind="report-source",
                title=f"Could not read {draft.harness} sessions",
                detail=str(exc),
            )
            state.screen = Screen.RECOVERABLE_ERROR
            return
        if scan.loaded_session_count == 0:
            state.error = _ErrorState(
                kind="report-empty",
                title="No sessions found",
                detail="No activity matched the selected harness and period.",
            )
            state.screen = Screen.RECOVERABLE_ERROR
            return
        draft.set_scan(scan)
    state.selection = SelectionState.from_scan(
        draft.scan,
        selected_session_ids=draft.selected_session_ids,
    )
    state.review_cursor = 0
    state.expanded_repositories = set()
    state.screen = Screen.SESSION_REVIEW


def _main_key(
    state: _State,
    key: KeyPress,
    actions: InteractiveActions,
    console: Console,
) -> None:
    state.main_cursor = _move(state.main_cursor, key, 4)
    if key.key in {Key.ESCAPE, Key.CTRL_C} or _char(key, "q"):
        state.screen = Screen.EXIT
        return
    if key.char in {"1", "2", "3", "4"}:
        state.main_cursor = int(key.char) - 1
        activate = True
    else:
        activate = key.key is Key.ENTER
    if not activate:
        return

    if state.main_cursor == 0:
        _new_report(state, actions)
    elif state.main_cursor == 1:
        _begin_browse(state, actions)
    elif state.main_cursor == 2:
        draft = actions.new_draft()
        harness = actions.choose_harness(draft.harness)
        try:
            lines = actions.doctor(harness)
        except AgentWorklogError as exc:
            console.print(f"Doctor error: {exc}")
        else:
            for line in lines:
                console.print(line)
    else:
        actions.edit_settings()


def _setup_key(state: _State, key: KeyPress, actions: InteractiveActions) -> None:
    assert state.draft is not None
    draft = state.draft
    state.setup_cursor = _move(state.setup_cursor, key, 9)
    if key.key is Key.CTRL_C or _char(key, "q"):
        state.screen = Screen.MAIN
        return
    if key.key is Key.ESCAPE or _char(key, "b"):
        state.screen = Screen.MAIN
        return
    if _char(key, "r"):
        _review(state, actions)
        return
    if key.key is not Key.ENTER:
        return

    choice = state.setup_cursor
    if choice == 0:
        _review(state, actions)
    elif choice == 1:
        draft.set_harness(actions.choose_harness(draft.harness))
        if draft.harness != "opencode":
            draft.set_sanitize(False)
    elif choice == 2:
        draft.set_period(actions.choose_period(draft.period))
    elif choice == 3:
        detail = DetailLevel.BRIEF if draft.detail is DetailLevel.FULL else DetailLevel.FULL
        draft.set_detail(detail)
    elif choice == 4:
        draft.set_include_subagents(not draft.include_subagents)
    elif choice == 5:
        draft.set_narrative(not draft.narrative)
    elif choice == 6 and draft.harness == "opencode":
        draft.set_sanitize(not draft.sanitize)
    elif choice == 7:
        draft.set_dry_run(not draft.dry_run)
    else:
        state.screen = Screen.MAIN


def _browser_key(state: _State, key: KeyPress) -> None:
    assert state.browser_scan is not None
    rows = build_visible_rows(state.browser_scan, state.expansions())
    state.browser_cursor = _move(state.browser_cursor, key, len(rows))
    if key.key is Key.CTRL_C or _char(key, "q"):
        state.screen = Screen.MAIN
        return
    if key.key is Key.ESCAPE or _char(key, "b"):
        state.screen = Screen.MAIN
        return
    if key.key is not Key.ENTER or not rows:
        return
    row = rows[state.browser_cursor]
    if row.kind != "repository":
        return
    expanded = state.expansions()
    if row.repository_id in expanded:
        expanded.remove(row.repository_id)
    else:
        expanded.add(row.repository_id)
    visible_count = len(build_visible_rows(state.browser_scan, expanded))
    state.browser_cursor = min(state.browser_cursor, max(0, visible_count - 1))


def _review_key(state: _State, key: KeyPress) -> None:
    assert state.selection is not None
    rows = build_visible_rows(state.selection.scan, state.expansions())
    state.review_cursor = _move(state.review_cursor, key, len(rows))
    if key.key is Key.CTRL_C or _char(key, "q"):
        state.screen = Screen.MAIN
        return
    if key.key is Key.ESCAPE or _char(key, "b"):
        state.draft.selected_session_ids = state.selection.selected_session_ids
        state.screen = Screen.REPORT_SETUP
        return
    if key.key is Key.ENTER and rows:
        row = rows[state.review_cursor]
        if row.kind == "repository":
            expanded = state.expansions()
            if row.repository_id in expanded:
                expanded.remove(row.repository_id)
            else:
                expanded.add(row.repository_id)
            state.review_cursor = min(
                state.review_cursor,
                max(0, len(build_visible_rows(state.selection.scan, expanded)) - 1),
            )


def _error_options(error: _ErrorState) -> list[str]:
    if error.kind in {"report-empty", "browse-empty"}:
        return ["Change period", "Change harness", "Back", "Main menu"]
    return ["Change harness", "Back", "Main menu"]


def _error_key(state: _State, key: KeyPress, actions: InteractiveActions) -> None:
    assert state.error is not None
    error = state.error
    options = _error_options(error)
    error.selected = _move(error.selected, key, len(options))
    if key.key is Key.CTRL_C or _char(key, "q"):
        state.screen = Screen.MAIN
        return
    if key.key is Key.ESCAPE or _char(key, "b"):
        state.screen = Screen.REPORT_SETUP if state.draft is not None else Screen.MAIN
        return
    if key.key is not Key.ENTER:
        return

    choice = options[error.selected]
    if choice == "Main menu":
        state.screen = Screen.MAIN
        return
    if choice == "Back":
        state.screen = Screen.REPORT_SETUP if error.kind.startswith("report") else Screen.MAIN
        return
    assert state.draft is not None
    if choice == "Change harness":
        state.draft.set_harness(actions.choose_harness(state.draft.harness))
        if state.draft.harness != "opencode":
            state.draft.set_sanitize(False)
    else:
        state.draft.set_period(actions.choose_period(state.draft.period))
    state.screen = Screen.REPORT_SETUP if error.kind.startswith("report") else Screen.MAIN


def _render(state: _State, console: Console) -> None:
    _clear_if_terminal(console)
    if state.screen is Screen.MAIN:
        render_main_menu(console, selected=state.main_cursor)
    elif state.screen is Screen.REPORT_SETUP:
        assert state.draft is not None
        render_report_setup(console, state.draft, selected=state.setup_cursor)
    elif state.screen is Screen.SESSION_BROWSER:
        assert state.browser_scan is not None
        render_session_browser(
            console,
            state.browser_scan,
            expanded_repositories=state.expansions(),
            cursor=state.browser_cursor,
        )
    elif state.screen is Screen.SESSION_REVIEW:
        assert state.selection is not None
        render_session_review(
            console,
            state.selection,
            expanded_repositories=state.expansions(),
            cursor=state.review_cursor,
        )
    elif state.screen is Screen.RECOVERABLE_ERROR:
        assert state.error is not None
        render_recoverable_error(
            console,
            title=state.error.title,
            detail=state.error.detail,
            options=_error_options(state.error),
            selected=state.error.selected,
        )


def run_interactive(
    *,
    actions: InteractiveActions,
    input_source: KeySource,
    console: Console,
) -> None:
    """Run the terminal interaction until the user explicitly leaves it."""

    state = _State()
    while state.screen is not Screen.EXIT:
        _render(state, console)
        try:
            key = _read_key(input_source)
        except KeyboardInterrupt:
            return
        if state.screen is Screen.MAIN:
            _main_key(state, key, actions, console)
        elif state.screen is Screen.REPORT_SETUP:
            _setup_key(state, key, actions)
        elif state.screen is Screen.SESSION_BROWSER:
            _browser_key(state, key)
        elif state.screen is Screen.SESSION_REVIEW:
            _review_key(state, key)
        elif state.screen is Screen.RECOVERABLE_ERROR:
            _error_key(state, key, actions)
