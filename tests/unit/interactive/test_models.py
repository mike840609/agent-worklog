from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from agent_worklog.interactive.models import ReportDraft
from agent_worklog.models.time_range import DateRange
from agent_worklog.renderers.markdown import DetailLevel

TZ = ZoneInfo("Asia/Taipei")


def _period(day: int) -> DateRange:
    return DateRange(
        since=datetime(2026, 7, day, tzinfo=TZ),
        until=datetime(2026, 7, day + 1, tzinfo=TZ),
    )


def _draft_with_scan() -> ReportDraft:
    draft = ReportDraft(harness="opencode", period=_period(20))
    draft.scan = object()  # type: ignore[assignment]
    draft.selected_session_ids = {"ses-a", "ses-b"}
    return draft


def test_period_change_clears_scan_and_selection() -> None:
    draft = _draft_with_scan()

    draft.set_period(_period(21))

    assert draft.scan is None
    assert draft.selected_session_ids == set()


def test_harness_change_clears_scan_and_selection() -> None:
    draft = _draft_with_scan()

    draft.set_harness("codex")

    assert draft.scan is None
    assert draft.selected_session_ids == set()


def test_subagent_change_clears_scan_and_selection() -> None:
    draft = _draft_with_scan()

    draft.set_include_subagents(False)

    assert draft.scan is None
    assert draft.selected_session_ids == set()


def test_sanitize_change_clears_scan_and_selection() -> None:
    draft = _draft_with_scan()

    draft.set_sanitize(True)

    assert draft.scan is None
    assert draft.selected_session_ids == set()


def test_non_scan_identity_changes_keep_cached_scan_and_selection() -> None:
    draft = _draft_with_scan()
    scan = draft.scan

    draft.set_detail(DetailLevel.BRIEF)
    draft.set_narrative(False)
    draft.set_dry_run(True)

    assert draft.scan is scan
    assert draft.selected_session_ids == {"ses-a", "ses-b"}


def test_setting_same_scan_identity_value_does_not_clear_cache() -> None:
    draft = _draft_with_scan()
    scan = draft.scan

    draft.set_harness("opencode")
    draft.set_period(_period(20))
    draft.set_include_subagents(True)
    draft.set_sanitize(False)

    assert draft.scan is scan
    assert draft.selected_session_ids == {"ses-a", "ses-b"}
