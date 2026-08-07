from __future__ import annotations

import pytest
from typer.testing import CliRunner

from agent_worklog import cli

runner = CliRunner()


def test_bare_real_tty_dispatches_key_driven_controller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[object] = []
    fake_input = object()

    monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: True)
    monkeypatch.setattr(cli, "_supports_key_navigation", lambda: True)
    monkeypatch.setattr(cli, "TerminalInput", lambda: fake_input)
    monkeypatch.setattr(
        cli,
        "run_interactive",
        lambda **kwargs: called.append(kwargs),
    )

    result = runner.invoke(cli.app, [])

    assert result.exit_code == 0, result.stdout
    assert len(called) == 1
    assert called[0]["input_source"] is fake_input
    assert called[0]["actions"] is not None
    assert called[0]["console"] is not None


def test_named_subcommand_never_dispatches_key_controller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "run_interactive",
        lambda **kwargs: pytest.fail("interactive controller must not run"),
        raising=False,
    )

    result = runner.invoke(cli.app, ["config", "path"])

    assert result.exit_code == 0, result.stdout


def test_help_never_dispatches_key_controller(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "run_interactive",
        lambda **kwargs: pytest.fail("interactive controller must not run"),
        raising=False,
    )

    result = runner.invoke(cli.app, ["--help"])

    assert result.exit_code == 0, result.stdout
    assert "Usage" in result.stdout


def test_non_tty_bare_invocation_keeps_exit_code_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: False)

    result = runner.invoke(cli.app, [])

    assert result.exit_code == 3
    assert "needs a terminal" in result.stdout
    assert "subcommand" in result.stdout
