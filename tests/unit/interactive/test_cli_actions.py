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


def test_choose_harness_cycles_enabled_values_without_prompting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "_load_settings", lambda: object())
    monkeypatch.setattr(
        cli,
        "_enabled_harnesses",
        lambda settings: [cli.Harness.OPENCODE, cli.Harness.CLAUDE_CODE, cli.Harness.CODEX],
    )
    monkeypatch.setattr(
        cli,
        "_prompt",
        lambda prompt: pytest.fail(f"typed prompt should not run: {prompt}"),
    )

    assert cli_actions._choose_harness("opencode") == "claude-code"
    assert cli_actions._choose_harness("claude-code") == "codex"
    assert cli_actions._choose_harness("codex") == "opencode"


def test_choose_harness_keeps_only_enabled_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_load_settings", lambda: object())
    monkeypatch.setattr(
        cli,
        "_enabled_harnesses",
        lambda settings: [cli.Harness.CODEX],
    )

    assert cli_actions._choose_harness("codex") == "codex"


def test_choose_period_cycles_built_in_windows_without_prompting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(report=SimpleNamespace(timezone="Asia/Taipei"))
    now = datetime(2026, 8, 7, 12, tzinfo=TZ)
    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(cli, "_now_in_timezone", lambda timezone: now)
    monkeypatch.setattr(
        cli,
        "_prompt",
        lambda prompt: pytest.fail(f"typed prompt should not run: {prompt}"),
    )

    last_week = DateRange.previous_week(now=now)
    last_7_days = DateRange.from_days(days=7, now=now)
    last_14_days = DateRange.from_days(days=14, now=now)
    last_30_days = DateRange.from_days(days=30, now=now)

    assert cli_actions._choose_period(last_week) == last_7_days
    assert cli_actions._choose_period(last_7_days) == last_14_days
    assert cli_actions._choose_period(last_14_days) == last_30_days
    assert cli_actions._choose_period(last_30_days) == last_week


def test_choose_period_custom_range_returns_to_first_builtin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(report=SimpleNamespace(timezone="Asia/Taipei"))
    now = datetime(2026, 8, 7, 12, tzinfo=TZ)
    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(cli, "_now_in_timezone", lambda timezone: now)

    assert cli_actions._choose_period(_period()) == DateRange.previous_week(now=now)
