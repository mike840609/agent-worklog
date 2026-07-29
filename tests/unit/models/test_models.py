from datetime import UTC, datetime

from agent_worklog.models.evidence import EvidenceConfidence, EvidenceItem
from agent_worklog.models.report import WorklogReport
from agent_worklog.models.session import TokenUsage, UsageSemantics
from agent_worklog.models.time_range import DateRange


def test_evidence_requires_provenance() -> None:
    item = EvidenceItem(
        text="Tests passed",
        source_activity_ids=["activity-1"],
        confidence=EvidenceConfidence.HIGH,
        extraction_method="successful_test_command",
    )

    assert item.source_activity_ids == ["activity-1"]


def test_unknown_token_usage_is_not_zero() -> None:
    usage = TokenUsage(semantics=UsageSemantics.UNKNOWN)

    assert usage.input_tokens is None
    assert usage.output_tokens is None


def test_report_schema_version_defaults_to_one() -> None:
    now = datetime(2026, 7, 29, tzinfo=UTC)
    report = WorklogReport(
        generated_at=now,
        period=DateRange(since=now.replace(day=28), until=now),
        repositories=[],
    )

    assert report.schema_version == "1"
