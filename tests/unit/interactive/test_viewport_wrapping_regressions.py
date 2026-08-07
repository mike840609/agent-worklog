from __future__ import annotations

from datetime import datetime
from io import StringIO
from zoneinfo import ZoneInfo

from rich.console import Console

from agent_worklog.interactive.render import (
    render_report_preview,
    render_session_browser,
    render_session_review,
)
from agent_worklog.interactive.selection import SelectionState
from agent_worklog.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from agent_worklog.models.session import AgentSession
from agent_worklog.models.time_range import DateRange
from agent_worklog.services.scan import ScanResult

TZ = ZoneInfo("Asia/Taipei")


def _console(*, width: int = 40, height: int = 20) -> tuple[Console, StringIO]:
    stream = StringIO()
    return (
        Console(
            file=stream,
            color_system=None,
            force_terminal=False,
            width=width,
            height=height,
        ),
        stream,
    )


def _period() -> DateRange:
    return DateRange(
        since=datetime(2026, 8, 3, tzinfo=TZ),
        until=datetime(2026, 8, 10, tzinfo=TZ),
    )


def _scan(count: int, *, long_titles: bool = False) -> ScanResult:
    sessions: list[ResolvedSession] = []
    for index in range(count):
        title = (
            f"Session {index} " + "very-long-branch-or-commit-title-" * 5
            if long_titles
            else f"Session {index}"
        )
        sessions.append(
            ResolvedSession(
                session=AgentSession(
                    harness="opencode",
                    session_id=f"ses-{index}",
                    title=title,
                    working_directory="/tmp/repo-a",
                ),
                repository=RepositoryIdentity(
                    repository_id="repo-a",
                    display_name="repo-a",
                    identity_type=RepositoryIdentityType.PATH_FALLBACK,
                    working_directory="/tmp/repo-a",
                    resolution_method="test",
                ),
            )
        )
    return ScanResult(
        period=_period(),
        candidate_session_count=count,
        loaded_session_count=count,
        failed_session_count=0,
        resolved_sessions=sessions,
        sessions_by_repository={"repo-a": sessions},
    )


def _display_lines(stream: StringIO) -> list[str]:
    return stream.getvalue().splitlines()


def test_session_review_long_titles_do_not_exceed_terminal_display_budget() -> None:
    console, stream = _console(width=40, height=20)
    selection = SelectionState.from_scan(_scan(12, long_titles=True))

    render_session_review(
        console,
        selection,
        expanded_repositories={"repo-a"},
        cursor=12,
    )

    assert len(_display_lines(stream)) <= console.size.height - 1
    assert "Session 11" in stream.getvalue()


def test_session_browser_long_titles_do_not_exceed_terminal_display_budget() -> None:
    console, stream = _console(width=40, height=20)
    scan = _scan(12, long_titles=True)

    render_session_browser(
        console,
        scan,
        expanded_repositories={"repo-a"},
        cursor=12,
    )

    assert len(_display_lines(stream)) <= console.size.height - 1
    assert "Session 11" in stream.getvalue()


def test_report_preview_long_lines_do_not_exceed_terminal_display_budget() -> None:
    console, stream = _console(width=40, height=20)
    content = "\n".join(
        f"Line {index} " + "long-report-content-" * 8
        for index in range(20)
    )

    render_report_preview(console, content=content, offset=5)

    assert len(_display_lines(stream)) <= console.size.height - 1
    assert "Line 5" in stream.getvalue()


def test_session_review_reserves_last_terminal_line_when_both_indicators_show() -> None:
    console, stream = _console(width=100, height=12)
    selection = SelectionState.from_scan(_scan(20))

    render_session_review(
        console,
        selection,
        expanded_repositories={"repo-a"},
        cursor=10,
    )

    text = stream.getvalue()
    assert "↑ " in text
    assert "↓ " in text
    assert len(_display_lines(stream)) <= console.size.height - 1


def test_report_preview_reserves_last_terminal_line_when_both_indicators_show() -> None:
    console, stream = _console(width=100, height=12)
    content = "\n".join(f"Line {index}" for index in range(30))

    render_report_preview(console, content=content, offset=10)

    text = stream.getvalue()
    assert "↑ " in text
    assert "↓ " in text
    assert len(_display_lines(stream)) <= console.size.height - 1
