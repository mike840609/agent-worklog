from datetime import datetime
from zoneinfo import ZoneInfo

from agent_worklog.errors import SessionParseError
from agent_worklog.models.repository import RepositoryIdentity, RepositoryIdentityType
from agent_worklog.models.session import (
    ActivityType,
    AgentSession,
    SessionActivity,
    SessionDescriptor,
)
from agent_worklog.models.time_range import DateRange
from agent_worklog.progress import ProgressStage
from agent_worklog.services.scan import ScanService
from tests.progress import RecordingProgressReporter

TZ = ZoneInfo("Asia/Taipei")


class FakeSource:
    def __init__(self) -> None:
        self.fail_session_ids: set[str] = set()
        self.fail_all = False
        self.activity_timestamps: dict[str, datetime] = {}
        self.descriptors = [
            SessionDescriptor(harness="opencode", session_id="good-1"),
            SessionDescriptor(harness="opencode", session_id="bad"),
            SessionDescriptor(harness="opencode", session_id="good-2"),
        ]

    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        return self.descriptors

    def load(self, descriptor: SessionDescriptor) -> AgentSession:
        if self.fail_all or descriptor.session_id in self.fail_session_ids:
            raise SessionParseError(f"failed export: {descriptor.session_id}")
        return AgentSession(
            harness="opencode",
            session_id=descriptor.session_id,
            activities=[
                SessionActivity(
                    activity_id=f"{descriptor.session_id}:a1",
                    activity_type=ActivityType.USER_MESSAGE,
                    timestamp=self.activity_timestamps.get(
                        descriptor.session_id,
                        datetime(2026, 7, 22, tzinfo=TZ),
                    ),
                    content="Add weekly report generation",
                )
            ],
        )


class StaticResolver:
    def resolve(self, session: AgentSession) -> RepositoryIdentity:
        return RepositoryIdentity(
            repository_id="git:github.com/mike/agent-worklog",
            display_name="Agent Worklog",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            normalized_remote="github.com/mike/agent-worklog",
            branch="main",
            resolution_method="git_origin_remote",
        )


def period() -> DateRange:
    return DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )


class PromptlessSource:
    """A root transcript whose human prompts the mapper could not identify."""

    def __init__(self, *, parent_session_id: str | None = None) -> None:
        self.parent_session_id = parent_session_id

    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        return [SessionDescriptor(harness="claude-code", session_id="old-transcript")]

    def load(self, descriptor: SessionDescriptor) -> AgentSession:
        return AgentSession(
            harness="claude-code",
            session_id=descriptor.session_id,
            parent_session_id=self.parent_session_id,
            activities=[
                SessionActivity(
                    activity_id="a-1",
                    activity_type=ActivityType.ASSISTANT_MESSAGE,
                    timestamp=datetime(2026, 7, 22, tzinfo=TZ),
                    content="I updated the fetcher.",
                ),
                SessionActivity(
                    activity_id="a-2",
                    activity_type=ActivityType.TOOL_CALL,
                    timestamp=datetime(2026, 7, 22, tzinfo=TZ),
                    content="pytest -q",
                    tool_name="Bash",
                ),
            ],
        )


def test_scan_warns_when_assistant_work_has_no_user_messages() -> None:
    """A pre-2.1.187 transcript yields no goals; that must not be silent."""

    service = ScanService(
        source=PromptlessSource(), period=period(), resolver=StaticResolver()
    )

    result = service.scan()

    assert result.loaded_session_count == 1
    assert any(
        "old-transcript" in warning and "no user messages" in warning
        for warning in result.warnings
    ), result.warnings


def test_scan_does_not_warn_when_a_session_has_user_messages() -> None:
    service = ScanService(source=FakeSource(), period=period(), resolver=StaticResolver())

    result = service.scan()

    assert not any("no user messages" in warning for warning in result.warnings)


def test_scan_does_not_warn_about_a_promptless_subagent_session() -> None:
    """A subagent is spawned with its parent's prompt, so it holds no human prompt.

    Measured over one week, 44 of 44 subagent transcripts have none. Warning about
    every one of them would bury the single root session that lost its goals.
    """

    service = ScanService(
        source=PromptlessSource(parent_session_id="root-session"),
        period=period(),
        resolver=StaticResolver(),
    )

    result = service.scan()

    assert result.loaded_session_count == 1
    assert not any("no user messages" in warning for warning in result.warnings)


def test_scan_continues_after_one_export_failure() -> None:
    source = FakeSource()
    source.fail_session_ids = {"bad"}
    service = ScanService(source=source, period=period(), resolver=StaticResolver())

    result = service.scan()

    assert result.loaded_session_count == 2
    assert result.failed_session_count == 1
    assert any("bad" in warning for warning in result.warnings)
    assert list(result.sessions_by_repository) == ["git:github.com/mike/agent-worklog"]


def test_scan_reports_every_discovered_descriptor_as_processed() -> None:
    source = FakeSource()
    source.fail_session_ids = {"bad"}
    source.activity_timestamps["good-2"] = datetime(2026, 7, 1, tzinfo=TZ)
    progress = RecordingProgressReporter()
    service = ScanService(
        source=source,
        period=period(),
        resolver=StaticResolver(),
        progress=progress,
    )

    result = service.scan()

    assert result.loaded_session_count == 1
    assert result.failed_session_count == 1
    assert progress.events == [
        ("start", ProgressStage.DISCOVERING_SESSIONS, None),
        ("start", ProgressStage.EXPORTING_SESSIONS, 3),
        ("advance", 1),
        ("advance", 2),
        ("advance", 3),
    ]
