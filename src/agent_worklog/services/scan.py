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
from agent_worklog.models.session import ActivityType, AgentSession
from agent_worklog.models.time_range import DateRange
from agent_worklog.progress import NullProgressReporter, ProgressReporter, ProgressStage
from agent_worklog.sessions.filtering import filter_session_to_period
from agent_worklog.sessions.hierarchy import group_resolved_sessions

_ASSISTANT_ACTIVITY_TYPES = frozenset(
    {ActivityType.ASSISTANT_MESSAGE, ActivityType.TOOL_CALL}
)


class Resolver(Protocol):
    def resolve(self, session: AgentSession) -> RepositoryIdentity: ...


def _has_assistant_work_but_no_prompt(session: AgentSession) -> bool:
    """Detect a root session whose user prompts were all filtered out of the mapping.

    A Claude Code transcript written before roughly version 2.1.187 carries no
    `origin` key, so the mapper's `origin.kind == "human"` filter — which exists to
    keep hook output and system reminders out of the report's goals — drops every
    user message in that file. 10 of 72 recent root sessions are affected, one of
    them with 188 assistant records. Loosening the filter would readmit the noise
    it was written to block, so the loss is reported instead of guessed at.

    Child and subagent sessions are exempt. A subagent is spawned with a prompt its
    parent wrote, not one a human typed, so it holds no human prompt by design:
    measured over one week, 44 of 44 subagent transcripts have none, against 1 of 10
    root sessions. Warning about them would bury the one case that means something.
    """

    if session.parent_session_id is not None:
        return False
    types = {activity.activity_type for activity in session.activities}
    return bool(types & _ASSISTANT_ACTIVITY_TYPES) and (
        ActivityType.USER_MESSAGE not in types
    )


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
                if _has_assistant_work_but_no_prompt(session):
                    warnings.append(
                        f"Session {session.session_id} recorded assistant work but no "
                        "user messages, so it contributes no goals; a Claude Code "
                        "transcript written before version 2.1.187 does not mark "
                        "human prompts"
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
            raise HarnessSourceError(
                f"all {descriptors[0].harness} session loads failed"
            )

        return ScanResult(
            period=self._period,
            candidate_session_count=len(descriptors),
            loaded_session_count=len(resolved_sessions),
            failed_session_count=failed_count,
            resolved_sessions=resolved_sessions,
            sessions_by_repository=group_resolved_sessions(resolved_sessions),
            warnings=warnings,
        )
