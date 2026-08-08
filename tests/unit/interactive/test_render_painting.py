"""The interactive loop paints frames over each other rather than clearing between them."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from agent_worklog.interactive import controller


def _terminal_console() -> tuple[Console, StringIO]:
    stream = StringIO()
    return (
        Console(file=stream, force_terminal=True, width=60, height=20, color_system=None),
        stream,
    )


def _plain_console() -> tuple[Console, StringIO]:
    stream = StringIO()
    return (
        Console(file=stream, force_terminal=False, width=60, height=20, color_system=None),
        stream,
    )


def test_a_frame_never_clears_the_screen() -> None:
    """Clearing then reprinting is what showed a blank screen between frames."""

    console, stream = _terminal_console()

    controller._render(controller._State(), console)

    written = stream.getvalue()
    assert "\x1b[2J" not in written
    assert "\x1b[3J" not in written


def test_a_frame_starts_at_home_and_erases_below_itself() -> None:
    """Home puts the frame over the last one; the trailing erase drops its leftovers."""

    console, stream = _terminal_console()

    controller._render(controller._State(), console)

    written = stream.getvalue()
    assert written.startswith("\x1b[H")
    assert written.endswith("\x1b[J")


def test_every_painted_line_erases_only_its_own_tail() -> None:
    """A line must clear what the previous frame left to its right, and nothing more."""

    console, stream = _terminal_console()

    controller._render(controller._State(), console)

    written = stream.getvalue()
    body = written[len("\x1b[H") : -len("\x1b[J")]
    lines = body.split("\n")[:-1]
    assert lines
    assert all(line.endswith("\x1b[K") for line in lines)


def test_painting_does_not_change_what_the_screen_says() -> None:
    """The cursor control is the only difference between the two paths."""

    console, stream = _terminal_console()
    controller._render(controller._State(), console)
    painted = stream.getvalue()

    plain_console, plain_stream = _plain_console()
    controller._render(controller._State(), plain_console)

    stripped = painted.replace("\x1b[H", "").replace("\x1b[K", "").replace("\x1b[J", "")
    assert stripped == plain_stream.getvalue()


def test_a_non_terminal_console_is_painted_with_nothing() -> None:
    """Captured output and CI logs must stay free of cursor control."""

    console, stream = _plain_console()

    controller._render(controller._State(), console)

    written = stream.getvalue()
    assert "\x1b[H" not in written
    assert "\x1b[K" not in written
    assert "\x1b[J" not in written