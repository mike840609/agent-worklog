from datetime import datetime
from io import StringIO
from zoneinfo import ZoneInfo

import pytest
from rich.console import Console

from agent_worklog.logging import ConsoleReporter, RichProgressReporter
from agent_worklog.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from agent_worklog.models.session import AgentSession
from agent_worklog.models.time_range import DateRange
from agent_worklog.progress import NullProgressReporter, ProgressStage
from agent_worklog.services.scan import ScanResult


def forced_console(stream: StringIO, *, width: int = 100) -> Console:
    return Console(
        file=stream,
        force_terminal=True,
        color_system=None,
        width=width,
    )


def test_progress_renders_one_transient_stage_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    output_stream = StringIO()
    progress_stream = StringIO()
    reporter = ConsoleReporter(
        console=forced_console(output_stream),
        progress_console=forced_console(progress_stream),
    )

    with reporter.progress() as progress:
        progress.start(ProgressStage.EXPORTING_SESSIONS, total=3)
        progress.advance(2)
    reporter.message("done")

    progress_output = progress_stream.getvalue()
    assert "Exporting sessions" in progress_output
    assert "2/3" in progress_output
    assert progress_output.count("\n") == 1
    assert progress_output.endswith("\x1b[2K")
    assert "done" in output_stream.getvalue()
    assert "Exporting sessions" not in output_stream.getvalue()


def test_progress_ellipsizes_to_one_row_in_a_narrow_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    progress_stream = StringIO()
    reporter = ConsoleReporter(
        progress_console=forced_console(progress_stream, width=40),
    )

    with reporter.progress() as progress:
        progress.start(ProgressStage.PREPARING_EVIDENCE, total=12345)
        progress.advance(12345)

    progress_output = progress_stream.getvalue()
    assert "…" in progress_output
    assert progress_output.count("\n") == 1


def test_progress_is_silent_when_the_terminal_cannot_render_transient_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERM", "dumb")
    progress_stream = StringIO()
    reporter = ConsoleReporter(progress_console=forced_console(progress_stream))

    with reporter.progress() as progress:
        progress.start(ProgressStage.EXPORTING_SESSIONS, total=3)
        progress.advance(2)

    assert progress_stream.getvalue() == ""


def test_quiet_progress_is_a_no_op() -> None:
    progress_stream = StringIO()
    reporter = ConsoleReporter(
        quiet=True,
        progress_console=forced_console(progress_stream),
    )

    with reporter.progress() as progress:
        assert isinstance(progress, NullProgressReporter)
        progress.start(ProgressStage.DISCOVERING_SESSIONS)

    assert progress_stream.getvalue() == ""


def test_progress_context_finishes_after_an_exception() -> None:
    progress_stream = StringIO()
    reporter = ConsoleReporter(
        progress_console=forced_console(progress_stream),
    )
    active: RichProgressReporter | None = None

    with pytest.raises(RuntimeError, match="boom"), reporter.progress() as progress:
        assert isinstance(progress, RichProgressReporter)
        active = progress
        progress.start(ProgressStage.RENDERING_REPORT)
        raise RuntimeError("boom")

    assert active is not None
    assert active._status is None


def test_progress_context_finishes_after_keyboard_interrupt() -> None:
    progress_stream = StringIO()
    reporter = ConsoleReporter(
        progress_console=forced_console(progress_stream),
    )
    active: RichProgressReporter | None = None

    with pytest.raises(KeyboardInterrupt), reporter.progress() as progress:
        assert isinstance(progress, RichProgressReporter)
        active = progress
        progress.start(ProgressStage.RENDERING_REPORT)
        raise KeyboardInterrupt

    assert active is not None
    assert active._status is None


SCAN_TZ = ZoneInfo("Asia/Taipei")


def scan_result_with(sessions: list[AgentSession]) -> ScanResult:
    identity = RepositoryIdentity(
        repository_id="git:github.com/mike/agent-worklog",
        display_name="Agent Worklog",
        identity_type=RepositoryIdentityType.GIT_REMOTE,
        normalized_remote="github.com/mike/agent-worklog",
        resolution_method="test",
    )
    resolved = [
        ResolvedSession(session=session, repository=identity) for session in sessions
    ]
    return ScanResult(
        period=DateRange(
            since=datetime(2026, 7, 20, tzinfo=SCAN_TZ),
            until=datetime(2026, 7, 27, tzinfo=SCAN_TZ),
        ),
        candidate_session_count=len(sessions),
        loaded_session_count=len(sessions),
        failed_session_count=0,
        resolved_sessions=resolved,
        sessions_by_repository={"git:github.com/mike/agent-worklog": resolved},
        warnings=["One session could not be exported."],
    )


def test_verbose_scan_lists_session_titles_and_directories() -> None:
    output_stream = StringIO()
    reporter = ConsoleReporter(
        verbose=True,
        console=forced_console(output_stream, width=200),
    )

    reporter.scan_result(
        scan_result_with(
            [
                AgentSession(
                    harness="opencode",
                    session_id="ses_abc",
                    title="Fix the exporter",
                    working_directory="/repos/agent-worklog",
                )
            ]
        )
    )

    output = output_stream.getvalue()
    assert "Fix the exporter" in output
    assert "/repos/agent-worklog" in output
    assert "One session could not be exported." in output


def test_a_session_without_a_title_falls_back_to_its_id() -> None:
    output_stream = StringIO()
    reporter = ConsoleReporter(
        verbose=True,
        console=forced_console(output_stream, width=200),
    )

    reporter.scan_result(
        scan_result_with(
            [AgentSession(harness="opencode", session_id="ses_def")]
        )
    )

    assert "ses_def" in output_stream.getvalue()


def test_non_verbose_scan_does_not_list_sessions() -> None:
    output_stream = StringIO()
    reporter = ConsoleReporter(console=forced_console(output_stream, width=200))

    reporter.scan_result(
        scan_result_with(
            [
                AgentSession(
                    harness="opencode",
                    session_id="ses_abc",
                    title="Fix the exporter",
                    working_directory="/repos/agent-worklog",
                )
            ]
        )
    )

    output = output_stream.getvalue()
    assert "Agent Worklog" in output
    assert "Fix the exporter" not in output


def test_quiet_scan_still_prints_only_the_count() -> None:
    output_stream = StringIO()
    reporter = ConsoleReporter(
        quiet=True,
        verbose=False,
        console=forced_console(output_stream, width=200),
    )

    reporter.scan_result(
        scan_result_with(
            [
                AgentSession(
                    harness="opencode",
                    session_id="ses_abc",
                    title="Fix the exporter",
                )
            ]
        )
    )

    assert output_stream.getvalue().strip() == "1"


def test_verbose_scan_redacts_secrets_in_session_titles() -> None:
    """Claude Code transcripts have no upstream sanitize step.

    ConsoleReporter's contract is that callers hand it redacted strings, and a
    scanned title and working directory are both raw harness data, so the
    listing must redact each independently. The two secrets below are
    distinct values so that dropping either redaction call is caught by its
    own assertion, rather than one field's redaction masking the other's.
    """

    output_stream = StringIO()
    reporter = ConsoleReporter(
        verbose=True,
        console=forced_console(output_stream, width=200),
    )

    reporter.scan_result(
        scan_result_with(
            [
                AgentSession(
                    harness="claude-code",
                    session_id="ses_ghi",
                    title="debug with token=hunter2secretvalue",
                    working_directory="/repos/token=dirsecretvalue999",
                )
            ]
        )
    )

    output = output_stream.getvalue()
    assert "hunter2secretvalue" not in output
    assert "dirsecretvalue999" not in output
    assert "[REDACTED]" in output


def test_verbose_scan_collapses_a_multi_line_title_to_one_list_item() -> None:
    """The report path solved this in `_normalized_title`; the console path must too."""

    output_stream = StringIO()
    reporter = ConsoleReporter(
        verbose=True,
        console=forced_console(output_stream, width=200),
    )

    reporter.scan_result(
        scan_result_with(
            [
                AgentSession(
                    harness="opencode",
                    session_id="ses_multiline",
                    title="Line one\nLine two  with   spaces",
                )
            ]
        )
    )

    output = output_stream.getvalue()
    assert "Line one Line two with spaces" in output
    assert "Line one\nLine two" not in output
    lines = [line for line in output.splitlines() if "Line one" in line]
    assert len(lines) == 1


def test_verbose_scan_ellipsizes_a_long_session_line_rather_than_wrapping() -> None:
    """A soft-wrapped continuation starts in column 0, where repository names are.

    Collapsing whitespace keeps a title on one *logical* line; only `no_wrap`
    keeps it on one *rendered* line, so a long path cannot read as a heading.
    """

    output_stream = StringIO()
    reporter = ConsoleReporter(
        verbose=True,
        console=forced_console(output_stream, width=40),
    )

    reporter.scan_result(
        scan_result_with(
            [
                AgentSession(
                    harness="opencode",
                    session_id="ses_long",
                    title="A session title far too long for this terminal",
                    working_directory="/repos/some/deeply/nested/checkout",
                )
            ]
        )
    )

    lines = output_stream.getvalue().splitlines()
    heading = lines.index("Agent Worklog")
    listing = [line for line in lines[heading + 1 :] if line.strip()]

    # One session must render as exactly one line: a second entry here is a
    # wrapped continuation sitting in column 0, indistinguishable from the
    # repository heading above it.
    assert len(listing) == 1
    assert listing[0].startswith("  • ")
    assert listing[0].endswith("…")


def test_verbose_scan_does_not_interpret_a_title_as_rich_markup() -> None:
    """A title is user content; Rich would otherwise eat anything in brackets."""

    output_stream = StringIO()
    reporter = ConsoleReporter(
        verbose=True,
        console=forced_console(output_stream, width=200),
    )

    reporter.scan_result(
        scan_result_with(
            [
                AgentSession(
                    harness="opencode",
                    session_id="ses_jkl",
                    title="[bold]not markup[/bold]",
                )
            ]
        )
    )

    assert "[bold]not markup[/bold]" in output_stream.getvalue()
