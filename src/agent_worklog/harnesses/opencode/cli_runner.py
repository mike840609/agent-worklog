"""Safe subprocess execution for OpenCode and Git commands."""

import os
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    """Execute a pre-tokenized command without shell expansion."""

    def __init__(self, *, timeout_seconds: float) -> None:
        self._timeout_seconds = timeout_seconds

    def run(self, args: list[str]) -> CommandResult:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=self._timeout_seconds,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        return CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
