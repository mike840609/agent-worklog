from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

from rich.console import Console

from agent_worklog.errors import HarnessSourceError
from agent_worklog.interactive.controller import (
    InteractiveActions,
    InteractiveReportResult,
    run_interactive,
)
from agent_worklog.interactive.input import Key, KeyPress
from agent_worklog.interactive.models import ReportDraft
from agent_worklog.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from agent_worklog.models.session import AgentSession
from agent_worklog.models.time_range import DateRange
from agent_worklog.services.scan import ScanResult

TZ = ZoneInfo("Asia/Taipei")


def char(value: str) -> KeyPress:
    return KeyPress(char=value)


class ScriptedInput:
    def __init__(self, keys: list[KeyPress]) -> None:
        self._keys: Iterator[KeyPress] = iter(keys)
        self.entered = 0
        self.exited = 0

    def __enter__(self) -> ScriptedInput:
        self.entered += 1
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.exited += 1

    def read_key(self) -> KeyPress:
        return next(self._keys)


def _console() -> Console:
    return Console(
        file=StringIO(),
        color_system=None,
        force_terminal=False,
        width=100,
    )


def _period(day: int = 3) -> DateRange:
    return DateRange(
        since=datetime(2026, 8, day, tzinfo=TZ),
        until=datetime(2026, 8, day + 7, tzinfo=TZ),
    )


def _scan(count: int = 1) -> ScanResult:
    sessions: list[ResolvedSession] = []
    for index in range(count):
        repository_id = "repo-a"
        sessions.append(
            ResolvedSession(
                session=AgentSession(
                    harness="opencode",
                    session_id=f"ses-{index}",
                    title=f"Session {index}",
                    working_directory="/tmp/repo-a",
                ),
                repository=RepositoryIdentity(
                    repository_id=repository_id,
                    display_name="repo-a",
                    identity_type=RepositoryIdentityType.PATH_FALLBACK,
                    working_directory="/tmp/repo-a",
                    resolution_method="test",
                ),
            )
        )
    groups = {"repo-a": sessions} if sessions else {}
    return ScanResult(
        period=_period(),
        candidate_session_count=count,
        loaded_session_count=count,
        failed_session_count=0,
        resolved_sessions=sessions,
        sessions_by_repository=groups,
    )


def _actions(
    *,
    scan_callback=None,
    draft: ReportDraft | None = None,
    counters: dict[str, int] | None = None,
) -> InteractiveActions:
    counters = counters if counters is not None else {}
    report_draft = draft or ReportDraft(harness="opencode", period=_period())

    def count(name: str) -> None:
        counters[name] = counters.get(name, 0) + 1

    def new_draft() -> ReportDraft:
        count("draft")
        return report_draft

    def choose_harness(current: str) -> str:
        count("choose_harness")
        return "codex" if current != "codex" else "opencode"

    def choose_period(current: DateRange) -> DateRange:
        count("choose_period")
        return _period(10)

    def scan(draft_value: ReportDraft) -> ScanResult:
        count("scan")
        if scan_callback is not None:
            return scan_callback(draft_value)
        return _scan()

    def generate(
        draft_value: ReportDraft,
        scan_value: ScanResult,
        force: bool,
    ) -> InteractiveReportResult:
        count("generate")
        return InteractiveReportResult(
            output_path=Path("reports/worklog.md"),
            content="report",
            repository_count=len(scan_value.sessions_by_repository),
            session_count=scan_value.loaded_session_count,
        )

    return InteractiveActions(
        new_draft=new_draft,
        choose_harness=choose_harness,
        choose_period=choose_period,
        scan=scan,
        generate=generate,
        doctor=lambda harness: [f"{harness}: ok"],
        edit_settings=lambda: None,
    )


def test_numeric_generate_then_back_returns_to_main_without_restarting() -> None:
    counters: dict[str, int] = {}
    input_source = ScriptedInput([char("1"), char("b"), char("q")])

    run_interactive(
        actions=_actions(counters=counters),
        input_source=input_source,
        console=_console(),
    )

    assert counters["draft"] == 1
    assert input_source.entered == input_source.exited == 3


def test_arrow_navigation_enters_read_only_browse_and_returns() -> None:
    counters: dict[str, int] = {}
    input_source = ScriptedInput(
        [
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.ENTER),
            KeyPress(key=Key.ENTER),
            KeyPress(key=Key.SPACE),
            char("b"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(counters=counters),
        input_source=input_source,
        console=_console(),
    )

    assert counters["choose_harness"] == 1
    assert counters["choose_period"] == 1
    assert counters["scan"] == 1
    assert counters.get("generate", 0) == 0


def test_review_reuses_cached_scan_after_back() -> None:
    counters: dict[str, int] = {}
    input_source = ScriptedInput(
        [
            char("1"),
            char("r"),
            char("b"),
            char("r"),
            char("b"),
            char("b"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(counters=counters),
        input_source=input_source,
        console=_console(),
    )

    assert counters["scan"] == 1


def test_setup_detail_edit_does_not_require_a_scan() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    input_source = ScriptedInput(
        [
            char("1"),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.ENTER),
            char("b"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(draft=draft),
        input_source=input_source,
        console=_console(),
    )

    assert draft.detail.value == "brief"


def test_harness_source_error_is_recoverable_by_changing_harness() -> None:
    counters: dict[str, int] = {}

    def fail_scan(draft: ReportDraft) -> ScanResult:
        raise HarnessSourceError("session store missing")

    input_source = ScriptedInput(
        [char("1"), char("r"), KeyPress(key=Key.ENTER), char("b"), char("q")]
    )

    run_interactive(
        actions=_actions(scan_callback=fail_scan, counters=counters),
        input_source=input_source,
        console=_console(),
    )

    assert counters["scan"] == 1
    assert counters["choose_harness"] == 1


def test_zero_sessions_is_recoverable_by_changing_period() -> None:
    counters: dict[str, int] = {}
    input_source = ScriptedInput(
        [char("1"), char("r"), KeyPress(key=Key.ENTER), char("b"), char("q")]
    )

    run_interactive(
        actions=_actions(scan_callback=lambda draft: _scan(0), counters=counters),
        input_source=input_source,
        console=_console(),
    )

    assert counters["scan"] == 1
    assert counters["choose_period"] == 1
