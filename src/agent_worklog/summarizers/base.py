"""Summarizer contract and deterministic evidence helpers."""

from abc import ABC, abstractmethod

from agent_worklog.extraction.pipeline import EVIDENCE_TEXT_MAX_LENGTH
from agent_worklog.models.evidence import RepositoryEvidence
from agent_worklog.models.report import RepositorySummary, SessionRef


class RepositorySummarizer(ABC):
    @abstractmethod
    def summarize(self, evidence: RepositoryEvidence) -> RepositorySummary:
        """Create a repository summary from structured evidence."""


def _normalized_title(title: str | None) -> str | None:
    """Collapse whitespace and cap length, matching the evidence text cap.

    A harness-recorded title has no length bound of its own — Codex's
    `threads.title` is the verbatim first user message, and the longest
    observed on a real machine is 1,478 characters. Titles reach both the
    rendered report and the outbound LLM request, so the same 300-character
    budget `extraction/pipeline.py` enforces for evidence text applies here,
    with the same trailing `…` marking the cut.
    """

    if title is None:
        return None
    collapsed = " ".join(title.split())
    if not collapsed:
        return None
    if len(collapsed) <= EVIDENCE_TEXT_MAX_LENGTH:
        return collapsed
    return collapsed[: EVIDENCE_TEXT_MAX_LENGTH - 1].rstrip() + "…"


def session_refs(evidence: RepositoryEvidence) -> list[SessionRef]:
    """Return session identifiers exactly as recorded; never model-generated.

    Unlike the summary lists, this one is deliberately uncapped: it is the report's
    only index back to individual sessions, and a busy repository is exactly where
    that index is needed. Operators bound it with `--root-only` or a shorter period.
    """

    return [
        SessionRef(
            session_id=session.session_id,
            title=_normalized_title(session.title),
        )
        for session in evidence.sessions
    ]


def session_directories(evidence: RepositoryEvidence) -> list[str]:
    """Return the distinct working directories seen for one repository."""

    directories: list[str] = []
    for session in evidence.sessions:
        directory = (session.working_directory or "").strip()
        if directory and directory not in directories:
            directories.append(directory)
    return sorted(directories)
