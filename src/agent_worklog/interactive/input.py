"""Safe, normalized terminal key input for the interactive CLI."""

from __future__ import annotations

import os
import select
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class Key(StrEnum):
    UP = "up"
    DOWN = "down"
    ENTER = "enter"
    SPACE = "space"
    ESCAPE = "escape"
    CTRL_C = "ctrl_c"


@dataclass(frozen=True)
class KeyPress:
    key: Key | None = None
    char: str | None = None


def normalize_posix_sequence(value: str) -> KeyPress:
    """Convert one POSIX terminal sequence into a logical key press."""

    mapping = {
        "\x1b[A": Key.UP,
        "\x1b[B": Key.DOWN,
        "\r": Key.ENTER,
        "\n": Key.ENTER,
        " ": Key.SPACE,
        "\x1b": Key.ESCAPE,
        "\x03": Key.CTRL_C,
    }
    key = mapping.get(value)
    if key is not None:
        return KeyPress(key=key)
    return KeyPress(char=value)


def _posix_setup() -> object:
    import termios
    import tty

    fd = sys.stdin.fileno()
    attributes = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    return fd, attributes


def _posix_restore(token: object) -> None:
    import termios

    fd, attributes = token  # type: ignore[misc]
    termios.tcsetattr(fd, termios.TCSADRAIN, attributes)


def _posix_read() -> str:
    fd = sys.stdin.fileno()
    first = os.read(fd, 1).decode(errors="ignore")
    if first != "\x1b":
        return first

    sequence = first
    for _ in range(2):
        readable, _, _ = select.select([fd], [], [], 0.02)
        if not readable:
            break
        sequence += os.read(fd, 1).decode(errors="ignore")
    return sequence


def _windows_setup() -> object:
    return None


def _windows_restore(token: object) -> None:
    return None


def _windows_read() -> str:
    import msvcrt

    first = msvcrt.getwch()
    if first in {"\x00", "\xe0"}:
        second = msvcrt.getwch()
        if second == "H":
            return "\x1b[A"
        if second == "P":
            return "\x1b[B"
        return second
    return first


class TerminalInput:
    """Context-managed one-key reader that always restores terminal mode."""

    def __init__(
        self,
        *,
        setup: Callable[[], object] | None = None,
        restore: Callable[[object], None] | None = None,
        reader: Callable[[], str] | None = None,
    ) -> None:
        if setup is None or restore is None or reader is None:
            if os.name == "nt":
                setup = setup or _windows_setup
                restore = restore or _windows_restore
                reader = reader or _windows_read
            else:
                setup = setup or _posix_setup
                restore = restore or _posix_restore
                reader = reader or _posix_read
        self._setup = setup
        self._restore = restore
        self._reader = reader
        self._token: object | None = None
        self._entered = False

    def __enter__(self) -> TerminalInput:
        self._token = self._setup()
        self._entered = True
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._entered:
            self._restore(self._token)
            self._entered = False
            self._token = None

    def read_key(self) -> KeyPress:
        return normalize_posix_sequence(self._reader())
