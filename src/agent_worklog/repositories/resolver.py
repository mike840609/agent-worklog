"""Resolve canonical repository identities for normalized sessions."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Protocol

from agent_worklog.harnesses.opencode.cli_runner import CommandResult
from agent_worklog.models.repository import RepositoryIdentity, RepositoryIdentityType
from agent_worklog.models.session import AgentSession
from agent_worklog.repositories.remote import normalize_git_remote, repository_display_name


class Runner(Protocol):
    def run(self, args: list[str]) -> CommandResult: ...


def _hash_identity(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:12]


def _normalize_local_path(value: str, *, base: str | None = None) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute() and base is not None:
        path = Path(base).expanduser() / path
    return str(path.resolve(strict=False))


def _basename(value: str, fallback: str) -> str:
    name = Path(value).name
    return repository_display_name(name) if name else fallback


class RepositoryResolver:
    """Apply remote/common-dir/harness/path/unknown identity priority."""

    def __init__(self, *, runner: Runner) -> None:
        self._runner = runner

    def _git(self, cwd: str, *args: str) -> CommandResult:
        try:
            return self._runner.run(["git", "-C", cwd, *args])
        except (FileNotFoundError, TimeoutError, OSError) as exc:
            return CommandResult(returncode=1, stdout="", stderr=type(exc).__name__)

    def resolve(self, session: AgentSession) -> RepositoryIdentity:
        cwd = session.working_directory
        branch: str | None = None
        common_dir: str | None = None

        if cwd:
            remote_result = self._git(cwd, "remote", "get-url", "origin")
            common_result = self._git(cwd, "rev-parse", "--git-common-dir")
            branch_result = self._git(cwd, "branch", "--show-current")
            if branch_result.returncode == 0:
                branch = branch_result.stdout.strip() or None
            if common_result.returncode == 0 and common_result.stdout.strip():
                common_dir = _normalize_local_path(common_result.stdout.strip(), base=cwd)

            if remote_result.returncode == 0 and remote_result.stdout.strip():
                try:
                    normalized_remote = normalize_git_remote(remote_result.stdout.strip())
                except ValueError:
                    normalized_remote = None
                if normalized_remote is not None:
                    return RepositoryIdentity(
                        repository_id=f"git:{normalized_remote}",
                        display_name=repository_display_name(normalized_remote),
                        identity_type=RepositoryIdentityType.GIT_REMOTE,
                        normalized_remote=normalized_remote,
                        branch=branch,
                        working_directory=cwd,
                        resolution_method="git_origin_remote",
                    )

            if common_dir is not None:
                return RepositoryIdentity(
                    repository_id=f"git-common:{_hash_identity(common_dir)}",
                    display_name=_basename(cwd, "Local Repository"),
                    identity_type=RepositoryIdentityType.GIT_COMMON_DIR,
                    branch=branch,
                    working_directory=cwd,
                    resolution_method="git_common_dir",
                )

        if session.project_id_hint:
            return RepositoryIdentity(
                repository_id=f"harness:{session.harness}:{session.project_id_hint}",
                display_name=session.project_id_hint,
                identity_type=RepositoryIdentityType.HARNESS_PROJECT,
                branch=branch,
                working_directory=cwd,
                resolution_method="harness_project_id",
            )

        if cwd:
            normalized_path = _normalize_local_path(cwd)
            return RepositoryIdentity(
                repository_id=f"path:{_hash_identity(normalized_path)}",
                display_name=_basename(normalized_path, "Local Project"),
                identity_type=RepositoryIdentityType.PATH_FALLBACK,
                branch=branch,
                working_directory=cwd,
                resolution_method="normalized_path",
            )

        return RepositoryIdentity(
            repository_id=f"unknown:{session.harness}:{session.session_id}",
            display_name="Unknown",
            identity_type=RepositoryIdentityType.UNKNOWN,
            resolution_method="per_session_unknown",
        )
