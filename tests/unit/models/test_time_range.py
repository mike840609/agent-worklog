from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agent_worklog.models.time_range import DateRange

TZ = ZoneInfo("Asia/Taipei")


def test_from_days_returns_half_open_range() -> None:
    now = datetime(2026, 7, 29, 20, 0, tzinfo=TZ)

    period = DateRange.from_days(days=7, now=now)

    assert period.since == datetime(2026, 7, 22, 20, 0, tzinfo=TZ)
    assert period.until == now


def test_previous_week_is_monday_to_monday() -> None:
    now = datetime(2026, 7, 29, 20, 0, tzinfo=TZ)

    period = DateRange.previous_week(now=now)

    assert period.since == datetime(2026, 7, 20, 0, 0, tzinfo=TZ)
    assert period.until == datetime(2026, 7, 27, 0, 0, tzinfo=TZ)


def test_date_range_rejects_naive_values() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        DateRange(
            since=datetime(2026, 7, 20),
            until=datetime(2026, 7, 21),
        )
