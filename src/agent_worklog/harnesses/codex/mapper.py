"""Map Codex rollout JSONL records into canonical session models."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from agent_worklog.harnesses.codex.rollout_catalog import parse_timestamp
from agent_worklog.harnesses.codex.thread_catalog import HARNESS_NAME
from agent_worklog.models.session import (
    ActivityType,
    AgentSession,
    SessionActivity,
    SessionDescriptor,
)

# The one Codex tool whose arguments name a command as a field. `exec` is a
# general JavaScript sandbox — its input calls MCP tools, drives a browser, or
# loops over `tools.exec_command` — so it is not a command source. A strict parse
# for a single wrapped `exec_command` call matched 0 of 4,963 measured `exec`
# calls, which is why none is attempted.
_COMMAND_TOOL = "exec_command"

_TOOL_CALL_TYPES = frozenset({"function_call", "custom_tool_call"})


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _tool_arguments(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a `function_call`'s parsed arguments.

    A `custom_tool_call` carries free-form `input` instead, which is never parsed
    — see `_COMMAND_TOOL`.
    """

    raw = payload.get("arguments")
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, Mapping) else {}


class CodexRolloutMapper:
    """Convert Codex rollout records to an AgentSession, dropping raw output.

    Two things never leave this mapper: the JavaScript an `exec` call carries,
    and the file bodies a `patch_apply_end` record carries in
    `changes[path].content`. Codex has no `--sanitize` upstream, and the
    300-character evidence cap downstream is a backstop, not a reason to carry
    them this far.
    """

    def map(
        self,
        records: list[Mapping[str, Any]],
        descriptor: SessionDescriptor,
    ) -> AgentSession:
        activities: list[SessionActivity] = []
        working_directory: str | None = None
        first_timestamp: datetime | None = None
        last_timestamp: datetime | None = None

        for index, record in enumerate(records):
            payload = _as_mapping(record.get("payload"))
            if not payload:
                continue
            record_type = record.get("type")
            timestamp = parse_timestamp(record.get("timestamp"))
            if timestamp is not None:
                if first_timestamp is None:
                    first_timestamp = timestamp
                last_timestamp = timestamp

            if record_type in {"session_meta", "turn_context"}:
                # A session can move between worktrees; the last one is where the
                # work ended, which is what the repository resolver should see.
                working_directory = _text(payload.get("cwd")) or working_directory
                continue

            if record_type == "event_msg":
                activities.extend(
                    self._event_activities(
                        payload=payload,
                        record_index=index,
                        timestamp=timestamp,
                    )
                )
                continue

            if record_type == "response_item" and payload.get("type") in _TOOL_CALL_TYPES:
                activity = self._tool_activity(
                    payload=payload,
                    record_index=index,
                    timestamp=timestamp,
                )
                if activity is not None:
                    activities.append(activity)

        return AgentSession(
            harness=HARNESS_NAME,
            session_id=descriptor.session_id,
            parent_session_id=descriptor.parent_session_id,
            title=descriptor.title,
            created_at=first_timestamp or descriptor.created_at,
            updated_at=last_timestamp or descriptor.updated_at,
            working_directory=working_directory or descriptor.working_directory_hint,
            project_id_hint=descriptor.project_id_hint,
            activities=activities,
        )

    def _event_activities(
        self,
        *,
        payload: Mapping[str, Any],
        record_index: int,
        timestamp: datetime | None,
    ) -> list[SessionActivity]:
        event_type = payload.get("type")

        if event_type in {"user_message", "agent_message"}:
            message = _text(payload.get("message"))
            if message is None:
                return []
            activity_type = (
                ActivityType.USER_MESSAGE
                if event_type == "user_message"
                else ActivityType.ASSISTANT_MESSAGE
            )
            return [
                SessionActivity(
                    activity_id=str(record_index),
                    activity_type=activity_type,
                    timestamp=timestamp,
                    content=message,
                )
            ]

        if event_type == "patch_apply_end":
            # `success` is the only structured outcome signal Codex records.
            # A failed patch changed nothing, so listing its paths under Key
            # Files would be wrong.
            if payload.get("success") is not True:
                return []
            changes = _as_mapping(payload.get("changes"))
            call_id = _text(payload.get("call_id")) or str(record_index)
            activities: list[SessionActivity] = []
            # Only the keys. Each value holds the whole file body.
            for offset, path in enumerate(changes):
                if not isinstance(path, str) or not path.strip():
                    continue
                activities.append(
                    SessionActivity(
                        activity_id=f"{call_id}:{offset}",
                        activity_type=ActivityType.FILE_CHANGE,
                        timestamp=timestamp,
                        content=path.strip(),
                    )
                )
            return activities

        return []

    def _tool_activity(
        self,
        *,
        payload: Mapping[str, Any],
        record_index: int,
        timestamp: datetime | None,
    ) -> SessionActivity | None:
        name = _text(payload.get("name"))
        call_id = _text(payload.get("call_id")) or str(record_index)

        if name == _COMMAND_TOOL:
            arguments = _tool_arguments(payload)
            command = _text(arguments.get("cmd"))
            if command is None:
                return None
            metadata: dict[str, object] = {}
            workdir = _text(arguments.get("workdir"))
            if workdir is not None:
                metadata["workdir"] = workdir
            # No `exit_code` and no `stderr_empty`: Codex records exit codes only
            # inside free-form output text, in at least three formats, and a regex
            # over that would fail silently the day Codex changes it. Their absence
            # routes every command through `pipeline.py:264`, which claims nothing.
            return SessionActivity(
                activity_id=call_id,
                activity_type=ActivityType.COMMAND,
                timestamp=timestamp,
                content=command,
                tool_name=name,
                tool_call_id=call_id,
                metadata=metadata,
            )

        # Every other tool, `exec` included, is recorded with empty content. The
        # activity still exists because Task 6's usage rides on activities, and a
        # turn made only of tool calls would otherwise vanish from the usage table.
        return SessionActivity(
            activity_id=call_id,
            activity_type=ActivityType.TOOL_CALL,
            timestamp=timestamp,
            content="",
            tool_name=name,
            tool_call_id=call_id,
        )
