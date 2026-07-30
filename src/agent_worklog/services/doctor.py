"""Environment diagnostics."""

import os
from dataclasses import dataclass
from typing import Protocol

from agent_worklog.config import AppSettings
from agent_worklog.process import CommandResult


class Runner(Protocol):
    def run(self, args: list[str]) -> CommandResult: ...


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class DoctorResult:
    checks: list[DoctorCheck]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)


def _check(runner: Runner, name: str, args: list[str]) -> DoctorCheck:
    try:
        result = runner.run(args)
    except (FileNotFoundError, TimeoutError, OSError) as exc:
        return DoctorCheck(name=name, ok=False, detail=type(exc).__name__)
    detail = result.stdout.strip() if result.returncode == 0 else result.stderr.strip()
    return DoctorCheck(name=name, ok=result.returncode == 0, detail=detail)


def run_doctor(
    settings: AppSettings,
    *,
    runner: Runner,
    harness: str = "opencode",
) -> DoctorResult:
    """Validate the selected harness and Git without exposing env values."""

    checks: list[DoctorCheck] = []
    if harness == "claude-code":
        directory = settings.harnesses.claude_code.projects_directory
        readable = directory.is_dir() and os.access(directory, os.R_OK)
        checks.append(
            DoctorCheck(
                name="claude code projects directory",
                ok=readable,
                detail=str(directory),
            )
        )
    else:
        executable = settings.harnesses.opencode.cli.executable
        checks.append(_check(runner, "opencode version", [executable, "--version"]))
        checks.append(_check(runner, "opencode database", [executable, "db", "path"]))
    checks.append(_check(runner, "git", ["git", "--version"]))
    return DoctorResult(checks=checks)
