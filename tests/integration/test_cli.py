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
from agent_worklog import config_store
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
        sanitize=False,
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
        sanitize=False,
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


def test_no_llm_builds_a_deterministic_report_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def build_scan(
        settings,
        period,
        root_only=False,
        *,
        harness=cli.Harness.OPENCODE,
        sanitize=False,
        progress=None,
    ):
        return object()

    monkeypatch.setattr(cli, "_build_scan_service", build_scan)

    no_llm_service = cli._build_report_service(
        cli.AppSettings(),
        DateRange.previous_week(now=datetime(2026, 7, 29, 20, 0, tzinfo=TZ)),
        tmp_path / "report.md",
        True,
        now=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )

    assert no_llm_service._narrative is False

    narrative_service = cli._build_report_service(
        cli.AppSettings(),
        DateRange.previous_week(now=datetime(2026, 7, 29, 20, 0, tzinfo=TZ)),
        tmp_path / "report.md",
        False,
        now=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )

    assert narrative_service._narrative is True
    assert narrative_service._opencode_runner is not None


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
        sanitize=False,
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
        sanitize=False,
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
        sanitize=False,
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
        sanitize=False,
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
    path.write_text(
        "AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__MODEL='stored-model'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))
    monkeypatch.delenv(
        "AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__MODEL", raising=False
    )
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

    model_row = next(
        line for line in result.stdout.splitlines() if "harnesses.opencode.cli.model" in line
    )
    assert "stored-model" in model_row
    assert "file" in model_row

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
    monkeypatch.delenv("AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__MODEL", raising=False)

    result = CliRunner().invoke(cli.app, ["config", "set", "harnesses.opencode.cli.model", "gpt-5"])

    assert result.exit_code == 0
    assert cli._load_settings().harnesses.opencode.cli.model == "gpt-5"


def test_config_set_rejects_an_unknown_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(tmp_path / "config.env"))

    result = CliRunner().invoke(cli.app, ["config", "set", "harnesses.opencode.cli.mdoel", "gpt-5"])

    assert result.exit_code == 3
    assert "did you mean harnesses.opencode.cli.model" in result.stdout


def test_config_set_rejects_a_value_the_settings_model_would_reject(
    monkeypatch, tmp_path
) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))

    result = CliRunner().invoke(
        cli.app, ["config", "set", "harnesses.opencode.cli.run_timeout_seconds", "abc"]
    )

    assert result.exit_code == 3
    assert "invalid value for harnesses.opencode.cli.run_timeout_seconds" in result.stdout
    assert not path.exists()


def test_config_set_with_an_empty_value_restores_the_default(monkeypatch, tmp_path) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))
    monkeypatch.delenv("AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__MODEL", raising=False)
    CliRunner().invoke(cli.app, ["config", "set", "harnesses.opencode.cli.model", "gpt-5"])

    result = CliRunner().invoke(cli.app, ["config", "set", "harnesses.opencode.cli.model", ""])

    assert result.exit_code == 0
    assert "using default" in result.stdout
    assert cli._load_settings().harnesses.opencode.cli.model == ""


def test_config_unset_restores_the_default(monkeypatch, tmp_path) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))
    monkeypatch.delenv("AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__MODEL", raising=False)
    CliRunner().invoke(cli.app, ["config", "set", "harnesses.opencode.cli.model", "gpt-5"])

    result = CliRunner().invoke(cli.app, ["config", "unset", "harnesses.opencode.cli.model"])

    assert result.exit_code == 0
    assert cli._load_settings().harnesses.opencode.cli.model == ""


def test_config_unset_of_an_unset_key_says_the_default_is_already_in_use(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(tmp_path / "config.env"))
    monkeypatch.setenv("COLUMNS", "200")

    result = CliRunner().invoke(cli.app, ["config", "unset", "harnesses.opencode.cli.model"])

    assert result.exit_code == 0
    assert "already using default" in result.stdout


def test_config_set_warns_when_the_environment_overrides_the_write(
    monkeypatch, tmp_path
) -> None:
    """Without this note the write is a silent no-op for the whole shell."""

    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(tmp_path / "config.env"))
    monkeypatch.setenv("AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__MODEL", "from-environment")
    monkeypatch.setenv("COLUMNS", "200")

    result = CliRunner().invoke(cli.app, ["config", "set", "harnesses.opencode.cli.model", "gpt-5"])

    assert result.exit_code == 0
    assert "AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__MODEL" in result.stdout
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
        result = CliRunner().invoke(
            cli.app, ["config", "set", "harnesses.opencode.cli.model", "gpt-5"]
        )
    finally:
        directory.chmod(0o700)  # restore so pytest can clean up tmp_path

    assert result.exit_code == 3
    assert result.exception is None or isinstance(result.exception, SystemExit)


@skip_unless_permissions_enforced
def test_config_list_exits_3_instead_of_a_traceback_on_an_unreadable_file(
    monkeypatch, tmp_path
) -> None:
    path = tmp_path / "config.env"
    path.write_text(
        "AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__MODEL='gpt-5'\n", encoding="utf-8"
    )
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))
    path.chmod(0o000)
    try:
        result = CliRunner().invoke(cli.app, ["config", "list"])
    finally:
        path.chmod(0o600)  # restore so pytest can clean up tmp_path

    assert result.exit_code == 3
    assert result.exception is None or isinstance(result.exception, SystemExit)


def _as_a_terminal(monkeypatch) -> None:
    """Pretend stdin is a terminal.

    CliRunner feeds stdin through a pipe, so the real `isatty()` is False and
    every prompting test would hit the non-terminal guard instead of the
    behavior it means to exercise.
    """

    monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: True)


def test_config_set_prompts_when_the_value_is_omitted(monkeypatch, tmp_path) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))
    monkeypatch.delenv("AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__EXECUTABLE", raising=False)
    _as_a_terminal(monkeypatch)

    result = CliRunner().invoke(
        cli.app,
        ["config", "set", "harnesses.opencode.cli.executable"],
        input="opencode-dev\n",
    )

    assert result.exit_code == 0
    assert "opencode" in result.stdout  # the prompt shows the value in force
    assert cli._load_settings().harnesses.opencode.cli.executable == "opencode-dev"


def test_config_set_prompt_leaves_the_setting_alone_on_an_empty_answer(
    monkeypatch, tmp_path
) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))
    monkeypatch.delenv("AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__EXECUTABLE", raising=False)
    _as_a_terminal(monkeypatch)

    result = CliRunner().invoke(
        cli.app, ["config", "set", "harnesses.opencode.cli.executable"], input="\n"
    )

    assert result.exit_code == 0
    assert "unchanged" in result.stdout
    assert not path.exists()


def test_config_set_prompt_rejects_a_bad_value_and_asks_again(monkeypatch, tmp_path) -> None:
    """A typo must not abort the prompt — the point of prompting is to fix it."""

    path = tmp_path / "config.env"
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))
    _as_a_terminal(monkeypatch)

    result = CliRunner().invoke(
        cli.app,
        ["config", "set", "harnesses.opencode.cli.timeout_seconds"],
        input="abc\n45\n",
    )

    assert result.exit_code == 0
    assert "invalid value for harnesses.opencode.cli.timeout_seconds" in result.stdout
    assert cli._load_settings().harnesses.opencode.cli.timeout_seconds == 45.0


def test_config_set_rejects_an_unknown_key_before_prompting(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(tmp_path / "config.env"))
    _as_a_terminal(monkeypatch)

    result = CliRunner().invoke(
        cli.app, ["config", "set", "harnesses.opencode.cli.mdoel"], input="deepseek-r1\n"
    )

    assert result.exit_code == 3
    assert "did you mean harnesses.opencode.cli.model" in result.stdout


def test_config_set_without_a_value_needs_a_terminal(monkeypatch, tmp_path) -> None:
    """In a pipe or in CI there is nobody to answer, so fail instead of reading stdin."""

    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(tmp_path / "config.env"))
    monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: False)

    result = CliRunner().invoke(
        cli.app, ["config", "set", "harnesses.opencode.cli.model"], input="deepseek-r1\n"
    )

    assert result.exit_code == 3
    assert "needs a terminal" in result.stdout


def test_config_set_with_a_value_still_works_without_a_terminal(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(tmp_path / "config.env"))
    monkeypatch.delenv("AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__MODEL", raising=False)
    monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: False)

    result = CliRunner().invoke(
        cli.app, ["config", "set", "harnesses.opencode.cli.model", "deepseek-r1"]
    )

    assert result.exit_code == 0
    assert cli._load_settings().harnesses.opencode.cli.model == "deepseek-r1"


def test_config_init_walks_every_setting_and_writes_only_the_answers(
    monkeypatch, tmp_path
) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))
    monkeypatch.delenv("AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__MODEL", raising=False)
    monkeypatch.delenv("AGENT_WORKLOG_REPORT__TIMEZONE", raising=False)
    _as_a_terminal(monkeypatch)
    settings = config_store.setting_keys()
    answers = {
        "report.timezone": "Europe/Berlin",
        "harnesses.opencode.cli.model": "deepseek-r1",
    }
    keystrokes = "".join(f"{answers.get(setting.key, '')}\n" for setting in settings)

    result = CliRunner().invoke(cli.app, ["config", "init"], input=keystrokes)

    assert result.exit_code == 0, result.stdout
    # Every setting was offered, not just the two that were answered.
    for setting in settings:
        assert setting.key in result.stdout
    assert config_store.stored_values(path) == {
        "AGENT_WORKLOG_REPORT__TIMEZONE": "Europe/Berlin",
        "AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__MODEL": "deepseek-r1",
    }
    assert "Wrote 2 settings" in result.stdout


def test_config_init_writes_nothing_when_every_answer_is_empty(monkeypatch, tmp_path) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))
    _as_a_terminal(monkeypatch)
    keystrokes = "\n" * len(config_store.setting_keys())

    result = CliRunner().invoke(cli.app, ["config", "init"], input=keystrokes)

    assert result.exit_code == 0
    assert not path.exists()
    assert "Wrote 0 settings" in result.stdout


def test_config_init_needs_a_terminal(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(tmp_path / "config.env"))
    monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: False)

    result = CliRunner().invoke(cli.app, ["config", "init"], input="\n" * 20)

    assert result.exit_code == 3
    assert "needs a terminal" in result.stdout
    # The way out of a non-interactive shell differs per command, so the
    # message must point at `config set`, not at "pass the value".
    assert "config set" in result.stdout


def _answer_for_run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    output_path: Path,
    period: DateRange,
    final_accept: bool,
) -> None:
    """Wire the run wizard's questions to fixed answers.

    sanitize/children/remote-LLM are all answered with their defaults kept by
    returning False for anything that is not the final preview review.
    """

    def ask_yes(prompt, *, default):
        return final_accept and "Generate the report" in prompt

    def ask_harness(settings):
        return cli.Harness.OPENCODE

    def ask_detail():
        return cli.DetailLevel.FULL

    def ask_output_path(settings, asked_period):
        return output_path, False

    monkeypatch.setattr(cli, "_ask_yes", ask_yes)
    monkeypatch.setattr(cli, "_ask_harness", ask_harness)
    monkeypatch.setattr(cli, "_ask_period", lambda settings_tz, now: period)
    monkeypatch.setattr(cli, "_ask_detail", ask_detail)
    monkeypatch.setattr(cli, "_ask_output_path", ask_output_path)
    _as_a_terminal(monkeypatch)


def test_run_refuses_a_non_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: False)

    result = runner.invoke(cli.app, ["run"])

    assert result.exit_code == 3
    # The message must name the non-interactive route, not ask for a terminal.
    assert "needs a terminal" in result.stdout
    assert "scan" in result.stdout
    assert "report" in result.stdout


def test_run_scans_once_then_generates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ), until=datetime(2026, 7, 27, tzinfo=TZ)
    )
    output_path = tmp_path / "worklog.md"
    scan = SimpleNamespace(
        loaded_session_count=2,
        sessions_by_repository={
            "git:github.com/mike/agent-worklog": [
                SimpleNamespace(repository=SimpleNamespace(display_name="Agent Worklog"))
            ]
        },
        warnings=[],
    )
    seen: dict[str, object] = {}

    class StubScanService:
        def scan(self):
            return scan

    class StubReportService:
        def __init__(self, output_path, period) -> None:
            self.output_path = output_path
            self.period = period

        def generate(self, *, force: bool = False, dry_run: bool = False, scan=None):
            seen["scan"] = scan
            self.output_path.write_text("# Engineering Worklog\n")
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

    def build_scan(settings, period, root_only=False, *, harness, sanitize, progress):
        seen["root_only"] = root_only
        return StubScanService()

    def build_report(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        harness,
        sanitize,
        detail,
        progress,
    ):
        seen["root_only"] = root_only
        return StubReportService(output_path, period)

    _answer_for_run(
        monkeypatch,
        output_path=output_path,
        period=period,
        final_accept=True,
    )
    monkeypatch.setattr(cli, "_build_scan_service", build_scan)
    monkeypatch.setattr(cli, "_build_report_service", build_report)

    result = runner.invoke(cli.app, ["run"])

    assert result.exit_code == 0, result.stdout
    assert output_path.exists()
    assert "Report written to" in result.stdout
    # The preview scan is reused for generation, not re-run.
    assert seen["scan"] is scan
    # The wizard answered "no" to including child sessions, so both the scan
    # and the report were told to keep to root sessions.
    assert seen["root_only"] is True


def test_run_aborts_when_the_preview_is_declined(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "worklog.md"
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ), until=datetime(2026, 7, 27, tzinfo=TZ)
    )

    class StubScanService:
        def scan(self):
            return SimpleNamespace(
                loaded_session_count=1,
                sessions_by_repository={
                    "git:github.com/mike/agent-worklog": [
                        SimpleNamespace(repository=SimpleNamespace(display_name="Agent Worklog"))
                    ]
                },
                warnings=[],
            )

    _answer_for_run(
        monkeypatch,
        output_path=output_path,
        period=period,
        final_accept=False,
    )
    monkeypatch.setattr(
        cli,
        "_build_scan_service",
        lambda settings, period, root_only=False, *, harness, sanitize, progress: StubScanService(),
    )

    result = runner.invoke(cli.app, ["run"])

    assert result.exit_code == 0
    assert "Aborted" in result.stdout
    assert not output_path.exists()


def test_run_accepts_a_non_opencode_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-OpenCode harness must not trip the sanitize-only-for-OpenCode guard."""

    output_path = tmp_path / "worklog.md"
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ), until=datetime(2026, 7, 27, tzinfo=TZ)
    )
    seen: dict[str, object] = {}

    class StubScanService:
        def scan(self):
            return SimpleNamespace(
                loaded_session_count=1,
                sessions_by_repository={
                    "git:github.com/mike/agent-worklog": [
                        SimpleNamespace(repository=SimpleNamespace(display_name="Agent Worklog"))
                    ]
                },
                warnings=[],
            )

    class StubReportService:
        def __init__(self, output_path, period) -> None:
            self.output_path = output_path
            self.period = period

        def generate(self, *, force: bool = False, dry_run: bool = False, scan=None):
            self.output_path.write_text("# Engineering Worklog\n")
            return SimpleNamespace(
                output_path=self.output_path,
                content="# Engineering Worklog\n",
                report=WorklogReport(
                    generated_at=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
                    period=self.period,
                    repositories=[
                        RepositorySummary(
                            repository_id="git:github.com/mike/agent-worklog",
                            display_name="Agent Worklog",
                        )
                    ],
                ),
            )

    def build_scan(settings, period, root_only=False, *, harness, sanitize, progress):
        seen["harness"] = harness
        seen["sanitize"] = sanitize
        return StubScanService()

    def build_report(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        harness,
        sanitize,
        detail,
        progress,
    ):
        return StubReportService(output_path, period)

    _answer_for_run(
        monkeypatch,
        output_path=output_path,
        period=period,
        final_accept=True,
    )
    monkeypatch.setattr(cli, "_ask_harness", lambda settings: cli.Harness.CLAUDE_CODE)
    monkeypatch.setattr(cli, "_build_scan_service", build_scan)
    monkeypatch.setattr(cli, "_build_report_service", build_report)

    result = runner.invoke(cli.app, ["run"])

    assert result.exit_code == 0, result.stdout
    assert output_path.exists()
    assert seen["harness"] is cli.Harness.CLAUDE_CODE
    assert seen["sanitize"] is False


def test_run_walks_the_real_prompts_on_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive the wizard through its actual prompts, answering nothing.

    Pressing Enter at every question must accept the defaults, which is the
    interactive equivalent of `report --days 7 --no-llm`.
    """

    output_path = tmp_path / "worklog.md"
    captured: dict[str, object] = {}

    class StubScanService:
        def scan(self):
            return SimpleNamespace(
                loaded_session_count=1,
                sessions_by_repository={
                    "git:github.com/mike/agent-worklog": [
                        SimpleNamespace(repository=SimpleNamespace(display_name="Agent Worklog"))
                    ]
                },
                warnings=[],
            )

    class StubReportService:
        def __init__(self, output_path, period) -> None:
            self.output_path = output_path
            self.period = period

        def generate(self, *, force: bool = False, dry_run: bool = False, scan=None):
            self.output_path.write_text("# Engineering Worklog\n")
            return SimpleNamespace(
                output_path=self.output_path,
                content="# Engineering Worklog\n",
                report=WorklogReport(
                    generated_at=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
                    period=self.period,
                    repositories=[
                        RepositorySummary(
                            repository_id="git:github.com/mike/agent-worklog",
                            display_name="Agent Worklog",
                        )
                    ],
                ),
            )

    def build_scan(settings, period, root_only=False, *, harness, sanitize, progress):
        captured["harness"] = harness
        captured["sanitize"] = sanitize
        captured["root_only"] = root_only
        return StubScanService()

    def build_report(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        harness,
        sanitize,
        detail,
        progress,
    ):
        captured["no_llm"] = no_llm
        captured["detail"] = detail
        return StubReportService(output_path, period)

    _as_a_terminal(monkeypatch)
    monkeypatch.setattr(cli, "_default_output_path", lambda settings, period: output_path)
    monkeypatch.setattr(cli, "_build_scan_service", build_scan)
    monkeypatch.setattr(cli, "_build_report_service", build_report)

    result = runner.invoke(cli.app, ["run"], input="\n" * 8)

    assert result.exit_code == 0, result.stdout
    assert output_path.exists()
    assert "Report written to" in result.stdout
    assert captured["harness"] is cli.Harness.OPENCODE
    assert captured["sanitize"] is False
    # Enter at the narrative question keeps `report`'s default: the narrative
    # review, which is `no_llm=False`.
    assert captured["no_llm"] is False
    assert captured["root_only"] is False
    assert captured["detail"] is cli.DetailLevel.FULL
