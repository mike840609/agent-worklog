from __future__ import annotations

from datetime import datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

from rich.console import Console

from agent_worklog.interactive.models import ReportDraft
from agent_worklog.interactive.render import (
    render_main_menu,
    render_recoverable_error,
    render_report_result,
    render_report_setup,
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


def _console() -> tuple[Console, StringIO]:
    stream = StringIO()
    return (
        Console(file=stream, color_system=None, force_terminal=False, width=100),
        stream,
    )


def _period() -> DateRange:
    return DateRange(
        since=datetime(2026, 8, 3, tzinfo=TZ),
        until=datetime(2026, 8, 10, tzinfo=TZ),
    )


def _resolved(session_id: str, repo: str) -> ResolvedSession:
    return ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id=session_id,
            title=f"Work on {session_id}",
            working_directory=f"/tmp/{repo}",
        ),
        repository=RepositoryIdentity(
            repository_id=repo,
            display_name=repo,
            identity_type=RepositoryIdentityType.PATH_FALLBACK,
            working_directory=f"/tmp/{repo}",
            resolution_method="test",
        ),
    )


def _selection(
    *,
    failed_session_count: int = 0,
    warnings: list[str] | None = None,
) -> SelectionState:
    sessions = [
        _resolved("ses-a1", "repo-a"),
        _resolved("ses-a2", "repo-a"),
        _resolved("ses-b1", "repo-b"),
    ]
    scan = ScanResult(
        period=_period(),
        candidate_session_count=3,
        loaded_session_count=3,
        failed_session_count=failed_session_count,
        resolved_sessions=sessions,
        sessions_by_repository={"repo-a": sessions[:2], "repo-b": sessions[2:]},
        warnings=warnings or [],
    )
    state = SelectionState.from_scan(scan)
    state.toggle_session("ses-a2")
    state.toggle_repository("repo-b")
    return state


def test_main_menu_renders_navigation_and_footer() -> None:
    console, stream = _console()

    render_main_menu(console, selected=0)

    text = stream.getvalue()
    assert "Agent Worklog" in text
    assert "❯ Generate Report" in text
    assert "Browse Sessions" in text
    assert "↑↓ / jk Navigate" in text
    assert "Enter Select" in text
    assert "q Quit" in text


def test_report_setup_renders_current_values_and_review_action() -> None:
    console, stream = _console()
    draft = ReportDraft(harness="opencode", period=_period())

    render_report_setup(console, draft, selected=0)

    text = stream.getvalue()
    assert "Generate Report" in text
    assert "Harness" in text and "OpenCode" in text
    assert "Detail" in text and "Full" in text
    assert "Subagents" in text and "Included" in text
    assert "Narrative" in text and "Enabled" in text
    assert "Sanitize" in text and "Off" in text
    assert "Dry run" in text
    assert "❯ Review sessions" in text
    assert "r Review" in text
    assert "b Back" in text


def test_session_review_renders_group_marks_expansion_and_controls() -> None:
    console, stream = _console()
    state = _selection()

    render_session_review(
        console,
        state,
        expanded_repositories={"repo-a"},
        cursor=0,
    )

    text = stream.getvalue()
    assert "Review Sessions" in text
    assert "1 / 3 selected" in text
    assert "◐ repo-a" in text
    assert "○ repo-b" in text
    assert "Work on ses-a1" in text
    assert "Work on ses-a2" in text
    assert "Space Toggle" in text
    assert "g Generate" in text
    assert "b Back" in text


def test_session_review_surfaces_scan_warnings() -> None:
    console, stream = _console()
    state = _selection(
        failed_session_count=1,
        warnings=["skipped ses-x1: unreadable transcript"],
    )

    render_session_review(console, state, expanded_repositories=set(), cursor=0)

    text = stream.getvalue()
    assert "⚠" in text
    assert "1 session(s) failed to load" in text
    assert "1 warning(s)" in text


def test_session_review_hides_warning_line_when_scan_is_clean() -> None:
    console, stream = _console()
    state = _selection()

    render_session_review(console, state, expanded_repositories=set(), cursor=0)

    assert "⚠" not in stream.getvalue()


def test_session_browser_surfaces_scan_warnings() -> None:
    console, stream = _console()
    state = _selection(warnings=["skipped ses-x1: unreadable transcript"])

    render_session_browser(console, state.scan, expanded_repositories=set(), cursor=0)

    text = stream.getvalue()
    assert "⚠" in text
    assert "1 warning(s)" in text


def test_report_result_renders_summary_and_next_actions() -> None:
    console, stream = _console()

    render_report_result(
        console,
        period=_period(),
        repository_count=2,
        session_count=3,
        output_path=Path("reports/worklog.md"),
        selected=0,
    )

    text = stream.getvalue()
    assert "Report generated" in text
    assert "Repositories" in text and "2" in text
    assert "Sessions" in text and "3" in text
    assert "reports/worklog.md" in text
    assert "Back to main menu" in text
    assert "Generate another report" in text
    assert "Print report path" in text


def test_recoverable_error_renders_safe_detail_and_options() -> None:
    console, stream = _console()

    render_recoverable_error(
        console,
        title="Could not read OpenCode sessions",
        detail="session store missing",
        options=["Change harness", "Back", "Main menu"],
        selected=1,
    )

    text = stream.getvalue()
    assert "Could not read OpenCode sessions" in text
    assert "session store missing" in text
    assert "❯ Back" in text


def test_session_review_labels_a_deselected_noise_session_with_its_reason() -> None:
    console, stream = _console()
    untitled = ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id="ses-untitled",
            title=None,
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
    sessions = [_resolved("ses-a1", "repo-a"), untitled]
    scan = ScanResult(
        period=_period(),
        candidate_session_count=2,
        loaded_session_count=2,
        failed_session_count=0,
        resolved_sessions=sessions,
        sessions_by_repository={"repo-a": sessions},
    )

    render_session_review(
        console,
        SelectionState.from_scan(scan),
        expanded_repositories={"repo-a"},
        cursor=0,
    )

    assert "No title" in stream.getvalue()
