# Usage Statistics, Session References, and Root-Only Scanning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three highest-impact gaps against the reference shell script `opencode-weekly-review-git-grouped`: OpenCode usage statistics, per-session references (title + working directory) in the report, and a flag to exclude subagent sessions.

**Architecture:** All three changes extend existing seams rather than adding layers. `--root-only` is a constructor flag on `OpenCodeCliSource` that appends `AND parent_id IS NULL` to the existing SQL. Session titles and directories flow through the models that already exist (`SessionDescriptor` → `AgentSession` → `SessionEvidence` → `RepositorySummary`), so they inherit the existing redaction pass for free. Usage statistics are a new one-function module invoked by `ReportService` through an injected callable, so a `opencode stats` failure degrades into a report warning instead of an exit code.

**Tech Stack:** Python 3.11+, Typer, Pydantic v2, Jinja2, pytest. No new dependencies.

## Global Constraints

- Python 3.11+ syntax; every module already starts with a docstring — keep that.
- `from __future__ import annotations` where the module already has it; do not add it elsewhere.
- Pydantic v2 models only; new fields must have defaults so existing constructors keep working.
- No new third-party dependencies.
- All subprocess calls go through the `Runner` protocol (`run(args: list[str]) -> CommandResult`) — never `subprocess` directly outside `cli_runner.py`.
- Anything rendered into the report is already redacted by `redact_text` in `ReportService.generate`; do not add a second redaction pass.
- Line length limit is enforced by ruff — keep lines under 100 characters.
- Release gate must stay green: `uv run pytest --cov=agent_worklog --cov-fail-under=80`, `uv run ruff check .`, `uv run pyright`.

## File Structure

**Task 1 — root-only scanning**
- Modify: `src/agent_worklog/harnesses/opencode/source.py` — `root_only` constructor flag, SQL parent filter.
- Modify: `src/agent_worklog/cli.py` — `--root-only` option on `scan` and `report`, threaded into `_build_scan_service`.
- Modify: `tests/unit/harnesses/opencode/test_source_discovery.py`, `tests/integration/test_cli.py`.
- Modify: `README.md`.

**Task 2 — session references and directories**
- Modify: `src/agent_worklog/models/session.py` — `SessionDescriptor.title`.
- Modify: `src/agent_worklog/harnesses/opencode/source.py` — carry the DB `title` column.
- Modify: `src/agent_worklog/harnesses/opencode/mapper.py` — fall back to the descriptor title.
- Modify: `src/agent_worklog/models/evidence.py` — `SessionEvidence.title`, `SessionEvidence.working_directory`.
- Modify: `src/agent_worklog/extraction/pipeline.py` — populate the two new evidence fields.
- Modify: `src/agent_worklog/models/report.py` — `SessionRef` model, `RepositorySummary.sessions`, `RepositorySummary.directories`.
- Modify: `src/agent_worklog/summarizers/base.py` — shared deterministic helpers used by both summarizers.
- Modify: `src/agent_worklog/summarizers/rule_based.py`, `src/agent_worklog/summarizers/openai_compatible.py`.
- Modify: `src/agent_worklog/templates/worklog.md.j2`.
- Modify: `tests/unit/renderers/test_markdown.py`, `tests/unit/harnesses/opencode/test_mapper.py`, `tests/integration/test_end_to_end.py`.

**Task 3 — usage statistics**
- Create: `src/agent_worklog/harnesses/opencode/stats.py` — `usage_days`, `collect_usage_stats`.
- Modify: `src/agent_worklog/models/report.py` — `WorklogReport.usage_text`, `WorklogReport.usage_days`.
- Modify: `src/agent_worklog/services/report.py` — optional `usage_provider`, warning on failure.
- Modify: `src/agent_worklog/cli.py` — wire the provider.
- Modify: `src/agent_worklog/templates/worklog.md.j2` — `## Usage` section.
- Create: `tests/unit/harnesses/opencode/test_stats.py`.
- Modify: `tests/conftest.py`, `tests/integration/test_end_to_end.py`, `README.md`.

---

### Task 1: Root-only session scanning

Adds `--root-only` so subagent/child sessions can be excluded, matching the reference script's default `INCLUDE_SUBAGENTS=0`. Agent Worklog keeps including child sessions by default because it resolves each child's own repository, which the script cannot do.

**Files:**
- Modify: `src/agent_worklog/harnesses/opencode/source.py:43-59`
- Modify: `src/agent_worklog/cli.py:98-135`, `src/agent_worklog/cli.py:172-237`
- Test: `tests/unit/harnesses/opencode/test_source_discovery.py`
- Test: `tests/integration/test_cli.py:115-135`
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `OpenCodeCliSource(*, runner, executable="opencode", root_only: bool = False)`;
  `_build_scan_service(settings: AppSettings, period: DateRange, root_only: bool = False) -> ScanService`;
  `_build_report_service(settings: AppSettings, period: DateRange, output_path: Path, no_llm: bool, root_only: bool = False) -> ReportService`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/harnesses/opencode/test_source_discovery.py`:

```python
def test_discovery_includes_child_sessions_by_default(fake_runner) -> None:
    fake_runner.stdout = "[]"
    source = OpenCodeCliSource(runner=fake_runner, executable="opencode")
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )

    source.discover(period)

    assert "parent_id IS NULL" not in fake_runner.calls[0][2]


def test_root_only_excludes_child_sessions(fake_runner) -> None:
    fake_runner.stdout = "[]"
    source = OpenCodeCliSource(
        runner=fake_runner,
        executable="opencode",
        root_only=True,
    )
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )

    source.discover(period)

    query = fake_runner.calls[0][2]
    assert "AND parent_id IS NULL" in query
    assert query.rstrip().endswith("DESC;")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/harnesses/opencode/test_source_discovery.py -v`
Expected: `test_root_only_excludes_child_sessions` FAILS with `TypeError: __init__() got an unexpected keyword argument 'root_only'`. `test_discovery_includes_child_sessions_by_default` passes already.

- [ ] **Step 3: Add the flag to the source**

In `src/agent_worklog/harnesses/opencode/source.py`, replace the constructor and the first six lines of `discover`:

```python
    def __init__(
        self,
        *,
        runner: Runner,
        executable: str = "opencode",
        root_only: bool = False,
    ) -> None:
        self._runner = runner
        self._executable = executable
        self._root_only = root_only

    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        since_ms = int(period.since.timestamp() * 1000)
        until_ms = int(period.until.timestamp() * 1000)
        parent_filter = "AND parent_id IS NULL " if self._root_only else ""
        query = (
            "SELECT id, project_id, parent_id, directory, title, time_created, time_updated "
            "FROM session "
            f"WHERE time_created < {until_ms} "
            f"AND COALESCE(time_updated, time_created, 0) >= {since_ms} "
            f"{parent_filter}"
            "ORDER BY COALESCE(time_updated, time_created, 0) DESC;"
        )
```

Leave the rest of `discover` unchanged.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/harnesses/opencode/test_source_discovery.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Thread the flag through the CLI**

In `src/agent_worklog/cli.py`, replace `_build_scan_service` and `_build_report_service`:

```python
def _build_scan_service(
    settings: AppSettings,
    period: DateRange,
    root_only: bool = False,
) -> ScanService:
    cli_settings = settings.harnesses.opencode.cli
    source_runner = CommandRunner(timeout_seconds=cli_settings.timeout_seconds)
    git_runner = CommandRunner(timeout_seconds=5.0)
    return ScanService(
        source=OpenCodeCliSource(
            runner=source_runner,
            executable=cli_settings.executable,
            root_only=root_only,
        ),
        period=period,
        resolver=RepositoryResolver(runner=git_runner),
    )


def _build_report_service(
    settings: AppSettings,
    period: DateRange,
    output_path: Path,
    no_llm: bool,
    root_only: bool = False,
) -> ReportService:
    summarizer = RuleBasedSummarizer()
    api_key = os.environ.get(settings.llm.api_key_env)
    if settings.llm.enabled and not no_llm and api_key:
        summarizer = OpenAICompatibleSummarizer(
            model=settings.llm.model,
            api_key=api_key,
            base_url=settings.llm.base_url,
            timeout_seconds=settings.llm.timeout_seconds,
            fallback=RuleBasedSummarizer(),
        )
    return ReportService(
        scan_service=_build_scan_service(settings, period, root_only),
        summarizer=summarizer,
        renderer=MarkdownRenderer(),
        period=period,
        output_path=output_path,
        now_factory=lambda: _now_in_timezone(settings.report.timezone),
    )
```

In the `scan` command signature, add after `until`:

```python
    root_only: bool = typer.Option(
        False,
        "--root-only",
        help="Exclude child/subagent sessions.",
    ),
```

and change its scan call to:

```python
        result = _build_scan_service(settings, selected_period, root_only).scan()
```

In the `report` command signature, add the same `root_only` option after `until`, and change the service construction to:

```python
        service = _build_report_service(
            settings,
            selected_period,
            output_path,
            no_llm,
            root_only,
        )
```

- [ ] **Step 6: Fix the CLI test that monkeypatches `_build_scan_service`**

In `tests/integration/test_cli.py`, inside `test_no_llm_never_constructs_http_summarizer`, replace the monkeypatch line:

```python
    monkeypatch.setattr(
        cli,
        "_build_scan_service",
        lambda settings, period, root_only=False: object(),
    )
```

- [ ] **Step 7: Add a CLI-level test for the flag**

Append to `tests/integration/test_cli.py`:

```python
def test_scan_passes_root_only_to_the_scan_service(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, bool] = {}

    class StubScanService:
        def scan(self):
            return SimpleNamespace(
                loaded_session_count=1,
                sessions_by_repository={},
                warnings=[],
            )

    def build(settings, period, root_only=False):
        captured["root_only"] = root_only
        return StubScanService()

    monkeypatch.setattr(cli, "_build_scan_service", build)

    result = runner.invoke(cli.app, ["scan", "--days", "7", "--root-only"])

    assert result.exit_code == 0
    assert captured["root_only"] is True
```

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest -q`
Expected: all tests PASS.

- [ ] **Step 9: Document the flag**

In `README.md`, insert this section immediately before the `## Repository grouping` heading:

```markdown
## Subagent sessions

Child/subagent sessions are included by default and are attributed to the repository they
actually ran in, so a subagent that worked in another checkout appears under that
repository. To report only root sessions:

```bash
agent-worklog report --period last-week --root-only
```
```

- [ ] **Step 10: Run lint and type checks**

Run: `uv run ruff check . && uv run pyright`
Expected: no findings.

- [ ] **Step 11: Commit**

```bash
git add src/agent_worklog/harnesses/opencode/source.py src/agent_worklog/cli.py \
  tests/unit/harnesses/opencode/test_source_discovery.py tests/integration/test_cli.py README.md
git commit -m "feat: add --root-only to exclude subagent sessions"
```

---

### Task 2: Session references and working directories in the report

The report currently names repositories but never the sessions inside them. `SessionEvidence` does not even carry a title, so the reference script's "Related Sessions" section is unreproducible. This task carries title and working directory from the database row all the way to the rendered Markdown. Both fields are populated deterministically in every summarizer — the LLM never invents session identifiers.

**Files:**
- Modify: `src/agent_worklog/models/session.py:34-41`
- Modify: `src/agent_worklog/harnesses/opencode/source.py:68-87`
- Modify: `src/agent_worklog/harnesses/opencode/mapper.py:175-198`
- Modify: `src/agent_worklog/models/evidence.py:35-42`
- Modify: `src/agent_worklog/extraction/pipeline.py:92-99`
- Modify: `src/agent_worklog/models/report.py:10-21`
- Modify: `src/agent_worklog/summarizers/base.py`
- Modify: `src/agent_worklog/summarizers/rule_based.py:47-83`
- Modify: `src/agent_worklog/summarizers/openai_compatible.py:159-176`
- Modify: `src/agent_worklog/templates/worklog.md.j2`
- Test: `tests/unit/harnesses/opencode/test_mapper.py`, `tests/unit/renderers/test_markdown.py`, `tests/integration/test_end_to_end.py`

**Interfaces:**
- Consumes: `OpenCodeCliSource.discover` from Task 1 (the SQL already selects the `title` column).
- Produces:
  - `SessionDescriptor.title: str | None`
  - `SessionEvidence.title: str | None`, `SessionEvidence.working_directory: str | None`
  - `SessionRef(session_id: str, title: str | None = None)` in `agent_worklog.models.report`
  - `RepositorySummary.sessions: list[SessionRef]`, `RepositorySummary.directories: list[str]`
  - `session_refs(evidence: RepositoryEvidence) -> list[SessionRef]` and
    `session_directories(evidence: RepositoryEvidence) -> list[str]` in `agent_worklog.summarizers.base`

- [ ] **Step 1: Write the failing title-propagation test**

Append to `tests/unit/harnesses/opencode/test_mapper.py`:

```python
def test_mapper_falls_back_to_descriptor_title() -> None:
    descriptor = SessionDescriptor(
        harness="opencode",
        session_id="s1",
        title="Database title",
    )

    session = OpenCodeExportMapper().map({"info": {}, "messages": []}, descriptor)

    assert session.title == "Database title"


def test_mapper_prefers_export_title_over_descriptor_title() -> None:
    descriptor = SessionDescriptor(
        harness="opencode",
        session_id="s1",
        title="Database title",
    )

    session = OpenCodeExportMapper().map(
        {"info": {"title": "Export title"}, "messages": []},
        descriptor,
    )

    assert session.title == "Export title"
```

If `SessionDescriptor` or `OpenCodeExportMapper` is not already imported at the top of that file, add:

```python
from agent_worklog.harnesses.opencode.mapper import OpenCodeExportMapper
from agent_worklog.models.session import SessionDescriptor
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/harnesses/opencode/test_mapper.py -v`
Expected: both new tests FAIL — `SessionDescriptor` has no `title` field, so Pydantic raises a validation error for an unexpected keyword.

- [ ] **Step 3: Carry the title from the database row to the session**

In `src/agent_worklog/models/session.py`, add `title` to `SessionDescriptor`:

```python
class SessionDescriptor(BaseModel):
    harness: str
    session_id: str
    title: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    working_directory_hint: str | None = None
    project_id_hint: str | None = None
    parent_session_id: str | None = None
```

In `src/agent_worklog/harnesses/opencode/source.py`, inside the `discover` row loop, read the column and pass it through:

```python
            directory = row.get("directory")
            project_id = row.get("project_id")
            parent_id = row.get("parent_id")
            title = row.get("title")
            descriptors.append(
                SessionDescriptor(
                    harness="opencode",
                    session_id=session_id,
                    title=(title if isinstance(title, str) else None),
                    created_at=_from_millis(row.get("time_created")),
                    updated_at=_from_millis(row.get("time_updated")),
                    working_directory_hint=(directory if isinstance(directory, str) else None),
                    project_id_hint=(project_id if isinstance(project_id, str) else None),
                    parent_session_id=(parent_id if isinstance(parent_id, str) else None),
                )
            )
```

In `src/agent_worklog/harnesses/opencode/mapper.py`, change the `title=` argument of the returned `AgentSession`:

```python
            title=title if isinstance(title, str) else descriptor.title,
```

- [ ] **Step 4: Run to verify the mapper tests pass**

Run: `uv run pytest tests/unit/harnesses/opencode/test_mapper.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Write the failing evidence test**

Append to `tests/unit/extraction/test_pipeline.py`:

```python
def test_extraction_carries_session_title_and_directory() -> None:
    resolved = ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id="s1",
            title="Fix the exporter",
            working_directory="/repos/agent-worklog",
        ),
        repository=RepositoryIdentity(
            repository_id="git:github.com/mike/agent-worklog",
            display_name="Agent Worklog",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            resolution_method="git_origin_remote",
        ),
    )

    evidence = extract_evidence(resolved)

    assert evidence.title == "Fix the exporter"
    assert evidence.working_directory == "/repos/agent-worklog"
```

Add any missing imports at the top of that file:

```python
from agent_worklog.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from agent_worklog.models.session import AgentSession
```

- [ ] **Step 6: Run to verify failure**

Run: `uv run pytest tests/unit/extraction/test_pipeline.py -v`
Expected: FAIL with `AttributeError: 'SessionEvidence' object has no attribute 'title'`.

- [ ] **Step 7: Add the evidence fields**

In `src/agent_worklog/models/evidence.py`, replace the `SessionEvidence` class:

```python
class SessionEvidence(BaseModel):
    session_id: str
    repository_id: str
    title: str | None = None
    working_directory: str | None = None
    goals: list[EvidenceItem] = Field(default_factory=list)
    commands: list[EvidenceItem] = Field(default_factory=list)
    files_changed: list[EvidenceItem] = Field(default_factory=list)
    errors: list[EvidenceItem] = Field(default_factory=list)
    outcomes: list[EvidenceItem] = Field(default_factory=list)
```

In `src/agent_worklog/extraction/pipeline.py`, replace the `evidence = SessionEvidence(...)` construction inside `extract_evidence`:

```python
    evidence = SessionEvidence(
        session_id=resolved.session.session_id,
        repository_id=resolved.repository.repository_id,
        title=resolved.session.title,
        working_directory=resolved.session.working_directory,
    )
```

- [ ] **Step 8: Run to verify it passes**

Run: `uv run pytest tests/unit/extraction/test_pipeline.py -v`
Expected: all tests PASS.

- [ ] **Step 9: Write the failing renderer test**

In `tests/unit/renderers/test_markdown.py`, add `SessionRef` to the import line:

```python
from agent_worklog.models.report import RepositorySummary, SessionRef, WorklogReport
```

Add these two arguments to the `RepositorySummary(...)` call inside `sample_report()`, immediately after `key_files=[...]`:

```python
                directories=["/repos/agent-worklog", "/worktrees/agent-feature"],
                sessions=[
                    SessionRef(session_id="ses_abc", title="Fix the exporter"),
                    SessionRef(session_id="ses_def"),
                ],
```

Append this test:

```python
def test_markdown_lists_sessions_and_directories() -> None:
    output = MarkdownRenderer().render(sample_report())

    assert "#### Directories" in output
    assert "`/worktrees/agent-feature`" in output
    assert "#### Sessions" in output
    assert "Fix the exporter — `ses_abc`" in output
    assert "ses_def — `ses_def`" in output
```

- [ ] **Step 10: Run to verify failure**

Run: `uv run pytest tests/unit/renderers/test_markdown.py -v`
Expected: FAIL — `RepositorySummary` rejects the unknown `directories` and `sessions` fields.

- [ ] **Step 11: Add the report model fields**

In `src/agent_worklog/models/report.py`, add `SessionRef` above `RepositorySummary` and extend `RepositorySummary`:

```python
class SessionRef(BaseModel):
    session_id: str
    title: str | None = None


class RepositorySummary(BaseModel):
    repository_id: str
    display_name: str
    normalized_remote: str | None = None
    summary: str = ""
    completed: list[str] = Field(default_factory=list)
    problems_resolved: list[str] = Field(default_factory=list)
    in_progress: list[str] = Field(default_factory=list)
    key_files: list[str] = Field(default_factory=list)
    directories: list[str] = Field(default_factory=list)
    sessions: list[SessionRef] = Field(default_factory=list)
    session_count: int = 0
    child_session_count: int = 0
    branches: list[str] = Field(default_factory=list)
```

- [ ] **Step 12: Render the new sections**

In `src/agent_worklog/templates/worklog.md.j2`, insert this block immediately after the `{% if repository.key_files %}` ... `{% endif %}` block (that is, after the line `{% endif %}` that closes Key Files, and before `{% if repository.branches %}`):

```jinja
{% if repository.directories %}

#### Directories
{% for item in repository.directories %}
- `{{ item }}`
{% endfor %}
{% endif %}
{% if repository.sessions %}

#### Sessions
{% for item in repository.sessions %}
- {{ item.title or item.session_id }} — `{{ item.session_id }}`
{% endfor %}
{% endif %}
```

- [ ] **Step 13: Run to verify the renderer test passes**

Run: `uv run pytest tests/unit/renderers/test_markdown.py -v`
Expected: all tests PASS.

- [ ] **Step 14: Populate the fields in both summarizers**

In `src/agent_worklog/summarizers/base.py`, replace the whole file:

```python
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
```

In `src/agent_worklog/summarizers/rule_based.py`, change the import line and the returned summary. The import becomes:

```python
from agent_worklog.summarizers.base import (
    RepositorySummarizer,
    session_directories,
    session_refs,
)
```

and the `return RepositorySummary(...)` gains two arguments after `key_files=`:

```python
        return RepositorySummary(
            repository_id=evidence.repository_id,
            display_name=evidence.display_name,
            normalized_remote=evidence.normalized_remote,
            summary=summary_text,
            completed=_limited(completed),
            problems_resolved=_limited(problems_resolved),
            in_progress=_limited(in_progress),
            key_files=_limited(key_files),
            directories=session_directories(evidence),
            sessions=session_refs(evidence),
            session_count=session_count,
            child_session_count=evidence.child_session_count,
            branches=_unique_sorted(evidence.branches),
        )
```

In `src/agent_worklog/summarizers/openai_compatible.py`, change the import line:

```python
from agent_worklog.summarizers.base import (
    RepositorySummarizer,
    session_directories,
    session_refs,
)
```

and add the same two arguments to the `RepositorySummary(...)` built inside `summarize`, after `key_files=result.key_files,`:

```python
                    directories=session_directories(evidence),
                    sessions=session_refs(evidence),
```

Do not touch `_SCHEMA` or `_StructuredSummary` — session identifiers must stay outside the model's output.

- [ ] **Step 15: Assert the end-to-end report names its sessions**

In `tests/integration/test_end_to_end.py`, append these assertions to `test_end_to_end_weekly_worklog`, after the existing `assert content.count("### Agent Worklog") == 1`:

```python
    assert "#### Sessions" in content
    assert "root-agent" in content
    assert "#### Directories" in content
    assert "/worktrees/agent-main" in content
```

- [ ] **Step 16: Run the full suite**

Run: `uv run pytest -q`
Expected: all tests PASS.

- [ ] **Step 17: Run lint and type checks**

Run: `uv run ruff check . && uv run pyright`
Expected: no findings.

- [ ] **Step 18: Commit**

```bash
git add src/agent_worklog tests README.md
git commit -m "feat: list session titles and working directories per repository"
```

---

### Task 3: OpenCode usage statistics

Adds the `opencode stats` output the reference script feeds into its Usage Overview. `opencode stats` only accepts a rolling window ending now, so the window is widened to cover from the report period's start until generation time and the report says so explicitly rather than implying an exact match. A stats failure produces a warning, never a non-zero exit.

**Files:**
- Create: `src/agent_worklog/harnesses/opencode/stats.py`
- Modify: `src/agent_worklog/models/report.py` (`WorklogReport`)
- Modify: `src/agent_worklog/services/report.py:41-116`
- Modify: `src/agent_worklog/cli.py` (`_build_report_service`)
- Modify: `src/agent_worklog/templates/worklog.md.j2`
- Test: `tests/unit/harnesses/opencode/test_stats.py` (create)
- Test: `tests/integration/test_report_service.py`, `tests/integration/test_end_to_end.py`
- Modify: `tests/conftest.py`, `README.md`

**Interfaces:**
- Consumes: `CommandRunner` and the `Runner` protocol; `DateRange` from `agent_worklog.models.time_range`.
- Produces:
  - `usage_days(period: DateRange, now: datetime) -> int`
  - `collect_usage_stats(*, runner: Runner, executable: str, days: int) -> str` — raises `HarnessSourceError` on any failure
  - `WorklogReport.usage_text: str | None`, `WorklogReport.usage_days: int | None`
  - `ReportService(..., usage_provider: Callable[[], str] | None = None, usage_days: int | None = None)`

- [ ] **Step 1: Write the failing stats tests**

Create `tests/unit/harnesses/opencode/test_stats.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agent_worklog.errors import HarnessSourceError
from agent_worklog.harnesses.opencode.cli_runner import CommandResult
from agent_worklog.harnesses.opencode.stats import collect_usage_stats, usage_days
from agent_worklog.models.time_range import DateRange

TZ = ZoneInfo("Asia/Taipei")


def test_usage_days_covers_period_start_until_now() -> None:
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )

    assert usage_days(period, datetime(2026, 7, 29, 20, 0, tzinfo=TZ)) == 10


def test_usage_days_is_at_least_one() -> None:
    period = DateRange(
        since=datetime(2026, 7, 29, 18, 0, tzinfo=TZ),
        until=datetime(2026, 7, 29, 19, 0, tzinfo=TZ),
    )

    assert usage_days(period, datetime(2026, 7, 29, 19, 0, tzinfo=TZ)) == 1


def test_collect_usage_stats_requests_models_and_tools(fake_runner) -> None:
    fake_runner.stdout = "gpt-5-mini  1234 tokens\n"

    text = collect_usage_stats(runner=fake_runner, executable="opencode", days=10)

    assert text == "gpt-5-mini  1234 tokens"
    assert fake_runner.calls[0] == [
        "opencode",
        "stats",
        "--days",
        "10",
        "--models",
        "20",
        "--tools",
        "20",
    ]


def test_collect_usage_stats_raises_on_failure(fake_runner) -> None:
    fake_runner.set_result(
        "--tools 20",
        CommandResult(returncode=1, stdout="", stderr="stats unsupported"),
    )

    with pytest.raises(HarnessSourceError, match="stats unsupported"):
        collect_usage_stats(runner=fake_runner, executable="opencode", days=7)


def test_collect_usage_stats_raises_on_empty_output(fake_runner) -> None:
    fake_runner.stdout = "   \n"

    with pytest.raises(HarnessSourceError, match="no output"):
        collect_usage_stats(runner=fake_runner, executable="opencode", days=7)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/harnesses/opencode/test_stats.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'agent_worklog.harnesses.opencode.stats'`.

- [ ] **Step 3: Create the stats module**

Create `src/agent_worklog/harnesses/opencode/stats.py`:

```python
"""Optional OpenCode usage statistics collection."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Protocol

from agent_worklog.errors import HarnessSourceError
from agent_worklog.harnesses.opencode.cli_runner import CommandResult
from agent_worklog.models.time_range import DateRange


class Runner(Protocol):
    def run(self, args: list[str]) -> CommandResult: ...


def usage_days(period: DateRange, now: datetime) -> int:
    """Return whole days from the period start to now, at least one.

    `opencode stats` only accepts a rolling window ending now, so the window is
    widened to contain the report period instead of matching it exactly.
    """

    elapsed_days = (now - period.since).total_seconds() / 86400
    return max(1, math.ceil(elapsed_days))


def collect_usage_stats(*, runner: Runner, executable: str, days: int) -> str:
    """Return raw `opencode stats` output for the trailing window."""

    # ponytail: raw CLI text, not parsed. Parse only if the report needs per-model rows.
    try:
        result = runner.run(
            [
                executable,
                "stats",
                "--days",
                str(days),
                "--models",
                "20",
                "--tools",
                "20",
            ]
        )
    except (FileNotFoundError, TimeoutError, OSError) as exc:
        raise HarnessSourceError(type(exc).__name__) from exc
    if result.returncode != 0:
        raise HarnessSourceError(result.stderr.strip() or "opencode stats failed")
    text = result.stdout.strip()
    if not text:
        raise HarnessSourceError("opencode stats returned no output")
    return text
```

- [ ] **Step 4: Run to verify the stats tests pass**

Run: `uv run pytest tests/unit/harnesses/opencode/test_stats.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Write the failing report-service tests**

Append to `tests/integration/test_report_service.py`:

```python
def test_usage_statistics_are_written_into_the_report(tmp_path: Path) -> None:
    source = FakeSource()
    output = tmp_path / "report.md"
    report_service = ReportService(
        scan_service=ScanService(source=source, period=period(), resolver=StaticResolver()),
        summarizer=RuleBasedSummarizer(),
        renderer=MarkdownRenderer(),
        period=period(),
        output_path=output,
        now_factory=lambda: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
        usage_provider=lambda: "gpt-5-mini  1234 tokens",
        usage_days=10,
    )

    result = report_service.generate(force=False)

    assert result.report.usage_text == "gpt-5-mini  1234 tokens"
    assert result.report.usage_days == 10
    content = output.read_text()
    assert "## Usage" in content
    assert "gpt-5-mini  1234 tokens" in content


def test_usage_failure_becomes_a_warning(tmp_path: Path) -> None:
    def failing_provider() -> str:
        raise HarnessSourceError("stats unsupported")

    source = FakeSource()
    output = tmp_path / "report.md"
    report_service = ReportService(
        scan_service=ScanService(source=source, period=period(), resolver=StaticResolver()),
        summarizer=RuleBasedSummarizer(),
        renderer=MarkdownRenderer(),
        period=period(),
        output_path=output,
        now_factory=lambda: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
        usage_provider=failing_provider,
        usage_days=10,
    )

    result = report_service.generate(force=False)

    assert result.report.usage_text is None
    assert any("usage statistics unavailable" in warning for warning in result.warnings)
    assert "## Usage" not in output.read_text()
```

- [ ] **Step 6: Run to verify failure**

Run: `uv run pytest tests/integration/test_report_service.py -v`
Expected: both new tests FAIL with `TypeError: __init__() got an unexpected keyword argument 'usage_provider'`.

- [ ] **Step 7: Add the report model fields**

In `src/agent_worklog/models/report.py`, extend `WorklogReport`:

```python
class WorklogReport(BaseModel):
    schema_version: str = "1"
    generated_at: datetime
    period: DateRange
    repositories: list[RepositorySummary]
    usage_text: str | None = None
    usage_days: int | None = None
    warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 8: Collect usage inside the report service**

In `src/agent_worklog/services/report.py`, add the error import next to the existing imports:

```python
from agent_worklog.errors import HarnessSourceError
```

Extend `__init__` with the two new keyword arguments (append them after `now_factory`):

```python
        now_factory: Callable[[], datetime],
        usage_provider: Callable[[], str] | None = None,
        usage_days: int | None = None,
    ) -> None:
        self._scan_service = scan_service
        self._summarizer = summarizer
        self._renderer = renderer
        self._period = period
        self._output_path = output_path
        self._now_factory = now_factory
        self._usage_provider = usage_provider
        self._usage_days = usage_days
```

In `generate`, insert the collection between the summarizer loop and the `WorklogReport(...)` construction, and pass the new fields:

```python
        summaries.sort(key=lambda item: item.display_name.casefold())
        usage_text: str | None = None
        if self._usage_provider is not None:
            try:
                usage_text = self._usage_provider()
            except HarnessSourceError as exc:
                warnings.append(f"OpenCode usage statistics unavailable: {exc}")
        report = WorklogReport(
            generated_at=self._now_factory(),
            period=self._period,
            repositories=summaries,
            usage_text=usage_text,
            usage_days=self._usage_days if usage_text else None,
            warnings=[redact_text(warning) for warning in warnings],
        )
```

- [ ] **Step 9: Render the usage section**

In `src/agent_worklog/templates/worklog.md.j2`, insert this block between the `{% endfor %}` that closes the repository loop and the `{% if report.warnings %}` block:

````jinja
{% if report.usage_text %}
## Usage
{% if report.usage_days %}

Window: the last {{ report.usage_days }} days ending at generation time. It contains the
report period but does not match it exactly, because OpenCode reports usage only for a
window ending now.
{% endif %}

```text
{{ report.usage_text }}
```
{% endif %}
````

Note: write the three-backtick fences into the template literally — they are Markdown output, not Jinja syntax.

- [ ] **Step 10: Run to verify the report-service tests pass**

Run: `uv run pytest tests/integration/test_report_service.py -v`
Expected: all tests PASS. `HarnessSourceError` is already imported at the top of that file, so no import change is needed.

- [ ] **Step 11: Wire the provider into the CLI**

In `src/agent_worklog/cli.py`, add the import next to the other harness imports:

```python
from agent_worklog.harnesses.opencode.stats import collect_usage_stats, usage_days
```

Replace the body of `_build_report_service` (keeping the signature from Task 1):

```python
def _build_report_service(
    settings: AppSettings,
    period: DateRange,
    output_path: Path,
    no_llm: bool,
    root_only: bool = False,
) -> ReportService:
    summarizer = RuleBasedSummarizer()
    api_key = os.environ.get(settings.llm.api_key_env)
    if settings.llm.enabled and not no_llm and api_key:
        summarizer = OpenAICompatibleSummarizer(
            model=settings.llm.model,
            api_key=api_key,
            base_url=settings.llm.base_url,
            timeout_seconds=settings.llm.timeout_seconds,
            fallback=RuleBasedSummarizer(),
        )
    cli_settings = settings.harnesses.opencode.cli
    stats_runner = CommandRunner(timeout_seconds=cli_settings.timeout_seconds)
    days = usage_days(period, _now_in_timezone(settings.report.timezone))
    return ReportService(
        scan_service=_build_scan_service(settings, period, root_only),
        summarizer=summarizer,
        renderer=MarkdownRenderer(),
        period=period,
        output_path=output_path,
        now_factory=lambda: _now_in_timezone(settings.report.timezone),
        usage_provider=lambda: collect_usage_stats(
            runner=stats_runner,
            executable=cli_settings.executable,
            days=days,
        ),
        usage_days=days,
    )
```

- [ ] **Step 12: Teach the acceptance runner about `opencode stats`**

In `tests/conftest.py`, inside `AcceptanceCommandRunner.run`, add this branch immediately after the `opencode db` branch:

```python
        if args[:2] == ["opencode", "stats"]:
            return CommandResult(
                0,
                "models: gpt-5-mini 1234 tokens\ntools: bash 12 calls\n",
                "",
            )
```

- [ ] **Step 13: Assert usage reaches the end-to-end report**

In `tests/integration/test_end_to_end.py`, append to `test_end_to_end_weekly_worklog`:

```python
    assert "## Usage" in content
    assert "gpt-5-mini 1234 tokens" in content
```

- [ ] **Step 14: Run the full suite with coverage**

Run: `uv run pytest --cov=agent_worklog --cov-fail-under=80`
Expected: all tests PASS and coverage stays above 80%.

- [ ] **Step 15: Document the usage section**

In `README.md`, add this section immediately before the `## Output and overwrite behavior` heading:

```markdown
## Usage statistics

Each report includes an OpenCode usage section built from `opencode stats`, covering
models, tokens, and tools. OpenCode reports usage only for a window ending now, so the
window shown starts at the report period's start and runs to generation time; it contains
the report period but is wider than it. If `opencode stats` is unavailable, the section is
omitted and a warning is recorded in the report.
```

In `README.md`, under `## MVP limitations`, replace the line `- Markdown is the only report format.` with:

```markdown
- Markdown is the only report format.
- Usage statistics cover a window ending at generation time, not the report period exactly.
```

- [ ] **Step 16: Run lint and type checks**

Run: `uv run ruff check . && uv run pyright`
Expected: no findings.

- [ ] **Step 17: Commit**

```bash
git add src/agent_worklog tests README.md
git commit -m "feat: include OpenCode usage statistics in the worklog report"
```

---

## Verification

After all three tasks:

```bash
uv run pytest --cov=agent_worklog --cov-fail-under=80
uv run ruff check .
uv run pyright
uv build
```

Manual smoke check against a real OpenCode installation:

```bash
uv run agent-worklog doctor
uv run agent-worklog scan --days 7 --root-only
uv run agent-worklog report --days 7 --no-llm --dry-run
```

Expect the dry-run Markdown to contain `#### Sessions`, `#### Directories`, and `## Usage`,
and expect `--root-only` to report fewer sessions than the same command without it whenever
subagents ran during the window.
