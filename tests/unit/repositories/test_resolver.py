from agent_worklog.models.repository import RepositoryIdentityType
from agent_worklog.models.session import AgentSession
from agent_worklog.process import CommandResult
from agent_worklog.repositories.resolver import RepositoryResolver


def test_same_remote_groups_different_worktrees(fake_git_runner) -> None:
    fake_git_runner.set_output("remote get-url origin", "git@github.com:mike/repo.git")
    fake_git_runner.set_output("rev-parse --git-common-dir", "/repo/.git")
    fake_git_runner.set_output("branch --show-current", "feature/test")
    resolver = RepositoryResolver(runner=fake_git_runner)

    first = resolver.resolve(
        AgentSession(harness="opencode", session_id="s1", working_directory="/worktree/a")
    )
    second = resolver.resolve(
        AgentSession(harness="opencode", session_id="s2", working_directory="/worktree/b")
    )

    assert first.repository_id == second.repository_id == "git:github.com/mike/repo"
    assert first.branch == "feature/test"


def test_same_basename_with_different_owners_remains_different(fake_git_runner) -> None:
    first_runner = fake_git_runner
    first_runner.set_output("remote get-url origin", "git@github.com:team-a/api.git")
    second_runner = type(fake_git_runner)()
    second_runner.set_output("remote get-url origin", "git@github.com:team-b/api.git")

    first = RepositoryResolver(runner=first_runner).resolve(
        AgentSession(harness="opencode", session_id="s1", working_directory="/a/api")
    )
    second = RepositoryResolver(runner=second_runner).resolve(
        AgentSession(harness="opencode", session_id="s2", working_directory="/b/api")
    )

    assert first.repository_id == "git:github.com/team-a/api"
    assert second.repository_id == "git:github.com/team-b/api"


def test_no_remote_falls_back_to_hashed_git_common_dir(fake_git_runner) -> None:
    fake_git_runner.set_result(
        "remote get-url origin",
        CommandResult(returncode=2, stdout="", stderr="no remote"),
    )
    fake_git_runner.set_output("rev-parse --git-common-dir", "/private/repo/.git")
    resolver = RepositoryResolver(runner=fake_git_runner)

    identity = resolver.resolve(
        AgentSession(harness="opencode", session_id="s1", working_directory="/worktree/a")
    )

    assert identity.identity_type == RepositoryIdentityType.GIT_COMMON_DIR
    assert identity.repository_id.startswith("git-common:")
    assert "/private/repo" not in identity.repository_id


def test_deleted_path_falls_back_to_harness_project_id(fake_git_runner) -> None:
    fake_git_runner.returncode = 1
    resolver = RepositoryResolver(runner=fake_git_runner)

    identity = resolver.resolve(
        AgentSession(
            harness="opencode",
            session_id="s1",
            working_directory="/deleted/worktree",
            project_id_hint="project-1",
        )
    )

    assert identity.repository_id == "harness:opencode:project-1"
    assert identity.identity_type == RepositoryIdentityType.HARNESS_PROJECT


def test_missing_all_hints_uses_per_session_unknown(fake_git_runner) -> None:
    identity = RepositoryResolver(runner=fake_git_runner).resolve(
        AgentSession(harness="opencode", session_id="s1")
    )

    assert identity.repository_id == "unknown:opencode:s1"
    assert identity.identity_type == RepositoryIdentityType.UNKNOWN
