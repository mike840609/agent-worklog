from datetime import datetime, timedelta
from itertools import count
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
        lambda settings, period, output_path, no_llm, root_only=False, *, now: (
            StubReportService(output_path, period)
        ),
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

    def build(settings, period, output_path, no_llm, root_only=False, *, now):
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
    monkeypatch.setattr(
        cli,
        "_build_scan_service",
        lambda settings, period, root_only=False: object(),
    )

    def fail_constructor(**kwargs):
        raise AssertionError("LLM summarizer must not be constructed")

    monkeypatch.setattr(cli, "OpenAICompatibleSummarizer", fail_constructor, raising=False)

    service = cli._build_report_service(
        cli.AppSettings(),
        DateRange.previous_week(now=datetime(2026, 7, 29, 20, 0, tzinfo=TZ)),
        tmp_path / "report.md",
        True,
        now=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )

    assert service is not None


def test_days_window_uses_a_single_clock_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second clock read widens `--days 7` into an eight-day usage window."""

    reads = count()
    monkeypatch.setattr(
        cli,
        "_now_in_timezone",
        lambda timezone: (
            datetime(2026, 7, 29, 20, 0, tzinfo=TZ) + timedelta(microseconds=next(reads))
        ),
    )
    captured: dict[str, object] = {}

    class CapturingReportService:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def generate(self, *, force: bool = False, dry_run: bool = False):
            return SimpleNamespace(
                output_path=captured["output_path"],
                content="# Engineering Worklog\n",
                report=WorklogReport(
                    generated_at=captured["now_factory"](),
                    period=captured["period"],
                    repositories=[
                        RepositorySummary(
                            repository_id="git:github.com/mike/agent-worklog",
                            display_name="Agent Worklog",
                        )
                    ],
                ),
            )

    monkeypatch.setattr(cli, "ReportService", CapturingReportService)

    result = runner.invoke(
        cli.app,
        [
            "report",
            "--days",
            "7",
            "--dry-run",
            "--output",
            str(tmp_path / "report.md"),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert captured["usage_days"] == 7
    period = captured["period"]
    assert period.until - period.since == timedelta(days=7)
    assert captured["now_factory"]() == period.until


def test_report_passes_root_only_to_the_report_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, bool] = {}

    def build(settings, period, output_path, no_llm, root_only=False, *, now):
        captured["root_only"] = root_only
        return StubReportService(output_path, period)

    monkeypatch.setattr(cli, "_build_report_service", build)

    result = runner.invoke(
        cli.app,
        [
            "report",
            "--days",
            "7",
            "--root-only",
            "--dry-run",
            "--output",
            str(tmp_path / "report.md"),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert captured["root_only"] is True


def test_scan_passes_root_only_to_the_scan_service(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, bool] = {}

    class StubScanService:
        def scan(self):
            return SimpleNamespace(
                loaded_session_count=1,
                sessions_by_repository={},
                warnings=[],
            )

    def build(settings, period, root_only=False):
        captured["root_only"] = root_only
        return StubScanService()

    monkeypatch.setattr(cli, "_build_scan_service", build)

    result = runner.invoke(cli.app, ["scan", "--days", "7", "--root-only"])

    assert result.exit_code == 0
    assert captured["root_only"] is True
