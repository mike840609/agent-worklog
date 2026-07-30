import subprocess
import sys

import pytest

from agent_worklog import process
from agent_worklog.process import CommandRunner


def test_runner_disables_interactive_git_and_uses_argument_list() -> None:
    runner = CommandRunner(timeout_seconds=5)

    result = runner.run([sys.executable, "-c", "print('ok')"])

    assert result.returncode == 0
    assert result.stdout.strip() == "ok"


def test_timeout_becomes_a_failed_result(monkeypatch: pytest.MonkeyPatch) -> None:
    def timing_out_run(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd=["opencode", "stats"], timeout=5.0)

    monkeypatch.setattr(process.subprocess, "run", timing_out_run)

    result = CommandRunner(timeout_seconds=5).run(["opencode", "stats"])

    assert result.returncode != 0
    assert result.stdout == ""
    assert "opencode timed out after 5 seconds" in result.stderr


def test_missing_executable_becomes_a_failed_result() -> None:
    result = CommandRunner(timeout_seconds=5).run(["agent-worklog-missing-binary"])

    assert result.returncode != 0
    assert result.stdout == ""
    assert "agent-worklog-missing-binary" in result.stderr
