from datetime import datetime
from zoneinfo import ZoneInfo

from agent_worklog.models.report import RepositorySummary, SessionRef, WorklogReport
from agent_worklog.models.time_range import DateRange
from agent_worklog.renderers.markdown import MarkdownRenderer

TZ = ZoneInfo("Asia/Taipei")


def sample_report() -> WorklogReport:
    return WorklogReport(
        generated_at=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
        period=DateRange(
            since=datetime(2026, 7, 20, tzinfo=TZ),
            until=datetime(2026, 7, 27, tzinfo=TZ),
        ),
        repositories=[
            RepositorySummary(
                repository_id="git:github.com/mike/agent-worklog",
                display_name="Agent Worklog",
                normalized_remote="github.com/mike/agent-worklog",
                summary="Implemented the MVP.",
                completed=["Tests passed"],
                in_progress=["Add cache"],
                key_files=["src/agent_worklog/cli.py"],
                directories=["/repos/agent-worklog", "/worktrees/agent-feature"],
                sessions=[
                    SessionRef(session_id="ses_abc", title="Fix the exporter"),
                    SessionRef(session_id="ses_def"),
                ],
                session_count=2,
                child_session_count=1,
                branches=["main"],
            )
        ],
        warnings=["One session could not be exported."],
    )


def test_markdown_contains_period_repository_and_warnings() -> None:
    output = MarkdownRenderer().render(sample_report())

    assert "# Engineering Worklog" in output
    assert "Asia/Taipei" in output
    assert "## Repositories" in output
    assert "### Agent Worklog" in output
    assert "github.com/mike/agent-worklog" in output
    assert "## Warnings" in output


def test_markdown_omits_empty_problem_section() -> None:
    output = MarkdownRenderer().render(sample_report())

    assert "#### Problems Resolved" not in output
    assert "#### Completed" in output


def test_markdown_lists_sessions_and_directories() -> None:
    output = MarkdownRenderer().render(sample_report())

    assert "#### Directories" in output
    assert "`/worktrees/agent-feature`" in output
    assert "#### Sessions" in output
    assert "Fix the exporter — `ses_abc`" in output
    assert "ses_def — `ses_def`" in output
