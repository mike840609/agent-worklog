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

    result = CliRunner().invoke(cli.app, ["scan", "--days", "7", "--harness", "codex"])

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
