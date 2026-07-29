"""Summarizer contract and deterministic evidence helpers."""

from abc import ABC, abstractmethod

from agent_worklog.models.evidence import RepositoryEvidence
from agent_worklog.models.report import RepositorySummary, SessionRef


class RepositorySummarizer(ABC):
    @abstractmethod
    def summarize(self, evidence: RepositoryEvidence) -> RepositorySummary:
        """Create a repository summary from structured evidence."""


def session_refs(evidence: RepositoryEvidence) -> list[SessionRef]:
    """Return session identifiers exactly as recorded; never model-generated."""

    return [
        SessionRef(session_id=session.session_id, title=session.title)
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
