from pathlib import Path

import pytest

from agent_worklog.config import AppSettings


def test_settings_use_opencode_cli_and_taipei_defaults() -> None:
    settings = AppSettings()

    assert settings.harnesses.opencode.source == "cli"
    assert settings.harnesses.opencode.cli.executable == "opencode"
    assert settings.report.timezone == "Asia/Taipei"
    assert settings.report.output_directory == Path("reports")


def test_claude_code_projects_directory_defaults_under_home() -> None:
    from pathlib import Path

    from agent_worklog.config import AppSettings

    settings = AppSettings()

    assert settings.harnesses.claude_code.projects_directory == (
        Path.home() / ".claude" / "projects"
    )


def test_claude_code_projects_directory_is_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pathlib import Path

    from agent_worklog.config import AppSettings

    monkeypatch.setenv(
        "AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY",
        "/tmp/claude-projects",
    )

    settings = AppSettings()

    assert settings.harnesses.claude_code.projects_directory == Path("/tmp/claude-projects")
