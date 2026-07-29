from agent_worklog.extraction.pipeline import extract_evidence
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
