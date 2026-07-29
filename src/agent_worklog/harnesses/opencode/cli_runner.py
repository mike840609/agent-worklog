"""Safe subprocess execution for OpenCode and Git commands."""

import os
import subprocess
from dataclasses import dataclass

_TIMEOUT_RETURNCODE = 124
_LAUNCH_FAILURE_RETURNCODE = 127


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
        """Run a command, reporting timeouts and launch failures as failed results.

        Every call site already handles a non-zero return code, so process-level
        failures are translated here instead of raising through unrelated layers.
        """

        try:
            completed = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except subprocess.TimeoutExpired:
            executable = args[0] if args else "command"
            return CommandResult(
                returncode=_TIMEOUT_RETURNCODE,
                stdout="",
                stderr=f"{executable} timed out after {self._timeout_seconds} seconds",
            )
        except OSError as exc:
            return CommandResult(
                returncode=_LAUNCH_FAILURE_RETURNCODE,
                stdout="",
                stderr=str(exc) or type(exc).__name__,
            )
        return CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
