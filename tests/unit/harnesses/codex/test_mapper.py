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
