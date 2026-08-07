from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from agent_worklog import cli
from agent_worklog.interactive import cli_actions
from agent_worklog.models.time_range import DateRange

TZ = ZoneInfo("Asia/Taipei")


def _period() -> DateRange:
    return DateRange(
        since=datetime(2026, 8, 3, tzinfo=TZ),
        until=datetime(2026, 8, 10, tzinfo=TZ),
    )


def test_choose_harness_enter_keeps_current_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "_load_settings", lambda: object())
    monkeypatch.setattr(cli, "_prompt", lambda prompt: "")
    monkeypatch.setattr(
        cli,
        "_ask_harness",
        lambda settings: pytest.fail("chooser should not run when Enter keeps current"),
    )

    result = cli_actions._choose_harness("claude-code")

    assert result == "claude-code"


def test_choose_harness_change_uses_existing_chooser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "_load_settings", lambda: object())
    monkeypatch.setattr(cli, "_prompt", lambda prompt: "c")
    monkeypatch.setattr(cli, "_ask_harness", lambda settings: cli.Harness.CODEX)

    assert cli_actions._choose_harness("claude-code") == "codex"


def test_choose_period_enter_keeps_current_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _period()
    settings = SimpleNamespace(report=SimpleNamespace(timezone="Asia/Taipei"))
    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(cli, "_prompt", lambda prompt: "")
    monkeypatch.setattr(
        cli,
        "_ask_period",
        lambda timezone, now: pytest.fail("chooser should not run when Enter keeps current"),
    )

    result = cli_actions._choose_period(current)

    assert result == current


def test_choose_period_change_uses_existing_chooser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _period()
    changed = DateRange(
        since=datetime(2026, 7, 27, tzinfo=TZ),
        until=datetime(2026, 8, 3, tzinfo=TZ),
    )
    settings = SimpleNamespace(report=SimpleNamespace(timezone="Asia/Taipei"))
    now = datetime(2026, 8, 7, tzinfo=TZ)
    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(cli, "_now_in_timezone", lambda timezone: now)
    monkeypatch.setattr(cli, "_prompt", lambda prompt: "c")
    monkeypatch.setattr(cli, "_ask_period", lambda timezone, value_now: changed)

    assert cli_actions._choose_period(current) == changed
