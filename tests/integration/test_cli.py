import os
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
        detail=cli.DetailLevel.FULL,
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
        detail=cli.DetailLevel.FULL,
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
        detail=cli.DetailLevel.FULL,
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
        detail=cli.DetailLevel.FULL,
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
def test_report_passes_the_detail_level_to_the_report_service(
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
        detail=cli.DetailLevel.FULL,
    ):
        captured["detail"] = detail
        return StubReportService(output_path, period)

    monkeypatch.setattr(cli, "_build_report_service", build)

    result = runner.invoke(
        cli.app,
        [
            "report",
            "--days",
            "7",
            "--detail",
            "brief",
            "--dry-run",
            "--output",
            str(tmp_path / "report.md"),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert captured["detail"] is cli.DetailLevel.BRIEF


def test_report_defaults_to_full_detail(
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
        detail=cli.DetailLevel.FULL,
    ):
        captured["detail"] = detail
        return StubReportService(output_path, period)

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

    assert result.exit_code == 0, result.stdout
    assert captured["detail"] is cli.DetailLevel.FULL


def test_report_rejects_an_unknown_detail_level(tmp_path: Path) -> None:
    output_path = tmp_path / "report.md"

    result = runner.invoke(
        cli.app,
        ["report", "--days", "7", "--detail", "medium", "--output", str(output_path)],
    )

    assert result.exit_code == 2
    assert not output_path.exists()


def test_config_path_prints_the_settings_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(tmp_path / "config.env"))

    result = CliRunner().invoke(cli.app, ["config", "path"])

    assert result.exit_code == 0
    assert result.stdout.strip() == str(tmp_path / "config.env")


def test_config_list_shows_the_value_in_force_and_its_source(monkeypatch, tmp_path) -> None:
    path = tmp_path / "config.env"
    path.write_text("AGENT_WORKLOG_LLM__MODEL='stored-model'\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))
    monkeypatch.delenv("AGENT_WORKLOG_LLM__MODEL", raising=False)
    # A second setting, set through the environment rather than the file, so the
    # source column is pinned independently: "environment" collides with nothing
    # else in the output, unlike "file" which also appears in the footer's
    # "Settings file: ..." line.
    monkeypatch.setenv("AGENT_WORKLOG_REPORT__TIMEZONE", "UTC")
    # Rich wraps to 80 columns when stdout is not a terminal, which would split
    # the longer settings across lines and break these substring assertions.
    monkeypatch.setenv("COLUMNS", "200")

    result = CliRunner().invoke(cli.app, ["config", "list"])

    assert result.exit_code == 0
    assert "Every setting is optional" in result.stdout

    llm_row = next(line for line in result.stdout.splitlines() if "llm.model" in line)
    assert "stored-model" in llm_row
    assert "file" in llm_row
    assert "gpt-5-mini" in llm_row

    timezone_row = next(
        line for line in result.stdout.splitlines() if "report.timezone" in line
    )
    assert "UTC" in timezone_row
    assert "environment" in timezone_row


def test_help_lists_the_config_command() -> None:
    result = CliRunner().invoke(cli.app, ["--help"])

    assert result.exit_code == 0
    assert "config" in result.stdout


def test_config_set_writes_the_value_and_the_next_load_reads_it(monkeypatch, tmp_path) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))
    monkeypatch.delenv("AGENT_WORKLOG_LLM__MODEL", raising=False)

    result = CliRunner().invoke(cli.app, ["config", "set", "llm.model", "gpt-5"])

    assert result.exit_code == 0
    assert cli._load_settings().llm.model == "gpt-5"


def test_config_set_rejects_an_unknown_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(tmp_path / "config.env"))

    result = CliRunner().invoke(cli.app, ["config", "set", "llm.mdoel", "gpt-5"])

    assert result.exit_code == 3
    assert "did you mean llm.model" in result.stdout


def test_config_set_rejects_a_value_the_settings_model_would_reject(
    monkeypatch, tmp_path
) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))

    result = CliRunner().invoke(
        cli.app, ["config", "set", "llm.timeout_seconds", "abc"]
    )

    assert result.exit_code == 3
    assert "invalid value for llm.timeout_seconds" in result.stdout
    assert not path.exists()


def test_config_set_with_an_empty_value_restores_the_default(monkeypatch, tmp_path) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))
    monkeypatch.delenv("AGENT_WORKLOG_LLM__MODEL", raising=False)
    CliRunner().invoke(cli.app, ["config", "set", "llm.model", "gpt-5"])

    result = CliRunner().invoke(cli.app, ["config", "set", "llm.model", ""])

    assert result.exit_code == 0
    assert "gpt-5-mini" in result.stdout
    assert cli._load_settings().llm.model == "gpt-5-mini"


def test_config_unset_restores_the_default(monkeypatch, tmp_path) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))
    monkeypatch.delenv("AGENT_WORKLOG_LLM__MODEL", raising=False)
    CliRunner().invoke(cli.app, ["config", "set", "llm.model", "gpt-5"])

    result = CliRunner().invoke(cli.app, ["config", "unset", "llm.model"])

    assert result.exit_code == 0
    assert cli._load_settings().llm.model == "gpt-5-mini"


def test_config_unset_of_an_unset_key_says_the_default_is_already_in_use(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(tmp_path / "config.env"))
    monkeypatch.setenv("COLUMNS", "200")

    result = CliRunner().invoke(cli.app, ["config", "unset", "llm.model"])

    assert result.exit_code == 0
    assert "already using default" in result.stdout


def test_config_set_warns_when_the_environment_overrides_the_write(
    monkeypatch, tmp_path
) -> None:
    """Without this note the write is a silent no-op for the whole shell."""

    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(tmp_path / "config.env"))
    monkeypatch.setenv("AGENT_WORKLOG_LLM__MODEL", "from-environment")
    monkeypatch.setenv("COLUMNS", "200")

    result = CliRunner().invoke(cli.app, ["config", "set", "llm.model", "gpt-5"])

    assert result.exit_code == 0
    assert "AGENT_WORKLOG_LLM__MODEL" in result.stdout
    assert "takes precedence" in result.stdout


# chmod-based permission denial does not bite on Windows, and root ignores file
# permission bits entirely, so both would make these tests spuriously fail to
# reproduce the OSError-turned-exit-3 behavior they exist to catch.
skip_unless_permissions_enforced = pytest.mark.skipif(
    sys.platform.startswith("win") or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="chmod-based permission denial does not apply on Windows or as root",
)


@skip_unless_permissions_enforced
def test_config_set_exits_3_instead_of_a_traceback_on_an_unwritable_directory(
    monkeypatch, tmp_path
) -> None:
    """Filesystem errors must honor the exit-3 contract, not dump a traceback."""

    directory = tmp_path / "unwritable"
    directory.mkdir()
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(directory / "config.env"))
    directory.chmod(0o500)
    try:
        result = CliRunner().invoke(cli.app, ["config", "set", "llm.model", "gpt-5"])
    finally:
        directory.chmod(0o700)  # restore so pytest can clean up tmp_path

    assert result.exit_code == 3
    assert result.exception is None or isinstance(result.exception, SystemExit)


@skip_unless_permissions_enforced
def test_config_list_exits_3_instead_of_a_traceback_on_an_unreadable_file(
    monkeypatch, tmp_path
) -> None:
    path = tmp_path / "config.env"
    path.write_text("AGENT_WORKLOG_LLM__MODEL='gpt-5'\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))
    path.chmod(0o000)
    try:
        result = CliRunner().invoke(cli.app, ["config", "list"])
    finally:
        path.chmod(0o600)  # restore so pytest can clean up tmp_path

    assert result.exit_code == 3
    assert result.exception is None or isinstance(result.exception, SystemExit)
