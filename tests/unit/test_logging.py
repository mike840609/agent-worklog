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


def test_progress_renders_generic_stage_and_absolute_count_separately() -> None:
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

    assert "Exporting sessions" in progress_stream.getvalue()
    assert "2/3" in progress_stream.getvalue()
    assert "done" not in progress_stream.getvalue()
    assert "done" in output_stream.getvalue()
    assert "Exporting sessions" not in output_stream.getvalue()


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
