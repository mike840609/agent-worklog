from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from agent_worklog.errors import HarnessSourceError
from agent_worklog.models.time_range import DateRange
from agent_worklog.renderers.markdown import MarkdownRenderer
from agent_worklog.services.report import ReportService
from agent_worklog.services.scan import ScanResult, ScanService
from agent_worklog.summarizers.rule_based import RuleBasedSummarizer
from tests.integration.test_scan_service import FakeSource, StaticResolver

TZ = ZoneInfo("Asia/Taipei")


def period() -> DateRange:
    return DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )


def service(source: FakeSource, output: Path) -> ReportService:
    return ReportService(
        scan_service=ScanService(source=source, period=period(), resolver=StaticResolver()),
        summarizer=RuleBasedSummarizer(),
        renderer=MarkdownRenderer(),
        period=period(),
        output_path=output,
        now_factory=lambda: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )


def test_all_exports_failing_is_an_error(tmp_path: Path) -> None:
    source = FakeSource()
    source.fail_all = True

    with pytest.raises(HarnessSourceError, match="all opencode session loads failed"):
        service(source, tmp_path / "report.md").generate(force=False)


def test_report_service_writes_markdown_for_loaded_sessions(tmp_path: Path) -> None:
    source = FakeSource()
    source.fail_session_ids = {"bad"}
    output = tmp_path / "report.md"

    result = service(source, output).generate(force=False)

    assert result.output_path == output
    assert output.exists()
    assert "# Engineering Worklog" in output.read_text()
    assert result.report.repositories[0].display_name == "Agent Worklog"


class WarningSummarizer:
    def __init__(self) -> None:
        self._fallback = RuleBasedSummarizer()

    def summarize(self, evidence):
        return self._fallback.summarize(evidence)

    def drain_warnings(self) -> list[str]:
        return ["LLM summary unavailable; used deterministic fallback"]


def test_llm_failure_warning_is_written_into_report(tmp_path: Path) -> None:
    source = FakeSource()
    output = tmp_path / "report.md"
    report_service = ReportService(
        scan_service=ScanService(source=source, period=period(), resolver=StaticResolver()),
        summarizer=WarningSummarizer(),
        renderer=MarkdownRenderer(),
        period=period(),
        output_path=output,
        now_factory=lambda: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )

    result = report_service.generate(force=False)

    assert output.exists()
    assert any("LLM" in warning for warning in result.warnings)
    assert "LLM summary unavailable" in output.read_text()


def test_usage_statistics_are_written_into_the_report(tmp_path: Path) -> None:
    source = FakeSource()
    output = tmp_path / "report.md"
    report_service = ReportService(
        scan_service=ScanService(source=source, period=period(), resolver=StaticResolver()),
        summarizer=RuleBasedSummarizer(),
        renderer=MarkdownRenderer(),
        period=period(),
        output_path=output,
        now_factory=lambda: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
        usage_provider=lambda _scan: "gpt-5-mini  1234 tokens",
        usage_days=10,
    )

    result = report_service.generate(force=False)

    assert result.report.usage_text == "gpt-5-mini  1234 tokens"
    assert result.report.usage_days == 10
    content = output.read_text()
    assert "## Usage" in content
    assert "gpt-5-mini  1234 tokens" in content


def test_usage_text_is_redacted_on_the_report_model(tmp_path: Path) -> None:
    source = FakeSource()
    output = tmp_path / "report.md"
    report_service = ReportService(
        scan_service=ScanService(source=source, period=period(), resolver=StaticResolver()),
        summarizer=RuleBasedSummarizer(),
        renderer=MarkdownRenderer(),
        period=period(),
        output_path=output,
        now_factory=lambda: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
        usage_provider=lambda _scan: "auth: Bearer super-secret-token\ngpt-5-mini  1234 tokens",
        usage_days=10,
    )

    result = report_service.generate(force=False)

    assert result.report.usage_text is not None
    assert "super-secret-token" not in result.report.usage_text
    assert "[REDACTED]" in result.report.usage_text
    assert "gpt-5-mini  1234 tokens" in result.report.usage_text


def test_usage_failure_becomes_a_warning(tmp_path: Path) -> None:
    def failing_provider(_scan: ScanResult) -> str:
        raise HarnessSourceError("stats unsupported")

    source = FakeSource()
    output = tmp_path / "report.md"
    report_service = ReportService(
        scan_service=ScanService(source=source, period=period(), resolver=StaticResolver()),
        summarizer=RuleBasedSummarizer(),
        renderer=MarkdownRenderer(),
        period=period(),
        output_path=output,
        now_factory=lambda: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
        usage_provider=failing_provider,
        usage_days=10,
    )

    result = report_service.generate(force=False)

    assert result.report.usage_text is None
    assert any("usage statistics unavailable" in warning for warning in result.warnings)
    assert "## Usage" not in output.read_text()
