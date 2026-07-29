from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agent_worklog.errors import HarnessSourceError
from agent_worklog.harnesses.opencode.cli_runner import CommandResult
from agent_worklog.harnesses.opencode.stats import collect_usage_stats, usage_days
from agent_worklog.models.time_range import DateRange

TZ = ZoneInfo("Asia/Taipei")


def test_usage_days_covers_period_start_until_now() -> None:
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )

    assert usage_days(period, datetime(2026, 7, 29, 20, 0, tzinfo=TZ)) == 10


def test_usage_days_is_at_least_one() -> None:
    period = DateRange(
        since=datetime(2026, 7, 29, 18, 0, tzinfo=TZ),
        until=datetime(2026, 7, 29, 19, 0, tzinfo=TZ),
    )

    assert usage_days(period, datetime(2026, 7, 29, 19, 0, tzinfo=TZ)) == 1


def test_collect_usage_stats_requests_models_and_tools(fake_runner) -> None:
    fake_runner.stdout = "gpt-5-mini  1234 tokens\n"

    text = collect_usage_stats(runner=fake_runner, executable="opencode", days=10)

    assert text == "gpt-5-mini  1234 tokens"
    assert fake_runner.calls[0] == [
        "opencode",
        "stats",
        "--days",
        "10",
        "--models",
        "20",
        "--tools",
        "20",
    ]


def test_collect_usage_stats_raises_on_failure(fake_runner) -> None:
    fake_runner.set_result(
        "--tools 20",
        CommandResult(returncode=1, stdout="", stderr="stats unsupported"),
    )

    with pytest.raises(HarnessSourceError, match="stats unsupported"):
        collect_usage_stats(runner=fake_runner, executable="opencode", days=7)


def test_collect_usage_stats_raises_on_empty_output(fake_runner) -> None:
    fake_runner.stdout = "   \n"

    with pytest.raises(HarnessSourceError, match="no output"):
        collect_usage_stats(runner=fake_runner, executable="opencode", days=7)
