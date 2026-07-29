"""OpenCode CLI-backed session discovery and loading."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Protocol, cast

from agent_worklog.errors import HarnessSourceError, SessionParseError
from agent_worklog.harnesses.opencode.mapper import OpenCodeExportMapper
from agent_worklog.harnesses.base import HarnessSessionSource
from agent_worklog.harnesses.opencode.cli_runner import CommandResult
from agent_worklog.models.session import AgentSession, SessionDescriptor
from agent_worklog.models.time_range import DateRange


class Runner(Protocol):
    def run(self, args: list[str]) -> CommandResult:
        """Run one command."""


def _from_millis(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        milliseconds = int(cast(int | str, value))
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)


def _rows_from_payload(payload: object) -> list[dict[str, object]]:
    rows: object = payload
    if isinstance(payload, dict):
        rows = payload.get("data", payload.get("rows", []))
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise HarnessSourceError("OpenCode database response must contain a list of rows")
    return cast(list[dict[str, object]], rows)


class OpenCodeCliSource(HarnessSessionSource):
    """Query all OpenCode projects through the OpenCode CLI."""

    def __init__(self, *, runner: Runner, executable: str = "opencode") -> None:
        self._runner = runner
        self._executable = executable

    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        since_ms = int(period.since.timestamp() * 1000)
        until_ms = int(period.until.timestamp() * 1000)
        query = (
            "SELECT id, project_id, parent_id, directory, title, time_created, time_updated "
            "FROM session "
            f"WHERE time_created < {until_ms} "
            f"AND COALESCE(time_updated, time_created, 0) >= {since_ms} "
            "ORDER BY COALESCE(time_updated, time_created, 0) DESC;"
        )
        result = self._runner.run(
            [self._executable, "db", query, "--format", "json"]
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or "OpenCode database query failed"
            raise HarnessSourceError(detail)
        try:
            payload = json.loads(result.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise HarnessSourceError("OpenCode database returned invalid JSON") from exc

        descriptors: list[SessionDescriptor] = []
        for row in _rows_from_payload(payload):
            session_id = row.get("id")
            if not isinstance(session_id, str) or not session_id:
                continue
            descriptors.append(
                SessionDescriptor(
                    harness="opencode",
                    session_id=session_id,
                    created_at=_from_millis(row.get("time_created")),
                    updated_at=_from_millis(row.get("time_updated")),
                    working_directory_hint=(
                        row.get("directory") if isinstance(row.get("directory"), str) else None
                    ),
                    project_id_hint=(
                        row.get("project_id")
                        if isinstance(row.get("project_id"), str)
                        else None
                    ),
                    parent_session_id=(
                        row.get("parent_id")
                        if isinstance(row.get("parent_id"), str)
                        else None
                    ),
                )
            )
        return descriptors

    def load(self, descriptor: SessionDescriptor) -> AgentSession:
        result = self._runner.run(
            [self._executable, "export", descriptor.session_id, "--sanitize"]
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or f"OpenCode export failed for {descriptor.session_id}"
            raise SessionParseError(detail)
        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise SessionParseError(
                f"OpenCode export returned invalid JSON for {descriptor.session_id}"
            ) from exc
        return OpenCodeExportMapper().map(payload, descriptor)
