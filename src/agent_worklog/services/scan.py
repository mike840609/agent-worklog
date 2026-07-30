"""Cross-project session scanning orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from agent_worklog.errors import HarnessSourceError, SessionParseError
from agent_worklog.harnesses.base import HarnessSessionSource
from agent_worklog.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from agent_worklog.models.session import AgentSession
from agent_worklog.models.time_range import DateRange
from agent_worklog.progress import NullProgressReporter, ProgressReporter, ProgressStage
from agent_worklog.sessions.filtering import filter_session_to_period
from agent_worklog.sessions.hierarchy import group_resolved_sessions


class Resolver(Protocol):
    def resolve(self, session: AgentSession) -> RepositoryIdentity: ...


@dataclass(frozen=True)
class ScanResult:
    period: DateRange
    candidate_session_count: int
    loaded_session_count: int
    failed_session_count: int
    resolved_sessions: list[ResolvedSession] = field(default_factory=list)
    sessions_by_repository: dict[str, list[ResolvedSession]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class ScanService:
    """Discover, independently load, filter, and repository-resolve sessions."""

    def __init__(
        self,
        *,
        source: HarnessSessionSource,
        period: DateRange,
        resolver: Resolver,
        progress: ProgressReporter | None = None,
    ) -> None:
        self._source = source
        self._period = period
        self._resolver = resolver
        self._progress = progress if progress is not None else NullProgressReporter()

    def scan(self) -> ScanResult:
        self._progress.start(ProgressStage.DISCOVERING_SESSIONS)
        descriptors = self._source.discover(self._period)
        self._progress.start(
            ProgressStage.EXPORTING_SESSIONS,
            total=len(descriptors),
        )
        resolved_sessions: list[ResolvedSession] = []
        warnings: list[str] = []
        failed_count = 0
        successful_exports = 0

        for completed, descriptor in enumerate(descriptors, start=1):
            try:
                try:
                    session = self._source.load(descriptor)
                except (SessionParseError, HarnessSourceError) as exc:
                    failed_count += 1
                    warnings.append(
                        f"Session {descriptor.session_id} export failed: {exc}"
                    )
                    continue
                successful_exports += 1
                missing_timestamp_count = sum(
                    activity.timestamp is None for activity in session.activities
                )
                if missing_timestamp_count:
                    warnings.append(
                        f"Session {session.session_id} has {missing_timestamp_count} "
                        "timestamp-less activities that were excluded"
                    )
                filtered = filter_session_to_period(session, self._period)
                if filtered is None:
                    continue
                repository = self._resolver.resolve(filtered)
                if repository.identity_type in {
                    RepositoryIdentityType.HARNESS_PROJECT,
                    RepositoryIdentityType.PATH_FALLBACK,
                    RepositoryIdentityType.UNKNOWN,
                }:
                    warnings.append(
                        f"Session {session.session_id} used fallback repository identity "
                        f"{repository.repository_id}"
                    )
                resolved_sessions.append(
                    ResolvedSession(session=filtered, repository=repository)
                )
            finally:
                self._progress.advance(completed)

        if descriptors and successful_exports == 0 and failed_count == len(descriptors):
            raise HarnessSourceError("all OpenCode session exports failed")

        return ScanResult(
            period=self._period,
            candidate_session_count=len(descriptors),
            loaded_session_count=len(resolved_sessions),
            failed_session_count=failed_count,
            resolved_sessions=resolved_sessions,
            sessions_by_repository=group_resolved_sessions(resolved_sessions),
            warnings=warnings,
        )
