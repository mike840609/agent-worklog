"""Map Codex rollout JSONL records into canonical session models."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent_worklog.models.session import AgentSession, SessionDescriptor


class CodexRolloutMapper:
    """Convert Codex rollout records to an AgentSession."""

    def map(
        self,
        records: list[Mapping[str, Any]],
        descriptor: SessionDescriptor,
    ) -> AgentSession:
        return AgentSession(
            harness="codex",
            session_id=descriptor.session_id,
            parent_session_id=descriptor.parent_session_id,
            title=descriptor.title,
            created_at=descriptor.created_at,
            updated_at=descriptor.updated_at,
            working_directory=descriptor.working_directory_hint,
        )
