"""Exact half-open activity filtering."""

from copy import deepcopy

from agent_worklog.models.session import AgentSession
from agent_worklog.models.time_range import DateRange


def filter_session_to_period(
    session: AgentSession,
    period: DateRange,
) -> AgentSession | None:
    """Return a copy containing only timestamped activities inside the period."""

    activities = [
        activity
        for activity in session.activities
        if activity.timestamp is not None
        and period.since <= activity.timestamp < period.until
    ]
    if not activities:
        return None
    filtered = deepcopy(session)
    filtered.activities = activities
    return filtered
