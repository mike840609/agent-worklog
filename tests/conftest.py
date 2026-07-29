import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from agent_worklog.harnesses.opencode.cli_runner import CommandResult


@dataclass
class FakeCommandRunner:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    calls: list[list[str]] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)
    results: dict[str, CommandResult] = field(default_factory=dict)

    def set_output(self, command_suffix: str, output: str) -> None:
        self.outputs[command_suffix] = output

    def set_result(self, command_suffix: str, result: CommandResult) -> None:
        self.results[command_suffix] = result

    def run(self, args: list[str]) -> CommandResult:
        self.calls.append(args)
        joined = " ".join(args)
        explicit = next(
            (value for suffix, value in self.results.items() if joined.endswith(suffix)),
            None,
        )
        if explicit is not None:
            return explicit
        stdout = next(
            (value for suffix, value in self.outputs.items() if joined.endswith(suffix)),
            self.stdout,
        )
        return CommandResult(self.returncode, stdout, self.stderr)


@pytest.fixture
def fake_runner() -> FakeCommandRunner:
    return FakeCommandRunner()


@pytest.fixture
def fake_git_runner() -> FakeCommandRunner:
    return FakeCommandRunner()

_ACCEPTANCE_FIXTURES = Path(__file__).parent / "fixtures" / "opencode"
_ACCEPTANCE_TZ = ZoneInfo("Asia/Taipei")


def _millis(value: datetime) -> int:
    return int(value.timestamp() * 1000)


@dataclass
class AcceptanceCommandRunner:
    export_calls: list[list[str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.rows = [
            {
                "id": "root-agent",
                "project_id": "project-agent",
                "parent_id": None,
                "directory": "/worktrees/agent-main",
                "title": "Agent root",
                "time_created": _millis(datetime(2026, 7, 10, tzinfo=_ACCEPTANCE_TZ)),
                "time_updated": _millis(datetime(2026, 7, 28, tzinfo=_ACCEPTANCE_TZ)),
            },
            {
                "id": "agent-feature",
                "project_id": "project-agent",
                "parent_id": "root-agent",
                "directory": "/worktrees/agent-feature",
                "title": "Agent feature",
                "time_created": _millis(datetime(2026, 7, 21, tzinfo=_ACCEPTANCE_TZ)),
                "time_updated": _millis(datetime(2026, 7, 21, 3, tzinfo=_ACCEPTANCE_TZ)),
            },
            {
                "id": "cross-repo-child",
                "project_id": "project-assets",
                "parent_id": "root-agent",
                "directory": "/worktrees/assets",
                "title": "Assets child",
                "time_created": _millis(datetime(2026, 7, 22, tzinfo=_ACCEPTANCE_TZ)),
                "time_updated": _millis(datetime(2026, 7, 22, 3, tzinfo=_ACCEPTANCE_TZ)),
            },
            {
                "id": "secret-session",
                "project_id": "project-assets",
                "parent_id": None,
                "directory": "/worktrees/assets-secret",
                "title": "Secret session",
                "time_created": _millis(datetime(2026, 7, 23, tzinfo=_ACCEPTANCE_TZ)),
                "time_updated": _millis(datetime(2026, 7, 23, 3, tzinfo=_ACCEPTANCE_TZ)),
            },
            {
                "id": "api-a",
                "project_id": "project-api-a",
                "parent_id": None,
                "directory": "/worktrees/team-a-api",
                "title": "API A",
                "time_created": _millis(datetime(2026, 7, 24, tzinfo=_ACCEPTANCE_TZ)),
                "time_updated": _millis(datetime(2026, 7, 24, 3, tzinfo=_ACCEPTANCE_TZ)),
            },
            {
                "id": "api-b",
                "project_id": "project-api-b",
                "parent_id": None,
                "directory": "/worktrees/team-b-api",
                "title": "API B",
                "time_created": _millis(datetime(2026, 7, 25, tzinfo=_ACCEPTANCE_TZ)),
                "time_updated": _millis(datetime(2026, 7, 25, 3, tzinfo=_ACCEPTANCE_TZ)),
            },
            {
                "id": "failed-export",
                "project_id": "project-failed",
                "parent_id": None,
                "directory": "/worktrees/failed",
                "title": "Failed export",
                "time_created": _millis(datetime(2026, 7, 25, tzinfo=_ACCEPTANCE_TZ)),
                "time_updated": _millis(datetime(2026, 7, 25, 3, tzinfo=_ACCEPTANCE_TZ)),
            },
        ]
        self.exports = {
            "root-agent": "export-cross-repo-child.json",
            "agent-feature": "export-agent-feature.json",
            "cross-repo-child": "export-assets-child.json",
            "secret-session": "export-secret.json",
            "api-a": "export-api-a.json",
            "api-b": "export-api-b.json",
        }
        self.remotes = {
            "/worktrees/agent-main": "git@github.com:mike/agent-worklog.git",
            "/worktrees/agent-feature": "https://github.com/mike/agent-worklog.git",
            "/worktrees/assets": "git@github.com:mike/assets-tracker.git",
            "/worktrees/assets-secret": "https://github.com/mike/assets-tracker.git",
            "/worktrees/team-a-api": "git@github.com:team-a/api.git",
            "/worktrees/team-b-api": "git@github.com:team-b/api.git",
        }

    def run(self, args: list[str]) -> CommandResult:
        if args[:2] == ["opencode", "db"]:
            return CommandResult(0, json.dumps(self.rows), "")
        if args[:2] == ["opencode", "export"]:
            self.export_calls.append(args)
            session_id = args[2]
            if session_id == "failed-export":
                return CommandResult(1, "", "fixture export failure")
            fixture = _ACCEPTANCE_FIXTURES / self.exports[session_id]
            return CommandResult(0, fixture.read_text(encoding="utf-8"), "")
        if len(args) >= 5 and args[:2] == ["git", "-C"]:
            cwd = args[2]
            command = args[3:]
            if command == ["remote", "get-url", "origin"]:
                remote = self.remotes.get(cwd)
                if remote:
                    return CommandResult(0, remote, "")
                return CommandResult(2, "", "no remote")
            if command == ["rev-parse", "--git-common-dir"]:
                return CommandResult(0, f"{cwd}/.git", "")
            if command == ["branch", "--show-current"]:
                return CommandResult(0, "main", "")
        return CommandResult(1, "", f"unexpected command: {args}")


@pytest.fixture
def mocked_opencode() -> AcceptanceCommandRunner:
    return AcceptanceCommandRunner()
