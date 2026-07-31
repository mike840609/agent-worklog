from datetime import datetime
from typing import Any

from agent_worklog.harnesses.codex.mapper import CodexRolloutMapper
from agent_worklog.models.session import ActivityType, SessionDescriptor

DESCRIPTOR = SessionDescriptor(
    harness="codex",
    session_id="thread-1",
    source_location="/rollouts/thread-1.jsonl",
    title="Add retry",
    working_directory_hint="/worktrees/agent",
)


def _record(timestamp: str, record_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"timestamp": timestamp, "type": record_type, "payload": payload}


def _map(records: list[dict[str, Any]]):
    return CodexRolloutMapper().map(records, DESCRIPTOR)


def test_user_messages_become_user_activities() -> None:
    session = _map(
        [
            _record(
                "2026-07-21T01:00:00.000Z",
                "event_msg",
                {"type": "user_message", "message": "Add retry to the price fetcher"},
            )
        ]
    )

    assert [activity.activity_type for activity in session.activities] == [
        ActivityType.USER_MESSAGE
    ]
    assert session.activities[0].content == "Add retry to the price fetcher"
    assert session.activities[0].timestamp == datetime.fromisoformat(
        "2026-07-21T01:00:00+00:00"
    )


def test_agent_messages_become_assistant_activities() -> None:
    session = _map(
        [
            _record(
                "2026-07-21T01:00:01.000Z",
                "event_msg",
                {"type": "agent_message", "message": "I implemented the retry."},
            )
        ]
    )

    assert session.activities[0].activity_type == ActivityType.ASSISTANT_MESSAGE
    assert session.activities[0].content == "I implemented the retry."


def test_exec_command_becomes_a_command_activity() -> None:
    session = _map(
        [
            _record(
                "2026-07-21T01:00:02.000Z",
                "response_item",
                {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "call-1",
                    "arguments": '{"cmd": "pytest -q", "workdir": "/worktrees/agent"}',
                },
            )
        ]
    )

    activity = session.activities[0]
    assert activity.activity_type == ActivityType.COMMAND
    assert activity.content == "pytest -q"
    assert activity.tool_name == "exec_command"
    assert activity.tool_call_id == "call-1"
    assert activity.metadata["workdir"] == "/worktrees/agent"


def test_no_outcome_signal_is_ever_recorded() -> None:
    session = _map(
        [
            _record(
                "2026-07-21T01:00:02.000Z",
                "response_item",
                {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "call-1",
                    "arguments": '{"cmd": "pytest -q"}',
                },
            )
        ]
    )

    metadata = session.activities[0].metadata
    assert "exit_code" not in metadata
    assert "stderr_empty" not in metadata


def test_exec_javascript_never_reaches_activity_content() -> None:
    javascript = 'const r = await tools.exec_command({"cmd":"rm -rf /"}); text(r);'
    session = _map(
        [
            _record(
                "2026-07-21T01:00:03.000Z",
                "response_item",
                {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": "call-2",
                    "input": javascript,
                },
            )
        ]
    )

    activity = session.activities[0]
    assert activity.activity_type == ActivityType.TOOL_CALL
    assert activity.content == ""
    assert activity.tool_name == "exec"
    assert javascript not in str(session.model_dump())


def test_applied_patches_become_one_file_change_per_path() -> None:
    session = _map(
        [
            _record(
                "2026-07-21T01:00:04.000Z",
                "event_msg",
                {
                    "type": "patch_apply_end",
                    "call_id": "call-3",
                    "success": True,
                    "changes": {
                        "/worktrees/agent/src/fetch.py": {
                            "type": "update",
                            "content": "SECRET_FILE_BODY",
                        },
                        "/worktrees/agent/tests/test_fetch.py": {
                            "type": "add",
                            "content": "SECRET_FILE_BODY",
                        },
                    },
                },
            )
        ]
    )

    paths = [activity.content for activity in session.activities]
    assert sorted(paths) == [
        "/worktrees/agent/src/fetch.py",
        "/worktrees/agent/tests/test_fetch.py",
    ]
    assert all(
        activity.activity_type == ActivityType.FILE_CHANGE
        for activity in session.activities
    )
    assert len({activity.activity_id for activity in session.activities}) == 2
    assert "SECRET_FILE_BODY" not in str(session.model_dump())


def test_failed_patches_produce_no_file_change() -> None:
    session = _map(
        [
            _record(
                "2026-07-21T01:00:05.000Z",
                "event_msg",
                {
                    "type": "patch_apply_end",
                    "call_id": "call-4",
                    "success": False,
                    "changes": {"/worktrees/agent/src/fetch.py": {"type": "update"}},
                },
            )
        ]
    )

    assert session.activities == []


def test_working_directory_follows_the_last_turn_context() -> None:
    session = _map(
        [
            _record(
                "2026-07-21T01:00:00.000Z",
                "session_meta",
                {"session_id": "thread-1", "cwd": "/worktrees/agent"},
            ),
            _record(
                "2026-07-21T01:00:06.000Z",
                "turn_context",
                {"turn_id": "t-1", "cwd": "/worktrees/assets", "model": "gpt-5.6-sol"},
            ),
        ]
    )

    assert session.working_directory == "/worktrees/assets"


def test_session_identity_comes_from_the_descriptor() -> None:
    session = _map([])

    assert session.harness == "codex"
    assert session.session_id == "thread-1"
    assert session.title == "Add retry"
    assert session.working_directory == "/worktrees/agent"


def test_torn_records_do_not_stop_the_mapping() -> None:
    session = _map(
        [
            {"timestamp": "2026-07-21T01:00:00.000Z", "type": "event_msg"},
            _record(
                "2026-07-21T01:00:01.000Z",
                "event_msg",
                {"type": "agent_message", "message": "still mapped"},
            ),
        ]
    )

    assert [activity.content for activity in session.activities] == ["still mapped"]


def _token_count(timestamp: str, total: dict[str, int]) -> dict[str, Any]:
    return _record(
        timestamp,
        "event_msg",
        {"type": "token_count", "info": {"total_token_usage": total}},
    )


def _turn_context(timestamp: str, model: str) -> dict[str, Any]:
    return _record(timestamp, "turn_context", {"turn_id": "t", "model": model})


def test_usage_is_the_delta_of_the_running_total() -> None:
    session = _map(
        [
            _turn_context("2026-07-21T01:00:00.000Z", "gpt-5.6-sol"),
            _record(
                "2026-07-21T01:00:01.000Z",
                "event_msg",
                {"type": "agent_message", "message": "first"},
            ),
            _token_count(
                "2026-07-21T01:00:02.000Z",
                {
                    "input_tokens": 100,
                    "output_tokens": 10,
                    "cached_input_tokens": 40,
                    "cache_write_input_tokens": 5,
                },
            ),
            _record(
                "2026-07-21T01:00:03.000Z",
                "event_msg",
                {"type": "agent_message", "message": "second"},
            ),
            _token_count(
                "2026-07-21T01:00:04.000Z",
                {
                    "input_tokens": 250,
                    "output_tokens": 30,
                    "cached_input_tokens": 90,
                    "cache_write_input_tokens": 5,
                },
            ),
        ]
    )

    first, second = session.activities
    assert first.metadata["usage"] == {
        "input_tokens": 100,
        "output_tokens": 10,
        "cache_read_tokens": 40,
        "cache_write_tokens": 5,
    }
    # The second turn's delta, not its running total.
    assert second.metadata["usage"] == {
        "input_tokens": 150,
        "output_tokens": 20,
        "cache_read_tokens": 50,
    }
    assert session.token_usage.input_tokens == 250
    assert session.token_usage.output_tokens == 30
    assert session.token_usage.cache_read_tokens == 90
    assert session.token_usage.cache_write_tokens == 5


def test_a_reset_running_total_is_taken_at_face_value() -> None:
    session = _map(
        [
            _turn_context("2026-07-21T01:00:00.000Z", "gpt-5.6-sol"),
            _record(
                "2026-07-21T01:00:01.000Z",
                "event_msg",
                {"type": "agent_message", "message": "first"},
            ),
            _token_count(
                "2026-07-21T01:00:02.000Z", {"input_tokens": 500, "output_tokens": 50}
            ),
            _record(
                "2026-07-21T01:00:03.000Z",
                "event_msg",
                {"type": "agent_message", "message": "after compaction"},
            ),
            _token_count(
                "2026-07-21T01:00:04.000Z", {"input_tokens": 20, "output_tokens": 3}
            ),
        ]
    )

    assert session.activities[1].metadata["usage"] == {
        "input_tokens": 20,
        "output_tokens": 3,
    }


def test_usage_follows_the_model_the_turn_context_names() -> None:
    session = _map(
        [
            _turn_context("2026-07-21T01:00:00.000Z", "gpt-5.6-sol"),
            _record(
                "2026-07-21T01:00:01.000Z",
                "event_msg",
                {"type": "agent_message", "message": "first"},
            ),
            _token_count("2026-07-21T01:00:02.000Z", {"output_tokens": 10}),
            _turn_context("2026-07-21T01:00:03.000Z", "gpt-5.6-terra"),
            _record(
                "2026-07-21T01:00:04.000Z",
                "event_msg",
                {"type": "agent_message", "message": "second"},
            ),
            _token_count("2026-07-21T01:00:05.000Z", {"output_tokens": 25}),
        ]
    )

    assert session.activities[0].metadata["model"] == "gpt-5.6-sol"
    assert session.activities[1].metadata["model"] == "gpt-5.6-terra"


def test_usage_with_no_activity_yet_joins_the_next_one() -> None:
    session = _map(
        [
            _turn_context("2026-07-21T01:00:00.000Z", "gpt-5.6-sol"),
            _token_count("2026-07-21T01:00:01.000Z", {"output_tokens": 40}),
            _record(
                "2026-07-21T01:00:02.000Z",
                "event_msg",
                {"type": "agent_message", "message": "after the reasoning"},
            ),
            _token_count("2026-07-21T01:00:03.000Z", {"output_tokens": 60}),
        ]
    )

    assert session.activities[0].metadata["usage"] == {"output_tokens": 60}


def test_trailing_usage_joins_the_last_activity_of_that_model() -> None:
    session = _map(
        [
            _turn_context("2026-07-21T01:00:00.000Z", "gpt-5.6-sol"),
            _record(
                "2026-07-21T01:00:01.000Z",
                "event_msg",
                {"type": "agent_message", "message": "answer"},
            ),
            _token_count("2026-07-21T01:00:02.000Z", {"output_tokens": 10}),
            # A trailing reasoning-only turn emits no activity of its own.
            _token_count("2026-07-21T01:00:03.000Z", {"output_tokens": 18}),
        ]
    )

    assert session.activities[0].metadata["usage"] == {"output_tokens": 18}


def test_reasoning_output_tokens_are_not_counted_twice() -> None:
    session = _map(
        [
            _turn_context("2026-07-21T01:00:00.000Z", "gpt-5.6-sol"),
            _record(
                "2026-07-21T01:00:01.000Z",
                "event_msg",
                {"type": "agent_message", "message": "answer"},
            ),
            _token_count(
                "2026-07-21T01:00:02.000Z",
                {"output_tokens": 100, "reasoning_output_tokens": 40},
            ),
        ]
    )

    assert session.activities[0].metadata["usage"] == {"output_tokens": 100}
