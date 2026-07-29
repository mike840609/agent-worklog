from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

import agent_worklog.cli as cli
from agent_worklog.errors import ReportOutputError
from agent_worklog.models.report import RepositorySummary, WorklogReport
from agent_worklog.models.time_range import DateRange

runner = CliRunner()
TZ = ZoneInfo("Asia/Taipei")


class StubReportService:
    def __init__(self, output_path: Path, period: DateRange) -> None:
        self.output_path = output_path
        self.period = period

    def generate(self, *, force: bool = False, dry_run: bool = False):
        if self.output_path.exists() and not force:
            raise ReportOutputError(f"report already exists: {self.output_path}")
        report = WorklogReport(
            generated_at=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
            period=self.period,
            repositories=[
                RepositorySummary(
                    repository_id="git:github.com/mike/agent-worklog",
                    display_name="Agent Worklog",
                )
            ],
        )
        return SimpleNamespace(
            output_path=self.output_path,
            content="# Engineering Worklog\n",
            report=report,
        )


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "_now_in_timezone",
        lambda timezone: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )


def test_report_refuses_overwrite_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_report = tmp_path / "report.md"
    existing_report.write_text("existing")
    monkeypatch.setattr(
        cli,
        "_build_report_service",
        lambda settings, period, output_path, no_llm: StubReportService(output_path, period),
    )

    result = runner.invoke(
        cli.app,
        ["report", "--days", "7", "--output", str(existing_report)],
    )

    assert result.exit_code == 7
    assert "already exists" in result.stdout


def test_report_supports_previous_calendar_week(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, DateRange] = {}

    def build(settings, period, output_path, no_llm):
        captured["period"] = period
        return StubReportService(output_path, period)

    monkeypatch.setattr(cli, "_build_report_service", build)

    result = runner.invoke(
        cli.app,
        [
            "report",
            "--period",
            "last-week",
            "--dry-run",
            "--output",
            str(tmp_path / "report.md"),
        ],
    )

    assert result.exit_code == 0
    assert captured["period"].since == datetime(2026, 7, 20, 0, 0, tzinfo=TZ)
    assert captured["period"].until == datetime(2026, 7, 27, 0, 0, tzinfo=TZ)
    assert "# Engineering Worklog" in result.stdout


def test_report_rejects_days_and_period_together() -> None:
    result = runner.invoke(cli.app, ["report", "--days", "7", "--period", "last-week"])

    assert result.exit_code == 2


def test_until_requires_since() -> None:
    result = runner.invoke(cli.app, ["scan", "--until", "2026-07-27T00:00:00+08:00"])

    assert result.exit_code == 2


def test_no_llm_never_constructs_http_summarizer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret-key")
    monkeypatch.setattr(cli, "_build_scan_service", lambda settings, period: object())

    def fail_constructor(**kwargs):
        raise AssertionError("LLM summarizer must not be constructed")

    monkeypatch.setattr(cli, "OpenAICompatibleSummarizer", fail_constructor, raising=False)

    service = cli._build_report_service(
        cli.AppSettings(),
        DateRange.previous_week(now=datetime(2026, 7, 29, 20, 0, tzinfo=TZ)),
        tmp_path / "report.md",
        True,
    )

    assert service is not None
