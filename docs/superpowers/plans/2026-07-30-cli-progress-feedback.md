# CLI Progress Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a transient, single-line, stage-based progress indicator with accurate counts to the interactive `scan` and `report` commands.

**Architecture:** Core services publish semantic progress through an optional, Rich-independent `ProgressReporter`; a no-op implementation preserves existing non-CLI behavior. `ConsoleReporter` owns the Rich adapter and its lifecycle, while one shared reporter flows from each CLI command into `ReportService` and its nested `ScanService`.

**Tech Stack:** Python 3.11+, Typer, Rich 14, pytest, Ruff, Pyright. No new dependencies.

## Global Constraints

- Apply progress only to `scan` and `report`; do not change `doctor`.
- Render one transient progress line, replacing it when stages change.
- Use a spinner for stages without totals and absolute `completed/total` counts where totals are known.
- Write progress to stderr; keep existing final command output on its current stream.
- `--quiet` must suppress progress completely.
- `report --dry-run` Markdown must remain clean on stdout.
- Progress text must not contain session IDs, titles, paths, repository names, warnings, or API errors.
- Core services must not import Rich or perform terminal rendering.
- Preserve existing report content, final output, warnings, and exit codes.
- Keep lines at or below 100 characters.
- Release gates must pass: `uv run pytest --cov=agent_worklog --cov-fail-under=80`, `uv run ruff check .`, `uv run pyright`, and `uv build`.

## File Structure

**Task 1 — progress contract**

- Create: `src/agent_worklog/progress.py` — stage identifiers, reporter protocol, and no-op implementation.
- Create: `tests/unit/test_progress.py` — contract and no-op behavior.
- Create: `tests/progress.py` — recording test reporter shared by service tests.

**Task 2 — scan progress**

- Modify: `src/agent_worklog/services/scan.py` — discovery and per-descriptor events.
- Modify: `tests/integration/test_scan_service.py` — success, failure, and filtered-session counts.

**Task 3 — report progress**

- Modify: `src/agent_worklog/services/report.py` — evidence, summary, usage, render, and write events.
- Modify: `tests/integration/test_report_service.py` — stage ordering, fallback, failure, and dry-run behavior.

**Task 4 — Rich progress renderer**

- Modify: `src/agent_worklog/logging.py` — Rich adapter and managed progress context.
- Create: `tests/unit/test_logging.py` — rendering, stream separation, quiet mode, and cleanup.

**Task 5 — CLI wiring**

- Modify: `src/agent_worklog/cli.py` — pass one managed reporter through service builders and commands.
- Modify: `tests/integration/test_cli.py` — builder propagation, quiet mode, and dry-run stream behavior.

**Task 6 — documentation and release gates**

- Modify: `README.md` — document interactive progress and output modes.
- Modify: `README.zh-TW.md` — add the equivalent Traditional Chinese guidance.
- Modify: `tests/unit/test_documentation.py` — assert both readmes cover progress and quiet mode.

---

### Task 1: Define the Rich-independent progress contract

**Files:**

- Create: `src/agent_worklog/progress.py`
- Create: `tests/unit/test_progress.py`
- Create: `tests/progress.py`

**Interfaces:**

- Consumes: Python 3.11 `StrEnum` and `typing.Protocol`.
- Produces: `ProgressStage`, `ProgressReporter`, `NullProgressReporter`, and the test-only `RecordingProgressReporter`.

- [ ] **Step 1: Write the failing contract test**

Create `tests/unit/test_progress.py`:

```python
from agent_worklog.progress import NullProgressReporter, ProgressStage


def test_progress_stages_are_stable_and_complete() -> None:
    assert [stage.value for stage in ProgressStage] == [
        "discovering_sessions",
        "exporting_sessions",
        "preparing_evidence",
        "summarizing_repositories",
        "collecting_usage",
        "rendering_report",
        "writing_report",
    ]


def test_null_progress_reporter_accepts_the_full_lifecycle() -> None:
    reporter = NullProgressReporter()

    assert reporter.start(ProgressStage.EXPORTING_SESSIONS, total=3) is None
    assert reporter.advance(1) is None
    assert reporter.advance(3) is None
    assert reporter.finish() is None
    assert reporter.finish() is None
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
uv run pytest tests/unit/test_progress.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'agent_worklog.progress'`.

- [ ] **Step 3: Implement the progress contract**

Create `src/agent_worklog/progress.py`:

```python
"""Rich-independent progress events for long-running application services."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol


class ProgressStage(StrEnum):
    """Stable semantic stages rendered by the CLI."""

    DISCOVERING_SESSIONS = "discovering_sessions"
    EXPORTING_SESSIONS = "exporting_sessions"
    PREPARING_EVIDENCE = "preparing_evidence"
    SUMMARIZING_REPOSITORIES = "summarizing_repositories"
    COLLECTING_USAGE = "collecting_usage"
    RENDERING_REPORT = "rendering_report"
    WRITING_REPORT = "writing_report"


class ProgressReporter(Protocol):
    """Receive absolute progress updates from synchronous services."""

    def start(
        self,
        stage: ProgressStage,
        *,
        total: int | None = None,
    ) -> None: ...

    def advance(self, completed: int) -> None: ...

    def finish(self) -> None: ...


class NullProgressReporter:
    """Ignore progress events while preserving the service interface."""

    def start(
        self,
        stage: ProgressStage,
        *,
        total: int | None = None,
    ) -> None:
        pass

    def advance(self, completed: int) -> None:
        pass

    def finish(self) -> None:
        pass
```

- [ ] **Step 4: Add the shared recording reporter for service tests**

Create `tests/progress.py`:

```python
from agent_worklog.progress import ProgressStage


class RecordingProgressReporter:
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []

    def start(
        self,
        stage: ProgressStage,
        *,
        total: int | None = None,
    ) -> None:
        self.events.append(("start", stage, total))

    def advance(self, completed: int) -> None:
        self.events.append(("advance", completed))

    def finish(self) -> None:
        self.events.append(("finish",))
```

- [ ] **Step 5: Run the test and type checker**

Run:

```bash
uv run pytest tests/unit/test_progress.py -v
uv run pyright
```

Expected: both commands pass with no findings.

- [ ] **Step 6: Commit the contract**

```bash
git add src/agent_worklog/progress.py tests/unit/test_progress.py tests/progress.py
git commit -m "feat: define service progress events"
```

---

### Task 2: Emit accurate scan progress

**Files:**

- Modify: `src/agent_worklog/services/scan.py:8-18,39-101`
- Modify: `tests/integration/test_scan_service.py:18-77`

**Interfaces:**

- Consumes: `ProgressReporter.start`, `ProgressReporter.advance`, `ProgressStage`, and `NullProgressReporter` from Task 1.
- Produces: `ScanService(..., progress: ProgressReporter | None = None)` with discovery and absolute per-descriptor progress events.

- [ ] **Step 1: Make the scan fake able to produce a filtered session**

In `tests/integration/test_scan_service.py`, add this field in `FakeSource.__init__`:

```python
        self.activity_timestamps: dict[str, datetime] = {}
```

Then replace the hard-coded activity timestamp in `FakeSource.load`:

```python
                    timestamp=self.activity_timestamps.get(
                        descriptor.session_id,
                        datetime(2026, 7, 22, tzinfo=TZ),
                    ),
```

- [ ] **Step 2: Write the failing scan progress test**

Add these imports to `tests/integration/test_scan_service.py`:

```python
from agent_worklog.progress import ProgressStage
from tests.progress import RecordingProgressReporter
```

Append:

```python
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
```

- [ ] **Step 3: Run the scan test and verify it fails**

Run:

```bash
uv run pytest \
  tests/integration/test_scan_service.py::test_scan_reports_every_discovered_descriptor_as_processed \
  -v
```

Expected: fails with `TypeError: ScanService.__init__() got an unexpected keyword argument 'progress'`.

- [ ] **Step 4: Add the optional reporter to `ScanService`**

Add this import to `src/agent_worklog/services/scan.py`:

```python
from agent_worklog.progress import NullProgressReporter, ProgressReporter, ProgressStage
```

Extend the constructor:

```python
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
        self._progress = (
            progress if progress is not None else NullProgressReporter()
        )
```

- [ ] **Step 5: Emit discovery and per-descriptor events**

Replace `ScanService.scan` with:

```python
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
```

Do not call `finish()` in `ScanService`; the CLI owns the reporter lifecycle, and
`report` must continue using the same live line after scanning.

- [ ] **Step 6: Run scan service tests**

Run:

```bash
uv run pytest tests/integration/test_scan_service.py -v
uv run ruff check src/agent_worklog/services/scan.py tests/integration/test_scan_service.py
```

Expected: all scan tests pass and Ruff reports no findings.

- [ ] **Step 7: Commit scan progress**

```bash
git add src/agent_worklog/services/scan.py tests/integration/test_scan_service.py
git commit -m "feat: report session scan progress"
```

---

### Task 3: Emit report-generation progress

**Files:**

- Modify: `src/agent_worklog/services/report.py:11-21,45-129`
- Modify: `tests/integration/test_report_service.py:18-153`

**Interfaces:**

- Consumes: Task 1's progress contract and Task 2's `ScanService(progress=...)`.
- Produces: `ReportService(..., progress: ProgressReporter | None = None)` with absolute repository counts and non-counted finalization stages.

- [ ] **Step 1: Let the report-service test helper share one reporter**

Add these imports to `tests/integration/test_report_service.py`:

```python
from collections.abc import Callable

from agent_worklog.progress import ProgressReporter, ProgressStage
from tests.progress import RecordingProgressReporter
```

Replace the `service` helper:

```python
def service(
    source: FakeSource,
    output: Path,
    *,
    progress: ProgressReporter | None = None,
    usage_provider: Callable[[], str] | None = None,
) -> ReportService:
    return ReportService(
        scan_service=ScanService(
            source=source,
            period=period(),
            resolver=StaticResolver(),
            progress=progress,
        ),
        summarizer=RuleBasedSummarizer(),
        renderer=MarkdownRenderer(),
        period=period(),
        output_path=output,
        now_factory=lambda: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
        usage_provider=usage_provider,
        usage_days=10 if usage_provider is not None else None,
        progress=progress,
    )
```

- [ ] **Step 2: Write the failing report stage test**

Append:

```python
def test_report_emits_repository_and_output_stages(tmp_path: Path) -> None:
    progress = RecordingProgressReporter()

    service(
        FakeSource(),
        tmp_path / "report.md",
        progress=progress,
        usage_provider=lambda: "gpt-5-mini 1234 tokens",
    ).generate()

    assert progress.events == [
        ("start", ProgressStage.DISCOVERING_SESSIONS, None),
        ("start", ProgressStage.EXPORTING_SESSIONS, 3),
        ("advance", 1),
        ("advance", 2),
        ("advance", 3),
        ("start", ProgressStage.PREPARING_EVIDENCE, 1),
        ("advance", 1),
        ("start", ProgressStage.SUMMARIZING_REPOSITORIES, 1),
        ("advance", 1),
        ("start", ProgressStage.COLLECTING_USAGE, None),
        ("start", ProgressStage.RENDERING_REPORT, None),
        ("start", ProgressStage.WRITING_REPORT, None),
    ]
```

- [ ] **Step 3: Write the failing dry-run and usage-failure test**

Append:

```python
def test_report_dry_run_skips_write_after_usage_failure(tmp_path: Path) -> None:
    def failing_provider() -> str:
        raise HarnessSourceError("stats unsupported")

    progress = RecordingProgressReporter()
    result = service(
        FakeSource(),
        tmp_path / "report.md",
        progress=progress,
        usage_provider=failing_provider,
    ).generate(dry_run=True)

    started = [
        event[1]
        for event in progress.events
        if event[0] == "start"
    ]
    assert ProgressStage.COLLECTING_USAGE in started
    assert ProgressStage.RENDERING_REPORT in started
    assert ProgressStage.WRITING_REPORT not in started
    assert any("usage statistics unavailable" in warning for warning in result.warnings)
```

- [ ] **Step 4: Run the new tests and verify they fail**

Run:

```bash
uv run pytest \
  tests/integration/test_report_service.py::test_report_emits_repository_and_output_stages \
  tests/integration/test_report_service.py::test_report_dry_run_skips_write_after_usage_failure \
  -v
```

Expected: both fail because `ReportService` does not accept `progress`.

- [ ] **Step 5: Add the optional reporter to `ReportService`**

Add this import to `src/agent_worklog/services/report.py`:

```python
from agent_worklog.progress import NullProgressReporter, ProgressReporter, ProgressStage
```

Extend the constructor:

```python
    def __init__(
        self,
        *,
        scan_service: ScanService,
        summarizer: RepositorySummarizer,
        renderer: Renderer | MarkdownRenderer,
        period: DateRange,
        output_path: Path,
        now_factory: Callable[[], datetime],
        usage_provider: Callable[[], str] | None = None,
        usage_days: int | None = None,
        progress: ProgressReporter | None = None,
    ) -> None:
        self._scan_service = scan_service
        self._summarizer = summarizer
        self._renderer = renderer
        self._period = period
        self._output_path = output_path
        self._now_factory = now_factory
        self._usage_provider = usage_provider
        self._usage_days = usage_days
        self._progress = (
            progress if progress is not None else NullProgressReporter()
        )
```

- [ ] **Step 6: Count repositories while preparing evidence**

Replace `_repository_evidence` with:

```python
    def _repository_evidence(self, scan: ScanResult) -> list[RepositoryEvidence]:
        child_counts = count_child_sessions_by_repository(scan.resolved_sessions)
        repositories: list[RepositoryEvidence] = []
        self._progress.start(
            ProgressStage.PREPARING_EVIDENCE,
            total=len(scan.sessions_by_repository),
        )
        for completed, (repository_id, resolved_items) in enumerate(
            scan.sessions_by_repository.items(),
            start=1,
        ):
            first = resolved_items[0].repository
            sessions: list[SessionEvidence] = []
            branches: list[str] = []
            for resolved in resolved_items:
                extracted = extract_evidence(resolved)
                redacted = redact_value(extracted.model_dump(mode="json"))
                sessions.append(SessionEvidence.model_validate(redacted))
                branch = resolved.repository.branch
                if branch and branch not in branches:
                    branches.append(branch)
            repositories.append(
                RepositoryEvidence(
                    repository_id=repository_id,
                    display_name=first.display_name,
                    normalized_remote=first.normalized_remote,
                    branches=branches,
                    sessions=sessions,
                    child_session_count=child_counts.get(repository_id, 0),
                )
            )
            self._progress.advance(completed)
        return repositories
```

- [ ] **Step 7: Emit summary, usage, render, and write stages**

Replace `ReportService.generate` with:

```python
    def generate(
        self,
        *,
        force: bool = False,
        dry_run: bool = False,
    ) -> ReportGenerationResult:
        scan = self._scan_service.scan()
        warnings = list(scan.warnings)
        evidence_items = self._repository_evidence(scan)
        summaries: list[RepositorySummary] = []
        self._progress.start(
            ProgressStage.SUMMARIZING_REPOSITORIES,
            total=len(evidence_items),
        )
        for completed, evidence in enumerate(evidence_items, start=1):
            summaries.append(self._summarizer.summarize(evidence))
            drain_warnings = getattr(self._summarizer, "drain_warnings", None)
            if callable(drain_warnings):
                warnings.extend(cast(list[str], drain_warnings()))
            self._progress.advance(completed)
        summaries.sort(key=lambda item: item.display_name.casefold())
        usage_text: str | None = None
        if self._usage_provider is not None:
            self._progress.start(ProgressStage.COLLECTING_USAGE)
            try:
                usage_text = redact_text(self._usage_provider())
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
        self._progress.start(ProgressStage.RENDERING_REPORT)
        content = redact_text(self._renderer.render(report))
        if not dry_run:
            self._progress.start(ProgressStage.WRITING_REPORT)
            atomic_secure_write(self._output_path, content, force=force)
        return ReportGenerationResult(
            report=report,
            content=content,
            output_path=self._output_path,
            scan=scan,
        )
```

Advance summary progress only after `summarize` returns. The existing
`OpenAICompatibleSummarizer` performs retry and fallback internally, so the count
remains unchanged while a retry is in flight and advances after fallback completes.

- [ ] **Step 8: Verify fallback advances summary progress**

Replace `test_llm_failure_warning_is_written_into_report` with:

```python
def test_llm_failure_warning_is_written_into_report(tmp_path: Path) -> None:
    source = FakeSource()
    output = tmp_path / "report.md"
    progress = RecordingProgressReporter()
    report_service = ReportService(
        scan_service=ScanService(
            source=source,
            period=period(),
            resolver=StaticResolver(),
            progress=progress,
        ),
        summarizer=WarningSummarizer(),
        renderer=MarkdownRenderer(),
        period=period(),
        output_path=output,
        now_factory=lambda: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
        progress=progress,
    )

    result = report_service.generate(force=False)

    assert output.exists()
    assert any("LLM" in warning for warning in result.warnings)
    assert "LLM summary unavailable" in output.read_text()
    summary_start = progress.events.index(
        ("start", ProgressStage.SUMMARIZING_REPOSITORIES, 1)
    )
    assert progress.events[summary_start + 1] == ("advance", 1)
```

- [ ] **Step 9: Run all report-service tests**

Run:

```bash
uv run pytest tests/integration/test_report_service.py -v
uv run ruff check src/agent_worklog/services/report.py tests/integration/test_report_service.py
uv run pyright
```

Expected: all tests and static checks pass.

- [ ] **Step 10: Commit report progress**

```bash
git add src/agent_worklog/services/report.py tests/integration/test_report_service.py
git commit -m "feat: report worklog generation progress"
```

---

### Task 4: Render and clean up one Rich status line

**Files:**

- Modify: `src/agent_worklog/logging.py:1-52`
- Create: `tests/unit/test_logging.py`

**Interfaces:**

- Consumes: Task 1's `ProgressReporter`, `ProgressStage`, and `NullProgressReporter`.
- Produces: `RichProgressReporter(console: Console)` and `ConsoleReporter.progress() -> Iterator[ProgressReporter]`.

- [ ] **Step 1: Write the failing Rich rendering tests**

Create `tests/unit/test_logging.py`:

```python
from io import StringIO

import pytest
from rich.console import Console

from agent_worklog.logging import ConsoleReporter, RichProgressReporter
from agent_worklog.progress import NullProgressReporter, ProgressStage


def forced_console(stream: StringIO) -> Console:
    return Console(
        file=stream,
        force_terminal=True,
        color_system=None,
        width=100,
    )


def test_progress_renders_generic_stage_and_absolute_count_separately() -> None:
    output_stream = StringIO()
    progress_stream = StringIO()
    reporter = ConsoleReporter(
        console=forced_console(output_stream),
        progress_console=forced_console(progress_stream),
    )

    with reporter.progress() as progress:
        progress.start(ProgressStage.EXPORTING_SESSIONS, total=3)
        progress.advance(2)
    reporter.message("done")

    assert "Exporting sessions" in progress_stream.getvalue()
    assert "2/3" in progress_stream.getvalue()
    assert "done" not in progress_stream.getvalue()
    assert "done" in output_stream.getvalue()
    assert "Exporting sessions" not in output_stream.getvalue()


def test_quiet_progress_is_a_no_op() -> None:
    progress_stream = StringIO()
    reporter = ConsoleReporter(
        quiet=True,
        progress_console=forced_console(progress_stream),
    )

    with reporter.progress() as progress:
        assert isinstance(progress, NullProgressReporter)
        progress.start(ProgressStage.DISCOVERING_SESSIONS)

    assert progress_stream.getvalue() == ""


def test_progress_context_finishes_after_an_exception() -> None:
    progress_stream = StringIO()
    reporter = ConsoleReporter(
        progress_console=forced_console(progress_stream),
    )
    active: RichProgressReporter | None = None

    with pytest.raises(RuntimeError, match="boom"):
        with reporter.progress() as progress:
            assert isinstance(progress, RichProgressReporter)
            active = progress
            progress.start(ProgressStage.RENDERING_REPORT)
            raise RuntimeError("boom")

    assert active is not None
    assert active._status is None


def test_progress_context_finishes_after_keyboard_interrupt() -> None:
    progress_stream = StringIO()
    reporter = ConsoleReporter(
        progress_console=forced_console(progress_stream),
    )
    active: RichProgressReporter | None = None

    with pytest.raises(KeyboardInterrupt):
        with reporter.progress() as progress:
            assert isinstance(progress, RichProgressReporter)
            active = progress
            progress.start(ProgressStage.RENDERING_REPORT)
            raise KeyboardInterrupt

    assert active is not None
    assert active._status is None
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
uv run pytest tests/unit/test_logging.py -v
```

Expected: collection fails because `RichProgressReporter` and
`ConsoleReporter.progress` do not exist.

- [ ] **Step 3: Add stage labels and the Rich adapter**

In `src/agent_worklog/logging.py`, add:

```python
from collections.abc import Iterator
from contextlib import contextmanager

from rich.status import Status

from agent_worklog.progress import (
    NullProgressReporter,
    ProgressReporter,
    ProgressStage,
)
```

Add before `ConsoleReporter`:

```python
_STAGE_LABELS = {
    ProgressStage.DISCOVERING_SESSIONS: "Finding sessions",
    ProgressStage.EXPORTING_SESSIONS: "Exporting sessions",
    ProgressStage.PREPARING_EVIDENCE: "Preparing repository evidence",
    ProgressStage.SUMMARIZING_REPOSITORIES: "Summarizing repositories",
    ProgressStage.COLLECTING_USAGE: "Collecting usage statistics",
    ProgressStage.RENDERING_REPORT: "Rendering report",
    ProgressStage.WRITING_REPORT: "Writing report",
}


class RichProgressReporter:
    """Render one transient, continuously animated Rich status line."""

    def __init__(self, console: Console) -> None:
        self._console = console
        self._status: Status | None = None
        self._stage: ProgressStage | None = None
        self._total: int | None = None
        self._completed = 0

    def _description(self) -> str:
        assert self._stage is not None
        label = _STAGE_LABELS[self._stage]
        if self._total is None:
            return label
        return f"{label} {self._completed}/{self._total}"

    def start(
        self,
        stage: ProgressStage,
        *,
        total: int | None = None,
    ) -> None:
        self._stage = stage
        self._total = total
        self._completed = 0
        description = self._description()
        if self._status is None:
            self._status = self._console.status(description, spinner="dots")
            self._status.start()
        else:
            self._status.update(description)

    def advance(self, completed: int) -> None:
        self._completed = completed
        if self._status is not None:
            self._status.update(self._description())

    def finish(self) -> None:
        status = self._status
        self._status = None
        self._stage = None
        if status is not None:
            status.stop()
```

The label map is the only source of progress copy. It accepts no user or
repository text, which enforces the privacy constraint structurally.

- [ ] **Step 4: Add the progress console and lifecycle to `ConsoleReporter`**

Extend `ConsoleReporter.__init__`:

```python
    def __init__(
        self,
        *,
        quiet: bool = False,
        verbose: bool = False,
        console: Console | None = None,
        progress_console: Console | None = None,
    ) -> None:
        self.quiet = quiet
        self.verbose = verbose
        self.console = console or Console()
        self.progress_console = progress_console or Console(stderr=True)
```

Add this method before `message`:

```python
    @contextmanager
    def progress(self) -> Iterator[ProgressReporter]:
        progress: ProgressReporter
        if self.quiet:
            progress = NullProgressReporter()
        else:
            progress = RichProgressReporter(self.progress_console)
        try:
            yield progress
        finally:
            progress.finish()
```

- [ ] **Step 5: Run renderer tests and checks**

Run:

```bash
uv run pytest tests/unit/test_logging.py -v
uv run ruff check src/agent_worklog/logging.py tests/unit/test_logging.py
uv run pyright
```

Expected: all tests and static checks pass.

- [ ] **Step 6: Commit the Rich renderer**

```bash
git add src/agent_worklog/logging.py tests/unit/test_logging.py
git commit -m "feat: render transient CLI progress"
```

---

### Task 5: Wire one managed reporter through each CLI command

**Files:**

- Modify: `src/agent_worklog/cli.py:23-29,101-157,195-292`
- Modify: `tests/integration/test_cli.py:53-254`

**Interfaces:**

- Consumes: Tasks 2–4 service constructors and `ConsoleReporter.progress`.
- Produces: `_build_scan_service(..., *, progress: ProgressReporter | None = None)` and `_build_report_service(..., *, now: datetime, progress: ProgressReporter | None = None)`.

- [ ] **Step 1: Update CLI test doubles to accept the new builder keyword**

In `tests/integration/test_cli.py`, update every monkeypatched
`_build_scan_service` function or lambda to accept:

```python
*, progress=None
```

Update every monkeypatched `_build_report_service` function or lambda to accept:

```python
*, now, progress=None
```

Confirm all call sites were updated:

```bash
rg -n "_build_scan_service|_build_report_service" tests/integration/test_cli.py
```

- [ ] **Step 2: Extend the existing root-only tests to require progress propagation**

In `test_report_passes_root_only_to_the_report_service`, change `captured` and
`build` to:

```python
    captured: dict[str, object] = {}

    def build(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        progress=None,
    ):
        captured["root_only"] = root_only
        captured["progress"] = progress
        return StubReportService(output_path, period)
```

Then add:

```python
    assert captured["progress"] is not None
```

In `test_scan_passes_root_only_to_the_scan_service`, change `captured` and
`build` to:

```python
    captured: dict[str, object] = {}

    def build(settings, period, root_only=False, *, progress=None):
        captured["root_only"] = root_only
        captured["progress"] = progress
        return StubScanService()
```

Then add:

```python
    assert captured["progress"] is not None
```

- [ ] **Step 3: Add the failing quiet-mode propagation test**

Add this import:

```python
from agent_worklog.progress import NullProgressReporter, ProgressStage
```

Append:

```python
def test_quiet_scan_passes_a_null_progress_reporter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class StubScanService:
        def scan(self):
            return SimpleNamespace(
                loaded_session_count=1,
                sessions_by_repository={},
                warnings=[],
            )

    def build(settings, period, root_only=False, *, progress=None):
        captured["progress"] = progress
        return StubScanService()

    monkeypatch.setattr(cli, "_build_scan_service", build)

    result = runner.invoke(cli.app, ["scan", "--days", "7", "--quiet"])

    assert result.exit_code == 0
    assert isinstance(captured["progress"], NullProgressReporter)
    assert result.stdout.strip() == "1"
```

- [ ] **Step 4: Add the failing dry-run stream test**

Add these imports:

```python
import sys

from rich.console import Console
```

Append:

```python
def test_dry_run_keeps_progress_out_of_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_console_reporter = cli.ConsoleReporter

    def build_reporter(**kwargs):
        return original_console_reporter(
            **kwargs,
            progress_console=Console(
                file=sys.stderr,
                force_terminal=True,
                color_system=None,
            ),
        )

    class ProgressReportService(StubReportService):
        def __init__(self, output_path, period, progress) -> None:
            super().__init__(output_path, period)
            self.progress = progress

        def generate(self, *, force: bool = False, dry_run: bool = False):
            self.progress.start(ProgressStage.RENDERING_REPORT)
            return super().generate(force=force, dry_run=dry_run)

    def build(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        progress=None,
    ):
        return ProgressReportService(output_path, period, progress)

    monkeypatch.setattr(cli, "ConsoleReporter", build_reporter)
    monkeypatch.setattr(cli, "_build_report_service", build)

    result = runner.invoke(
        cli.app,
        [
            "report",
            "--days",
            "7",
            "--dry-run",
            "--output",
            str(tmp_path / "report.md"),
        ],
    )

    assert result.exit_code == 0
    assert "# Engineering Worklog" in result.stdout
    assert "Rendering report" not in result.stdout
    assert "Rendering report" in result.stderr
```

- [ ] **Step 5: Run the new CLI tests and verify they fail**

Run:

```bash
uv run pytest \
  tests/integration/test_cli.py::test_quiet_scan_passes_a_null_progress_reporter \
  tests/integration/test_cli.py::test_dry_run_keeps_progress_out_of_stdout \
  -v
```

Expected: tests fail because commands do not open `ConsoleReporter.progress()` or
pass its reporter to builders.

- [ ] **Step 6: Thread the reporter through service builders**

Add this import to `src/agent_worklog/cli.py`:

```python
from agent_worklog.progress import ProgressReporter
```

Update `_build_scan_service`:

```python
def _build_scan_service(
    settings: AppSettings,
    period: DateRange,
    root_only: bool = False,
    *,
    progress: ProgressReporter | None = None,
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
        progress=progress,
    )
```

Add `progress` to `_build_report_service` after `now`:

```python
    *,
    now: datetime,
    progress: ProgressReporter | None = None,
) -> ReportService:
```

Then update its returned `ReportService`:

```python
    return ReportService(
        scan_service=_build_scan_service(
            settings,
            period,
            root_only,
            progress=progress,
        ),
        summarizer=summarizer,
        renderer=MarkdownRenderer(),
        period=period,
        output_path=output_path,
        now_factory=lambda: now,
        usage_provider=lambda: collect_usage_stats(
            runner=stats_runner,
            executable=cli_settings.executable,
            days=days,
        ),
        usage_days=days,
        progress=progress,
    )
```

- [ ] **Step 7: Manage progress around the `scan` service call**

In `scan`, replace the direct service call and no-session check with:

```python
        with reporter.progress() as progress:
            result = _build_scan_service(
                settings,
                selected_period,
                root_only,
                progress=progress,
            ).scan()
            if result.loaded_session_count == 0:
                raise NoSessionsError(
                    "no OpenCode activity found in the requested period"
                )
```

Keep the context inside the existing `try`. This guarantees cleanup before all
existing `except` blocks print their errors.

- [ ] **Step 8: Manage progress around the `report` service call**

In `report`, replace service construction, generation, and the no-session check:

```python
        with reporter.progress() as progress:
            service = _build_report_service(
                settings,
                selected_period,
                output_path,
                no_llm,
                root_only,
                now=now,
                progress=progress,
            )
            result = service.generate(force=force, dry_run=dry_run)
            if not result.report.repositories:
                raise NoSessionsError(
                    "no OpenCode activity found in the requested period"
                )
```

Leave final dry-run, quiet, normal, and verbose output after the `try` block so
the live line is already gone.

- [ ] **Step 9: Run the complete CLI and end-to-end suites**

Run:

```bash
uv run pytest tests/integration/test_cli.py tests/integration/test_end_to_end.py -v
uv run ruff check src/agent_worklog/cli.py tests/integration/test_cli.py
uv run pyright
```

Expected: all tests and static checks pass. Existing output assertions and exit
codes remain unchanged.

- [ ] **Step 10: Commit CLI wiring**

```bash
git add src/agent_worklog/cli.py tests/integration/test_cli.py
git commit -m "feat: show progress in scan and report commands"
```

---

### Task 6: Document progress behavior and run release gates

**Files:**

- Modify: `README.md:90-126`
- Modify: `README.zh-TW.md:87-122`
- Modify: `tests/unit/test_documentation.py:1-10`

**Interfaces:**

- Consumes: the completed CLI behavior from Tasks 1–5.
- Produces: user-facing English and Traditional Chinese documentation with test coverage.

- [ ] **Step 1: Write the failing documentation test**

Append to `tests/unit/test_documentation.py`:

```python
def test_readmes_document_interactive_progress() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh_tw = Path("README.zh-TW.md").read_text(encoding="utf-8")

    assert "transient progress status" in readme
    assert "`--quiet` hides the progress status" in readme
    assert "暫時性的進度狀態" in readme_zh_tw
    assert "`--quiet` 會隱藏進度狀態" in readme_zh_tw
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
uv run pytest tests/unit/test_documentation.py -v
```

Expected: `test_readmes_document_interactive_progress` fails on all four assertions.

- [ ] **Step 3: Document progress in English**

In `README.md`, after the `scan` and `report` shared-options table, add:

```markdown
While `scan` and `report` are working, they show a transient progress status with the
current stage. Session and repository stages also show a `completed/total` count.
`--quiet` hides the progress status. For `report --dry-run`, progress is written to
stderr so stdout contains only Markdown.
```

- [ ] **Step 4: Document progress in Traditional Chinese**

In `README.zh-TW.md`, after the `scan` and `report` shared-options table, add:

```markdown
`scan` 與 `report` 執行時會顯示暫時性的進度狀態，指出目前所在階段。處理工作階段與
repository 時也會顯示 `已完成數/總數`。`--quiet` 會隱藏進度狀態。使用
`report --dry-run` 時，進度會寫入 stderr，stdout 只會包含 Markdown。
```

- [ ] **Step 5: Run documentation and focused feature tests**

Run:

```bash
uv run pytest \
  tests/unit/test_documentation.py \
  tests/unit/test_progress.py \
  tests/unit/test_logging.py \
  tests/integration/test_scan_service.py \
  tests/integration/test_report_service.py \
  tests/integration/test_cli.py \
  -v
```

Expected: all focused tests pass.

- [ ] **Step 6: Run all release gates**

Run:

```bash
uv run pytest --cov=agent_worklog --cov-fail-under=80
uv run ruff check .
uv run pyright
uv build
git diff --check
```

Expected: the full suite passes, coverage is at least 80%, Ruff and Pyright
report no findings, the package builds successfully, and `git diff --check`
prints nothing.

- [ ] **Step 7: Commit documentation**

```bash
git add README.md README.zh-TW.md tests/unit/test_documentation.py
git commit -m "docs: explain interactive CLI progress"
```

---

## Final Verification

Review the implementation against
`docs/superpowers/specs/2026-07-30-cli-progress-feedback-design.md`, then run:

```bash
uv run pytest --cov=agent_worklog --cov-fail-under=80
uv run ruff check .
uv run pyright
uv build
git status --short
```

Expected:

- All tests pass with at least 80% coverage.
- Ruff and Pyright report no findings.
- The wheel and source distribution build successfully.
- Only intentionally uncommitted files appear in `git status --short`.
- `scan` and `report` share one transient progress line.
- `--quiet` produces no progress, and `--dry-run` stdout contains only Markdown.
