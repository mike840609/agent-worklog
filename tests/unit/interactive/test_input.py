from __future__ import annotations

import pytest

from agent_worklog.interactive.input import Key, KeyPress, TerminalInput, normalize_posix_sequence


def test_arrow_enter_space_escape_and_char_sequences_normalize() -> None:
    assert normalize_posix_sequence("\x1b[A") == KeyPress(key=Key.UP)
    assert normalize_posix_sequence("\x1b[B") == KeyPress(key=Key.DOWN)
    assert normalize_posix_sequence("\r") == KeyPress(key=Key.ENTER)
    assert normalize_posix_sequence("\n") == KeyPress(key=Key.ENTER)
    assert normalize_posix_sequence(" ") == KeyPress(key=Key.SPACE)
    assert normalize_posix_sequence("\x1b") == KeyPress(key=Key.ESCAPE)
    assert normalize_posix_sequence("j") == KeyPress(char="j")
    assert normalize_posix_sequence("k") == KeyPress(char="k")
    assert normalize_posix_sequence("\x03") == KeyPress(key=Key.CTRL_C)


def test_unknown_escape_sequence_is_preserved_as_char_input() -> None:
    assert normalize_posix_sequence("x") == KeyPress(char="x")


def test_terminal_context_restores_after_exception() -> None:
    events: list[str] = []
    terminal = TerminalInput(
        setup=lambda: events.append("setup") or "token",
        restore=lambda token: events.append(f"restore:{token}"),
        reader=lambda: "q",
    )

    with pytest.raises(RuntimeError, match="boom"):
        with terminal:
            raise RuntimeError("boom")

    assert events == ["setup", "restore:token"]


def test_read_key_normalizes_the_injected_reader() -> None:
    terminal = TerminalInput(setup=lambda: None, restore=lambda token: None, reader=lambda: "\x1b[A")

    assert terminal.read_key() == KeyPress(key=Key.UP)
