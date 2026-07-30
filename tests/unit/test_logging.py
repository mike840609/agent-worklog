from io import StringIO

import pytest
from rich.console import Console

from agent_worklog.logging import ConsoleReporter, RichProgressReporter
from agent_worklog.progress import NullProgressReporter, ProgressStage


def forced_console(stream: StringIO) -> Console:
    return Console(
        file=stream,
        force_terminal=True,
        color_system=None,
        width=100,
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


def test_progress_is_silent_when_the_terminal_cannot_render_transient_output() -> None:
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
