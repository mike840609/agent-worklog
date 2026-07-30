from typer.testing import CliRunner

from agent_worklog.cli import app

runner = CliRunner()


def test_help_lists_core_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "doctor" in result.stdout
    assert "scan" in result.stdout
    assert "report" in result.stdout


def test_scan_rejects_an_unknown_harness() -> None:
    from typer.testing import CliRunner

    import agent_worklog.cli as cli

    result = CliRunner().invoke(cli.app, ["scan", "--days", "7", "--harness", "unknown"])

    assert result.exit_code == 2


def test_build_scan_service_selects_the_claude_code_source(tmp_path) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import agent_worklog.cli as cli
    from agent_worklog.config import AppSettings
    from agent_worklog.harnesses.claude_code.source import ClaudeCodeFileSource
    from agent_worklog.models.time_range import DateRange

    tz = ZoneInfo("Asia/Taipei")
    settings = AppSettings()
    settings.harnesses.claude_code.projects_directory = tmp_path
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=tz),
        until=datetime(2026, 7, 27, tzinfo=tz),
    )

    service = cli._build_scan_service(
        settings,
        period,
        harness=cli.Harness.CLAUDE_CODE,
    )

    assert isinstance(service._source, ClaudeCodeFileSource)


def test_a_disabled_harness_is_refused_with_a_configuration_error(tmp_path) -> None:
    """An off switch a privacy tool advertises has to actually turn something off."""

    import agent_worklog.cli as cli

    result = CliRunner().invoke(
        cli.app,
        ["scan", "--days", "7", "--harness", "claude-code"],
        env={"AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__ENABLED": "false"},
    )

    assert result.exit_code == 3
    assert "AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__ENABLED" in result.stdout


def test_doctor_refuses_a_disabled_harness() -> None:
    import agent_worklog.cli as cli

    result = CliRunner().invoke(
        cli.app,
        ["doctor", "--harness", "opencode"],
        env={"AGENT_WORKLOG_HARNESSES__OPENCODE__ENABLED": "false"},
    )

    assert result.exit_code == 3
    assert "disabled by configuration" in result.stdout


def test_report_still_runs_when_the_harness_is_enabled(tmp_path) -> None:
    import agent_worklog.cli as cli

    result = CliRunner().invoke(
        cli.app,
        ["scan", "--days", "7", "--harness", "claude-code"],
        env={
            "AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__ENABLED": "true",
            "AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY": str(tmp_path),
        },
    )

    assert result.exit_code == 4  # no sessions in an empty directory, not a config error
