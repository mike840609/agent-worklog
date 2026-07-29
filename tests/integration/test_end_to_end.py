from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from typer.testing import CliRunner

import agent_worklog.cli as cli

TZ = ZoneInfo("Asia/Taipei")


def test_end_to_end_weekly_worklog(
    tmp_path: Path,
    monkeypatch,
    mocked_opencode,
) -> None:
    monkeypatch.setattr(
        cli,
        "_now_in_timezone",
        lambda timezone: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )
    monkeypatch.setattr(
        cli,
        "CommandRunner",
        lambda timeout_seconds: mocked_opencode,
    )
    output = tmp_path / "worklog.md"

    result = CliRunner().invoke(
        cli.app,
        [
            "report",
            "--period",
            "last-week",
            "--no-llm",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.stdout
    content = output.read_text(encoding="utf-8")
    assert "github.com/mike/agent-worklog" in content
    assert "github.com/mike/assets-tracker" in content
    assert "github.com/team-a/api" in content
    assert "github.com/team-b/api" in content
    assert "super-secret-token" not in content
    assert content.count("### Agent Worklog") == 1
    assert "Session failed-export export failed" in content
    assert mocked_opencode.export_calls
    assert all(call[-1] == "--sanitize" for call in mocked_opencode.export_calls)
