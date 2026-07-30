import sys
from datetime import datetime, timedelta
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from rich.console import Console
from typer.testing import CliRunner

import agent_worklog.cli as cli
from agent_worklog.errors import ReportOutputError
from agent_worklog.models.report import RepositorySummary, WorklogReport
from agent_worklog.models.time_range import DateRange
from agent_worklog.progress import NullProgressReporter, ProgressStage

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

    def build(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        harness=cli.Harness.OPENCODE,
        progress=None,
    ):
        return StubReportService(output_path, period)

    monkeypatch.setattr(cli, "_build_report_service", build)

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

    def build(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        harness=cli.Harness.OPENCODE,
        progress=None,
    ):
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
    def build_scan(
        settings,
        period,
        root_only=False,
        *,
        harness=cli.Harness.OPENCODE,
        progress=None,
    ):
        return object()

    monkeypatch.setattr(cli, "_build_scan_service", build_scan)

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
    captured: dict[str, object] = {}

    def build(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        harness=cli.Harness.OPENCODE,
        progress=None,
    ):
        captured["root_only"] = root_only
        captured["progress"] = progress
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
    assert captured["progress"] is not None


def test_scan_passes_root_only_to_the_scan_service(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class StubScanService:
        def scan(self):
            return SimpleNamespace(
                loaded_session_count=1,
                sessions_by_repository={},
                warnings=[],
            )

    def build(
        settings,
        period,
        root_only=False,
        *,
        harness=cli.Harness.OPENCODE,
        progress=None,
    ):
        captured["root_only"] = root_only
        captured["progress"] = progress
        return StubScanService()

    monkeypatch.setattr(cli, "_build_scan_service", build)

    result = runner.invoke(cli.app, ["scan", "--days", "7", "--root-only"])

    assert result.exit_code == 0
    assert captured["root_only"] is True
    assert captured["progress"] is not None


def test_quiet_scan_passes_a_null_progress_reporter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class StubScanService:
        def scan(self):
            return SimpleNamespace(
                loaded_session_count=1,
                sessions_by_repository={},
                warnings=[],
            )

    def build(
        settings,
        period,
        root_only=False,
        *,
        harness=cli.Harness.OPENCODE,
        progress=None,
    ):
        captured["progress"] = progress
        return StubScanService()

    monkeypatch.setattr(cli, "_build_scan_service", build)

    result = runner.invoke(cli.app, ["scan", "--days", "7", "--quiet"])

    assert result.exit_code == 0
    assert isinstance(captured["progress"], NullProgressReporter)
    assert result.stdout.strip() == "1"


def test_dry_run_keeps_progress_out_of_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    original_console_reporter = cli.ConsoleReporter

    def build_reporter(**kwargs):
        return original_console_reporter(
            **kwargs,
            progress_console=Console(
                file=sys.stderr,
                force_terminal=True,
                color_system=None,
            ),
        )

    class ProgressReportService(StubReportService):
        def __init__(self, output_path, period, progress) -> None:
            super().__init__(output_path, period)
            self.progress = progress

        def generate(self, *, force: bool = False, dry_run: bool = False):
            self.progress.start(ProgressStage.RENDERING_REPORT)
            return super().generate(force=force, dry_run=dry_run)

    def build(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        harness=cli.Harness.OPENCODE,
        progress=None,
    ):
        return ProgressReportService(output_path, period, progress)

    monkeypatch.setattr(cli, "ConsoleReporter", build_reporter)
    monkeypatch.setattr(cli, "_build_report_service", build)

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

    assert result.exit_code == 0
    assert "# Engineering Worklog" in result.stdout
    assert "Rendering report" not in result.stdout
    assert "Rendering report" in result.stderr


def test_disabled_codex_harness_is_refused(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_WORKLOG_HARNESSES__CODEX__ENABLED", "false")

    result = CliRunner().invoke(cli.app, ["doctor", "--harness", "codex"])

    assert result.exit_code == 3
    assert "AGENT_WORKLOG_HARNESSES__CODEX__ENABLED" in result.stdout
