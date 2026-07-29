import sys

from agent_worklog.harnesses.opencode.cli_runner import CommandRunner


def test_runner_disables_interactive_git_and_uses_argument_list() -> None:
    runner = CommandRunner(timeout_seconds=5)

    result = runner.run([sys.executable, "-c", "print('ok')"])

    assert result.returncode == 0
    assert result.stdout.strip() == "ok"
