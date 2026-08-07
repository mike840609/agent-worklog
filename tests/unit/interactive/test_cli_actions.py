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


def test_choose_harness_uses_current_harness_as_prompt_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[object] = []
    monkeypatch.setattr(cli, "_load_settings", lambda: object())

    def ask_harness(settings: object, *, default: cli.Harness | None = None) -> cli.Harness:
        seen.append(default)
        return default or cli.Harness.OPENCODE

    monkeypatch.setattr(cli, "_ask_harness", ask_harness)

    result = cli_actions._choose_harness("claude-code")

    assert result == "claude-code"
    assert seen == [cli.Harness.CLAUDE_CODE]


def test_choose_period_uses_current_period_as_prompt_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _period()
    settings = SimpleNamespace(report=SimpleNamespace(timezone="Asia/Taipei"))
    now = datetime(2026, 8, 7, tzinfo=TZ)
    seen: list[DateRange | None] = []
    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(cli, "_now_in_timezone", lambda timezone: now)

    def ask_period(
        timezone: str,
        value_now: datetime,
        *,
        default: DateRange | None = None,
    ) -> DateRange:
        assert timezone == "Asia/Taipei"
        assert value_now == now
        seen.append(default)
        return default or DateRange.previous_week(now=value_now)

    monkeypatch.setattr(cli, "_ask_period", ask_period)

    result = cli_actions._choose_period(current)

    assert result == current
    assert seen == [current]
