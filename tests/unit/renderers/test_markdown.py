from datetime import datetime
from zoneinfo import ZoneInfo

from agent_worklog.models.report import RepositorySummary, SessionRef, WorklogReport
from agent_worklog.models.time_range import DateRange
from agent_worklog.renderers.markdown import DetailLevel, MarkdownRenderer

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


EXPECTED_FULL_OUTPUT = """# Engineering Worklog

**Period:** 2026-07-20 00:00 – 2026-07-27 00:00
**Timezone:** Asia/Taipei
**Generated:** 2026-07-29 20:00

## Repositories
### Agent Worklog
Repository: `github.com/mike/agent-worklog`

Implemented the MVP.

Sessions: 2 · Child sessions: 1
#### Completed
- Tests passed

#### In Progress
- Add cache

#### Key Files
- `src/agent_worklog/cli.py`

#### Directories
- `/repos/agent-worklog`
- `/worktrees/agent-feature`

#### Sessions
- Fix the exporter — `ses_abc`
- ses_def — `ses_def`

#### Branches
- `main`

## Warnings
- One session could not be exported.
"""


def test_full_output_is_unchanged_byte_for_byte() -> None:
    """Characterization guard for the truncation refactor.

    The macro rewrite in worklog.md.j2 is a pure whitespace hazard: Jinja's
    trim_blocks and lstrip_blocks make blank lines easy to gain or lose. This
    pins the exact bytes so any drift fails loudly.
    """

    output = MarkdownRenderer().render(sample_report())

    assert output == EXPECTED_FULL_OUTPUT


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


def report_with_completed(items: list[str]) -> WorklogReport:
    return WorklogReport(
        generated_at=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
        period=DateRange(
            since=datetime(2026, 7, 20, tzinfo=TZ),
            until=datetime(2026, 7, 27, tzinfo=TZ),
        ),
        repositories=[
            RepositorySummary(
                repository_id="repo",
                display_name="Repo",
                summary="Worked.",
                completed=items,
                session_count=1,
            )
        ],
    )


def test_full_caps_a_long_section_at_twenty_items() -> None:
    items = [f"Completed {index:02d}" for index in range(25)]

    output = MarkdownRenderer().render(report_with_completed(items))

    assert "- Completed 19" in output
    assert "- Completed 20" not in output
    assert "- Additional items omitted: 5" in output


def test_a_section_at_exactly_the_limit_has_no_overflow_line() -> None:
    items = [f"Completed {index:02d}" for index in range(20)]

    output = MarkdownRenderer().render(report_with_completed(items))

    assert "- Completed 19" in output
    assert "Additional items omitted" not in output


def test_brief_keeps_the_narrative_sections_and_drops_the_appendices() -> None:
    output = MarkdownRenderer().render(sample_report(), detail=DetailLevel.BRIEF)

    assert "# Engineering Worklog" in output
    assert "### Agent Worklog" in output
    assert "Implemented the MVP." in output
    assert "Sessions: 2" in output
    assert "#### Completed" in output
    assert "#### In Progress" in output

    assert "#### Key Files" not in output
    assert "#### Directories" not in output
    assert "#### Sessions" not in output
    assert "#### Branches" not in output


def test_brief_keeps_warnings() -> None:
    """A shorter report is a request for less detail, not less disclosure."""

    output = MarkdownRenderer().render(sample_report(), detail=DetailLevel.BRIEF)

    assert "## Warnings" in output
    assert "One session could not be exported." in output


def test_brief_drops_the_usage_block() -> None:
    report = sample_report()
    report.usage_text = "OVERVIEW\nSessions 2"
    report.usage_days = 5

    output = MarkdownRenderer().render(report, detail=DetailLevel.BRIEF)

    assert "## Usage" not in output
    assert "OVERVIEW" not in output
    assert "Window: the last" not in output


def test_full_keeps_the_usage_block() -> None:
    report = sample_report()
    report.usage_text = "OVERVIEW\nSessions 2"
    report.usage_days = 5

    output = MarkdownRenderer().render(report, detail=DetailLevel.FULL)

    assert "## Usage" in output
    assert "OVERVIEW" in output


def test_brief_caps_sections_at_five_items() -> None:
    items = [f"Completed {index:02d}" for index in range(25)]

    output = MarkdownRenderer().render(
        report_with_completed(items),
        detail=DetailLevel.BRIEF,
    )

    assert "- Completed 04" in output
    assert "- Completed 05" not in output
    assert "- Additional items omitted: 20" in output


def test_brief_default_is_full() -> None:
    assert MarkdownRenderer().render(sample_report()) == EXPECTED_FULL_OUTPUT
