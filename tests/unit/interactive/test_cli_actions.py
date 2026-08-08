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


def test_choose_period_reaches_every_named_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The arrow advertises five windows, so pressing it must reach all five.

    The old cycle located the current window by comparing its timestamps against a
    freshly derived list. A rolling window's `until` is the moment it was built, so
    the comparison failed on every other press and snapped back to the first entry:
    `Last 14 days` and `Last 30 days` could not be reached at all. The previous test
    missed it by freezing the clock, which is the one thing that made it work.
    """

    settings = SimpleNamespace(report=SimpleNamespace(timezone="Asia/Taipei"))
    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(
        cli,
        "_prompt",
        lambda prompt: pytest.fail(f"typed prompt should not run: {prompt}"),
    )

    # A clock that advances between presses, as a real one does.
    ticks = iter(datetime(2026, 8, 7, 12, second=tick, tzinfo=TZ) for tick in range(30))
    monkeypatch.setattr(cli, "_now_in_timezone", lambda timezone: next(ticks))

    label: str | None = None
    seen: list[str] = []
    for _ in range(6):
        label, _range = cli_actions._choose_period(label)
        seen.append(label)

    assert seen == [
        "This week",
        "Last week",
        "Last 7 days",
        "Last 14 days",
        "Last 30 days",
        "This week",
    ]


def test_choose_period_starts_the_cycle_for_an_unnamed_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `--since` range carries no name, so the arrow starts the cycle rather than guessing."""

    settings = SimpleNamespace(report=SimpleNamespace(timezone="Asia/Taipei"))
    now = datetime(2026, 8, 7, 12, tzinfo=TZ)
    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(cli, "_now_in_timezone", lambda timezone: now)

    label, period = cli_actions._choose_period(None)

    assert label == "This week"
    assert period == DateRange.current_week(now=now)
