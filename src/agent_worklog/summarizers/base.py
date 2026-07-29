"""Summarizer contract."""

from abc import ABC, abstractmethod

from agent_worklog.models.evidence import RepositoryEvidence
from agent_worklog.models.report import RepositorySummary


class RepositorySummarizer(ABC):
    @abstractmethod
    def summarize(self, evidence: RepositoryEvidence) -> RepositorySummary:
        """Create a repository summary from structured evidence."""
