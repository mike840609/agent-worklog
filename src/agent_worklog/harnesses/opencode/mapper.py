"""Map sanitized OpenCode exports into canonical session models."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any, Mapping

from agent_worklog.errors import SessionParseError
from agent_worklog.models.session import (
    ActivityType,
    AgentSession,
    SessionActivity,
    SessionDescriptor,
    TokenUsage,
    UsageSemantics,
)


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _parse_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        seconds = float(value)
        if abs(seconds) > 10_000_000_000:
            seconds /= 1000
        return datetime.fromtimestamp(seconds, tz=UTC)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            numeric = float(stripped)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
            except ValueError:
                return None
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        return _parse_timestamp(numeric)
    return None


def _first_timestamp(*values: object) -> datetime | None:
    for value in values:
        parsed = _parse_timestamp(value)
        if parsed is not None:
            return parsed
    return None


def _message_role(message: Mapping[str, Any]) -> str:
    info = _as_mapping(message.get("info"))
    role = info.get("role", message.get("role", "assistant"))
    return role if isinstance(role, str) else "assistant"


def _message_id(message: Mapping[str, Any], *, session_id: str, index: int) -> str:
    info = _as_mapping(message.get("info"))
    value = info.get("id", message.get("id"))
    if isinstance(value, str) and value:
        return value
    return f"{session_id}:message:{index}"


def _message_timestamp(
    message: Mapping[str, Any],
    *,
    descriptor: SessionDescriptor,
) -> datetime | None:
    info = _as_mapping(message.get("info"))
    info_time = _as_mapping(info.get("time"))
    message_time = _as_mapping(message.get("time"))
    return _first_timestamp(
        info_time.get("created"),
        info_time.get("completed"),
        info.get("time_created"),
        message_time.get("created"),
        message.get("time_created"),
        descriptor.updated_at,
        descriptor.created_at,
    )


def _tool_content(part: Mapping[str, Any]) -> str:
    state = _as_mapping(part.get("state"))
    input_value = state.get("input", part.get("input"))
    input_mapping = _as_mapping(input_value)
    command = input_mapping.get("command")
    if isinstance(command, str):
        return command
    if input_value is None:
        return ""
    if isinstance(input_value, str):
        return input_value
    try:
        return json.dumps(input_value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(input_value)


class OpenCodeExportMapper:
    """Convert a sanitized OpenCode export to an AgentSession."""

    def map(self, payload: object, descriptor: SessionDescriptor) -> AgentSession:
        if not isinstance(payload, Mapping):
            raise SessionParseError("OpenCode export must be a JSON object")

        export_info = _as_mapping(payload.get("info"))
        export_time = _as_mapping(export_info.get("time"))
        raw_messages = payload.get("messages", [])
        if not isinstance(raw_messages, list):
            raise SessionParseError("OpenCode export messages must be a list")

        activities: list[SessionActivity] = []
        for message_index, raw_message in enumerate(raw_messages):
            if not isinstance(raw_message, Mapping):
                continue
            message = raw_message
            role = _message_role(message)
            message_id = _message_id(
                message,
                session_id=descriptor.session_id,
                index=message_index,
            )
            timestamp = _message_timestamp(message, descriptor=descriptor)
            raw_parts = message.get("parts", [])
            if not isinstance(raw_parts, list):
                continue
            for part_index, raw_part in enumerate(raw_parts):
                if not isinstance(raw_part, Mapping):
                    continue
                part = raw_part
                part_type = part.get("type")
                activity_id = f"{message_id}:{part_index}"
                if part_type == "text":
                    text = part.get("text", "")
                    if not isinstance(text, str) or not text:
                        continue
                    activity_type = (
                        ActivityType.USER_MESSAGE
                        if role == "user"
                        else ActivityType.ASSISTANT_MESSAGE
                    )
                    activities.append(
                        SessionActivity(
                            activity_id=activity_id,
                            activity_type=activity_type,
                            timestamp=timestamp,
                            content=text,
                        )
                    )
                elif part_type == "tool":
                    tool_name = part.get("tool", part.get("name"))
                    call_id = part.get("callID", part.get("call_id"))
                    activities.append(
                        SessionActivity(
                            activity_id=activity_id,
                            activity_type=ActivityType.TOOL_CALL,
                            timestamp=timestamp,
                            content=_tool_content(part),
                            tool_name=tool_name if isinstance(tool_name, str) else None,
                            tool_call_id=call_id if isinstance(call_id, str) else None,
                            metadata={"state": part.get("state", {})},
                        )
                    )

        title = export_info.get("title", payload.get("title"))
        directory = export_info.get("directory", payload.get("directory"))
        parent_id = export_info.get("parentID", export_info.get("parent_id"))
        created_at = _first_timestamp(
            export_time.get("created"),
            export_info.get("time_created"),
            descriptor.created_at,
        )
        updated_at = _first_timestamp(
            export_time.get("updated"),
            export_time.get("completed"),
            export_info.get("time_updated"),
            descriptor.updated_at,
            created_at,
        )
        project_id = export_info.get("projectID", export_info.get("project_id"))

        return AgentSession(
            harness="opencode",
            session_id=descriptor.session_id,
            parent_session_id=(
                parent_id if isinstance(parent_id, str) else descriptor.parent_session_id
            ),
            title=title if isinstance(title, str) else None,
            created_at=created_at,
            updated_at=updated_at,
            working_directory=(
                directory
                if isinstance(directory, str)
                else descriptor.working_directory_hint
            ),
            project_id_hint=(
                project_id if isinstance(project_id, str) else descriptor.project_id_hint
            ),
            activities=activities,
            token_usage=TokenUsage(semantics=UsageSemantics.UNKNOWN),
        )
