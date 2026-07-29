from pathlib import Path

from agent_worklog.config import AppSettings


def test_settings_use_opencode_cli_and_taipei_defaults() -> None:
    settings = AppSettings()

    assert settings.harnesses.opencode.source == "cli"
    assert settings.harnesses.opencode.cli.executable == "opencode"
    assert settings.report.timezone == "Asia/Taipei"
    assert settings.report.output_directory == Path("reports")
