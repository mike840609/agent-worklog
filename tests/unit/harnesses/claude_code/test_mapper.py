import json
from pathlib import Path

import pytest

from agent_worklog.harnesses.claude_code.mapper import ClaudeCodeJsonlMapper
from agent_worklog.models.session import ActivityType, SessionDescriptor, UsageSemantics

FIXTURE = Path("tests/fixtures/claude_code/session-basic.jsonl")

SECRET_MARKERS = (
    "HOOK_STDOUT_MARKER",
    "SYSTEM_REMINDER_MARKER",
    "THINKING_MARKER",
    "STDOUT_SECRET_MARKER",
    "STDERR_SECRET_MARKER",
)


@pytest.fixture
def descriptor() -> SessionDescriptor:
    return SessionDescriptor(
        harness="claude-code",
        session_id="sess-1",
        source_location=str(FIXTURE),
        project_id_hint="-repo-main",
    )


@pytest.fixture
def records() -> list[dict]:
    return [
        json.loads(line)
        for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_maps_only_human_prompts_to_user_messages(records, descriptor) -> None:
    session = ClaudeCodeJsonlMapper().map(records, descriptor)

    user_texts = [
        activity.content
        for activity in session.activities
        if activity.activity_type == ActivityType.USER_MESSAGE
    ]
    assert user_texts == ["Add retry to the price fetcher"]


def test_drops_every_secret_marker(records, descriptor) -> None:
    """stdout, stderr, thinking, hook output, and system reminders never reach the model."""

    session = ClaudeCodeJsonlMapper().map(records, descriptor)
    serialized = session.model_dump_json()

    for marker in SECRET_MARKERS:
        assert marker not in serialized, f"{marker} leaked into AgentSession"


def test_maps_tool_calls_with_result_flags(records, descriptor) -> None:
    session = ClaudeCodeJsonlMapper().map(records, descriptor)

    tool_calls = {
        activity.tool_call_id: activity
        for activity in session.activities
        if activity.activity_type == ActivityType.TOOL_CALL
    }

    bash = tool_calls["toolu-1"]
    assert bash.tool_name == "Bash"
    assert bash.content == "pytest -q"
    assert bash.metadata["stderr_empty"] is True
    assert bash.metadata["interrupted"] is False

    edit = tool_calls["toolu-2"]
    assert edit.tool_name == "Edit"
    assert edit.content == "/repo/worktree-feat/src/fetch.py"
    assert edit.metadata["stderr_empty"] is False


def test_uses_last_cwd_and_ai_title(records, descriptor) -> None:
    session = ClaudeCodeJsonlMapper().map(records, descriptor)

    assert session.working_directory == "/repo/worktree-feat"
    assert session.title == "Retry for the price fetcher"
    assert session.harness == "claude-code"


def test_accumulates_incremental_token_usage(records, descriptor) -> None:
    session = ClaudeCodeJsonlMapper().map(records, descriptor)

    assert session.token_usage is not None
    assert session.token_usage.semantics is UsageSemantics.INCREMENTAL
    assert session.token_usage.input_tokens == 15
    assert session.token_usage.output_tokens == 300
    assert session.token_usage.cache_read_tokens == 3000
    assert session.token_usage.cache_write_tokens == 50


def test_attaches_per_model_usage_to_one_activity_per_record(records, descriptor) -> None:
    session = ClaudeCodeJsonlMapper().map(records, descriptor)

    per_model = [
        (activity.metadata["model"], activity.metadata["usage"])
        for activity in session.activities
        if "usage" in activity.metadata
    ]
    assert per_model == [
        (
            "claude-opus-5",
            {
                "input_tokens": 10,
                "output_tokens": 200,
                "cache_read_tokens": 1000,
                "cache_write_tokens": 50,
            },
        ),
        (
            "claude-sonnet-5",
            {
                "input_tokens": 5,
                "output_tokens": 100,
                "cache_read_tokens": 2000,
                "cache_write_tokens": 0,
            },
        ),
    ]


def test_every_activity_has_a_timestamp(records, descriptor) -> None:
    """ScanService warns about timestamp-less activities; Claude Code always has them."""

    session = ClaudeCodeJsonlMapper().map(records, descriptor)

    assert session.activities
    assert all(activity.timestamp is not None for activity in session.activities)
