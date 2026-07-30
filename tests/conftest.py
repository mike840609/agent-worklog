import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from agent_worklog.process import CommandResult


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
        if args[:2] == ["opencode", "stats"]:
            return CommandResult(
                0,
                "models: gpt-5-mini 1234 tokens\ntools: bash 12 calls\n",
                "",
            )
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


@dataclass
class GitOnlyCommandRunner:
    """Answer git queries for the Claude Code acceptance run; no harness CLI."""

    remotes: dict[str, str] = field(default_factory=dict)

    def run(self, args: list[str]) -> CommandResult:
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
        if args[:1] == ["git"]:
            return CommandResult(0, "git version 2.45.0", "")
        return CommandResult(1, "", f"unexpected command: {args}")


@pytest.fixture
def claude_code_projects(tmp_path: Path) -> Path:
    """A projects directory with one root session and one subagent session."""

    root = tmp_path / "claude-projects"
    session_dir = root / "-repo-agent-worklog"
    session_dir.mkdir(parents=True)

    def record(payload: dict) -> str:
        return json.dumps(payload)

    root_lines = [
        record(
            {
                "type": "user",
                "origin": {"kind": "human"},
                "message": {
                    "role": "user",
                    "content": "Add retry to the price fetcher",
                },
                "uuid": "u-1",
                "timestamp": "2026-07-21T01:00:00.000Z",
                "cwd": "/worktrees/agent-main",
                "gitBranch": "main",
            }
        ),
        record(
            {
                "type": "assistant",
                "message": {
                    "model": "claude-opus-5",
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "I implemented the retry."},
                        {
                            "type": "tool_use",
                            "id": "toolu-1",
                            "name": "Bash",
                            "input": {"command": "pytest -q"},
                        },
                    ],
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 200,
                        "cache_read_input_tokens": 1000,
                        "cache_creation_input_tokens": 50,
                    },
                },
                "uuid": "a-1",
                "timestamp": "2026-07-21T01:00:01.000Z",
                "cwd": "/worktrees/agent-main",
                "gitBranch": "main",
            }
        ),
        record(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "toolu-1", "content": "ok"}
                    ],
                },
                "toolUseResult": {
                    "stdout": "ACCEPTANCE_SECRET_MARKER 42 passed",
                    "stderr": "",
                    "interrupted": False,
                    "isImage": False,
                },
                "uuid": "u-2",
                "timestamp": "2026-07-21T01:00:02.000Z",
                "cwd": "/worktrees/agent-main",
                "gitBranch": "main",
            }
        ),
        record({"type": "ai-title", "aiTitle": "Retry for the price fetcher"}),
    ]
    (session_dir / "root-session.jsonl").write_text(
        "\n".join(root_lines) + "\n", encoding="utf-8"
    )

    subagent_dir = session_dir / "root-session" / "subagents"
    subagent_dir.mkdir(parents=True)
    (subagent_dir / "agent-abc.jsonl").write_text(
        record(
            {
                "type": "user",
                "origin": {"kind": "human"},
                "message": {"role": "user", "content": "Review the retry helper"},
                "uuid": "u-3",
                "timestamp": "2026-07-22T01:00:00.000Z",
                "cwd": "/worktrees/assets",
                "gitBranch": "main",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (subagent_dir / "agent-abc.meta.json").write_text(
        json.dumps({"agentType": "general-purpose", "description": "Review the helper"}),
        encoding="utf-8",
    )
    return root


@pytest.fixture
def git_only_runner() -> GitOnlyCommandRunner:
    return GitOnlyCommandRunner(
        remotes={
            "/worktrees/agent-main": "git@github.com:mike/agent-worklog.git",
            "/worktrees/assets": "git@github.com:mike/assets-tracker.git",
        }
    )
