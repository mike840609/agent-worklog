"""Deterministic repository summarization."""

from agent_worklog.models.evidence import (
    EvidenceConfidence,
    EvidenceItem,
    EvidenceStatus,
    RepositoryEvidence,
)
from agent_worklog.models.report import RepositorySummary
from agent_worklog.summarizers.base import RepositorySummarizer

_MAX_ITEMS = 20


def _unique_sorted(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        normalized = " ".join(item.split()).strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            unique.append(normalized)
    return sorted(unique, key=str.casefold)


def _limited(items: list[str]) -> list[str]:
    ordered = _unique_sorted(items)
    if len(ordered) <= _MAX_ITEMS:
        return ordered
    omitted = len(ordered) - _MAX_ITEMS
    return [*ordered[:_MAX_ITEMS], f"Additional items omitted: {omitted}"]


def _completed(items: list[EvidenceItem]) -> list[str]:
    return [
        item.text
        for item in items
        if item.status == EvidenceStatus.COMPLETED
        and item.confidence == EvidenceConfidence.HIGH
    ]


class RuleBasedSummarizer(RepositorySummarizer):
    """Map high-confidence evidence into conservative report sections."""

    def summarize(self, evidence: RepositoryEvidence) -> RepositorySummary:
        completed: list[str] = []
        problems_resolved: list[str] = []
        goals: list[str] = []
        key_files: list[str] = []

        for session in evidence.sessions:
            completed.extend(_completed(session.outcomes))
            problems_resolved.extend(_completed(session.errors))
            goals.extend(
                item.text
                for item in session.goals
                if item.status != EvidenceStatus.COMPLETED
            )
            key_files.extend(item.text for item in session.files_changed)

        completed_keys = {item.casefold() for item in completed}
        in_progress = [goal for goal in goals if goal.casefold() not in completed_keys]
        session_count = len(evidence.sessions)
        summary_text = (
            f"{session_count} session{'s' if session_count != 1 else ''} "
            f"captured for {evidence.display_name}."
        )

        return RepositorySummary(
            repository_id=evidence.repository_id,
            display_name=evidence.display_name,
            normalized_remote=evidence.normalized_remote,
            summary=summary_text,
            completed=_limited(completed),
            problems_resolved=_limited(problems_resolved),
            in_progress=_limited(in_progress),
            key_files=_limited(key_files),
            session_count=session_count,
            child_session_count=evidence.child_session_count,
            branches=_unique_sorted(evidence.branches),
        )
