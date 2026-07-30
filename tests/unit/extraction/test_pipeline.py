from datetime import UTC, datetime

from agent_worklog.extraction.pipeline import extract_evidence
from agent_worklog.models.evidence import EvidenceConfidence, EvidenceStatus
from agent_worklog.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from agent_worklog.models.session import ActivityType, AgentSession, SessionActivity


def resolved(*activities: SessionActivity) -> ResolvedSession:
    return ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id="s1",
            activities=list(activities),
        ),
        repository=RepositoryIdentity(
            repository_id="git:github.com/mike/agent-worklog",
            display_name="Agent Worklog",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            normalized_remote="github.com/mike/agent-worklog",
            resolution_method="git_origin_remote",
        ),
    )


def test_user_request_becomes_goal_with_provenance() -> None:
    evidence = extract_evidence(
        resolved(
            SessionActivity(
                activity_id="message-1:part-0",
                activity_type=ActivityType.USER_MESSAGE,
                content="Add weekly report generation",
            )
        )
    )

    goal = evidence.goals[0]
    assert goal.text == "Add weekly report generation"
    assert goal.source_activity_ids == ["message-1:part-0"]
    assert goal.extraction_method == "user_message"


def test_successful_test_command_becomes_completed_outcome() -> None:
    evidence = extract_evidence(
        resolved(
            SessionActivity(
                activity_id="tool-1",
                activity_type=ActivityType.TOOL_CALL,
                tool_name="bash",
                content="pytest -q",
                metadata={"exit_code": 0},
            )
        )
    )

    assert evidence.outcomes[0].status == "completed"
    assert evidence.outcomes[0].confidence == "high"
    assert evidence.outcomes[0].source_activity_ids == ["tool-1"]


def test_nonzero_command_becomes_error_not_completed_outcome() -> None:
    evidence = extract_evidence(
        resolved(
            SessionActivity(
                activity_id="tool-1",
                activity_type=ActivityType.TOOL_CALL,
                tool_name="bash",
                content="pytest -q",
                metadata={"exit_code": 1},
            )
        )
    )

    assert evidence.errors[0].text == "pytest -q"
    assert evidence.outcomes == []


def test_assistant_completion_claim_is_low_confidence_unknown() -> None:
    evidence = extract_evidence(
        resolved(
            SessionActivity(
                activity_id="message-2:part-0",
                activity_type=ActivityType.ASSISTANT_MESSAGE,
                content="Implemented the feature successfully.",
            )
        )
    )

    assert evidence.outcomes[0].status == "unknown"
    assert evidence.outcomes[0].confidence == "low"


def test_extraction_carries_session_title_and_directory() -> None:
    resolved = ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id="s1",
            title="Fix the exporter",
            working_directory="/repos/agent-worklog",
        ),
        repository=RepositoryIdentity(
            repository_id="git:github.com/mike/agent-worklog",
            display_name="Agent Worklog",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            resolution_method="git_origin_remote",
        ),
    )

    evidence = extract_evidence(resolved)

    assert evidence.title == "Fix the exporter"
    assert evidence.working_directory == "/repos/agent-worklog"


def test_clean_stderr_yields_a_medium_verification_outcome() -> None:
    resolved = ResolvedSession(
        session=AgentSession(
            harness="claude-code",
            session_id="sess-1",
            working_directory="/repo/main",
            activities=[
                SessionActivity(
                    activity_id="a-1",
                    activity_type=ActivityType.TOOL_CALL,
                    timestamp=datetime(2026, 7, 21, tzinfo=UTC),
                    content="pytest -q",
                    tool_name="Bash",
                    metadata={"stderr_empty": True, "interrupted": False},
                )
            ],
        ),
        repository=RepositoryIdentity(
            repository_id="git:github.com/mike/agent-worklog",
            display_name="Agent Worklog",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            resolution_method="git_origin_remote",
        ),
    )

    evidence = extract_evidence(resolved)

    assert len(evidence.outcomes) == 1
    outcome = evidence.outcomes[0]
    assert outcome.text == "Verification passed: pytest -q"
    assert outcome.confidence is EvidenceConfidence.MEDIUM
    assert outcome.extraction_method == "stderr_heuristic"
    assert outcome.status is EvidenceStatus.COMPLETED


def test_nonempty_stderr_yields_a_medium_error() -> None:
    resolved = ResolvedSession(
        session=AgentSession(
            harness="claude-code",
            session_id="sess-1",
            working_directory="/repo/main",
            activities=[
                SessionActivity(
                    activity_id="a-1",
                    activity_type=ActivityType.TOOL_CALL,
                    timestamp=datetime(2026, 7, 21, tzinfo=UTC),
                    content="ruff check .",
                    tool_name="Bash",
                    metadata={"stderr_empty": False, "interrupted": False},
                )
            ],
        ),
        repository=RepositoryIdentity(
            repository_id="git:github.com/mike/agent-worklog",
            display_name="Agent Worklog",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            resolution_method="git_origin_remote",
        ),
    )

    evidence = extract_evidence(resolved)

    assert len(evidence.errors) == 1
    error = evidence.errors[0]
    assert error.text == "ruff check ."
    assert error.confidence is EvidenceConfidence.MEDIUM
    assert error.extraction_method == "stderr_heuristic"
    assert error.status is EvidenceStatus.BLOCKED


def test_interrupted_command_yields_no_verification_outcome() -> None:
    resolved = ResolvedSession(
        session=AgentSession(
            harness="claude-code",
            session_id="sess-1",
            working_directory="/repo/main",
            activities=[
                SessionActivity(
                    activity_id="a-1",
                    activity_type=ActivityType.TOOL_CALL,
                    timestamp=datetime(2026, 7, 21, tzinfo=UTC),
                    content="pytest -q",
                    tool_name="Bash",
                    metadata={"stderr_empty": True, "interrupted": True},
                )
            ],
        ),
        repository=RepositoryIdentity(
            repository_id="git:github.com/mike/agent-worklog",
            display_name="Agent Worklog",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            resolution_method="git_origin_remote",
        ),
    )

    evidence = extract_evidence(resolved)

    assert evidence.outcomes == []
    assert evidence.commands  # the command itself is still evidence


def test_missing_stderr_metadata_leaves_opencode_behavior_untouched() -> None:
    """OpenCode tool calls have no stderr flags; nothing new should appear."""

    resolved = ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id="sess-1",
            working_directory="/repo/main",
            activities=[
                SessionActivity(
                    activity_id="a-1",
                    activity_type=ActivityType.TOOL_CALL,
                    timestamp=datetime(2026, 7, 21, tzinfo=UTC),
                    content="pytest -q",
                    tool_name="bash",
                )
            ],
        ),
        repository=RepositoryIdentity(
            repository_id="git:github.com/mike/agent-worklog",
            display_name="Agent Worklog",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            resolution_method="git_origin_remote",
        ),
    )

    evidence = extract_evidence(resolved)

    assert evidence.outcomes == []
    assert evidence.errors == []
