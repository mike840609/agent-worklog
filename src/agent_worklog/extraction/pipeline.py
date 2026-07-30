"""Convert canonical session activities into provenance-aware evidence."""

from __future__ import annotations

from collections.abc import Mapping

from agent_worklog.extraction.rules import (
    ASSISTANT_COMPLETION_PATTERN,
    COMMAND_TOOL_NAMES,
    FILE_TOOL_NAMES,
    is_meaningful_user_text,
    is_verification_command,
)
from agent_worklog.models.evidence import (
    EvidenceConfidence,
    EvidenceItem,
    EvidenceStatus,
    SessionEvidence,
)
from agent_worklog.models.repository import ResolvedSession
from agent_worklog.models.session import ActivityType, SessionActivity


def _normalize(text: str) -> str:
    return " ".join(text.split()).strip()


def _nested_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _exit_code(activity: SessionActivity) -> int | None:
    direct = activity.metadata.get("exit_code")
    if isinstance(direct, int):
        return direct
    state = _nested_mapping(activity.metadata.get("state"))
    for key in ("exit_code", "exitCode", "code"):
        value = state.get(key)
        if isinstance(value, int):
            return value
    metadata = _nested_mapping(state.get("metadata"))
    for key in ("exit", "exit_code", "exitCode"):
        value = metadata.get(key)
        if isinstance(value, int):
            return value
    return None


def _file_path(activity: SessionActivity) -> str | None:
    for source in (
        activity.metadata,
        _nested_mapping(activity.metadata.get("state")),
        _nested_mapping(_nested_mapping(activity.metadata.get("state")).get("input")),
    ):
        for key in ("path", "file", "file_path", "filePath"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    content = _normalize(activity.content)
    return content or None


def _item(
    *,
    text: str,
    activity: SessionActivity,
    confidence: EvidenceConfidence,
    extraction_method: str,
    status: EvidenceStatus = EvidenceStatus.UNKNOWN,
) -> EvidenceItem:
    return EvidenceItem(
        text=_normalize(text),
        source_activity_ids=[activity.activity_id],
        confidence=confidence,
        extraction_method=extraction_method,
        status=status,
    )


def _append_unique(
    items: list[EvidenceItem],
    candidate: EvidenceItem,
    *,
    repository_id: str,
) -> None:
    key = (candidate.text.casefold(), repository_id)
    existing = {(item.text.casefold(), repository_id) for item in items}
    if key not in existing:
        items.append(candidate)


def _append_stderr_heuristic(
    evidence: SessionEvidence,
    *,
    activity: SessionActivity,
    content: str,
    repository_id: str,
) -> None:
    """Infer command success from stderr when the harness reports no exit code.

    Claude Code's tool results carry no exit code, so this is the only signal
    available. It is a guess — pytest writes failures to stdout — so everything
    it produces is MEDIUM confidence, never HIGH.
    """

    stderr_empty = activity.metadata.get("stderr_empty")
    if stderr_empty is False:
        _append_unique(
            evidence.errors,
            _item(
                text=content,
                activity=activity,
                confidence=EvidenceConfidence.MEDIUM,
                extraction_method="stderr_heuristic",
                status=EvidenceStatus.BLOCKED,
            ),
            repository_id=repository_id,
        )
        return
    if (
        stderr_empty is True
        and activity.metadata.get("interrupted") is not True
        and is_verification_command(content)
    ):
        _append_unique(
            evidence.outcomes,
            _item(
                text=f"Verification passed: {content}",
                activity=activity,
                confidence=EvidenceConfidence.MEDIUM,
                extraction_method="stderr_heuristic",
                status=EvidenceStatus.COMPLETED,
            ),
            repository_id=repository_id,
        )


def extract_evidence(resolved: ResolvedSession) -> SessionEvidence:
    """Extract conservative evidence from one repository-resolved session."""

    evidence = SessionEvidence(
        session_id=resolved.session.session_id,
        repository_id=resolved.repository.repository_id,
        title=resolved.session.title,
        working_directory=resolved.session.working_directory,
    )
    repository_id = resolved.repository.repository_id

    for activity in resolved.session.activities:
        content = _normalize(activity.content)
        if activity.activity_type == ActivityType.USER_MESSAGE and is_meaningful_user_text(
            content
        ):
            _append_unique(
                evidence.goals,
                _item(
                    text=content,
                    activity=activity,
                    confidence=EvidenceConfidence.HIGH,
                    extraction_method="user_message",
                    status=EvidenceStatus.IN_PROGRESS,
                ),
                repository_id=repository_id,
            )
            continue

        tool_name = (activity.tool_name or "").casefold()
        is_command = activity.activity_type == ActivityType.COMMAND or (
            activity.activity_type == ActivityType.TOOL_CALL
            and tool_name in COMMAND_TOOL_NAMES
        )
        if is_command and content:
            _append_unique(
                evidence.commands,
                _item(
                    text=content,
                    activity=activity,
                    confidence=EvidenceConfidence.HIGH,
                    extraction_method="tool_command",
                ),
                repository_id=repository_id,
            )
            exit_code = _exit_code(activity)
            if exit_code is not None and exit_code != 0:
                _append_unique(
                    evidence.errors,
                    _item(
                        text=content,
                        activity=activity,
                        confidence=EvidenceConfidence.HIGH,
                        extraction_method="nonzero_exit_code",
                        status=EvidenceStatus.BLOCKED,
                    ),
                    repository_id=repository_id,
                )
            elif exit_code == 0 and is_verification_command(content):
                _append_unique(
                    evidence.outcomes,
                    _item(
                        text=f"Verification passed: {content}",
                        activity=activity,
                        confidence=EvidenceConfidence.HIGH,
                        extraction_method="successful_verification_command",
                        status=EvidenceStatus.COMPLETED,
                    ),
                    repository_id=repository_id,
                )
            elif exit_code is None:
                _append_stderr_heuristic(
                    evidence,
                    activity=activity,
                    content=content,
                    repository_id=repository_id,
                )
            continue

        if activity.activity_type in {ActivityType.FILE_CHANGE, ActivityType.TOOL_CALL} and (
            activity.activity_type == ActivityType.FILE_CHANGE or tool_name in FILE_TOOL_NAMES
        ):
            path = _file_path(activity)
            if path:
                _append_unique(
                    evidence.files_changed,
                    _item(
                        text=path,
                        activity=activity,
                        confidence=EvidenceConfidence.HIGH,
                        extraction_method="file_tool",
                    ),
                    repository_id=repository_id,
                )
            continue

        if (
            activity.activity_type == ActivityType.ASSISTANT_MESSAGE
            and content
            and ASSISTANT_COMPLETION_PATTERN.search(content)
        ):
            _append_unique(
                evidence.outcomes,
                _item(
                    text=content,
                    activity=activity,
                    confidence=EvidenceConfidence.LOW,
                    extraction_method="assistant_claim",
                    status=EvidenceStatus.UNKNOWN,
                ),
                repository_id=repository_id,
            )

    return evidence
