# Agent Worklog MVP Implementation Plan

**Goal:** Build a Python CLI that queries OpenCode sessions across all projects for a requested period, assigns each session to a canonical Git repository, extracts safe evidence, and produces a Markdown engineering worklog with optional LLM summarization.

**Architecture:** The MVP uses an OpenCode CLI-first adapter: `opencode db` discovers candidate sessions and `opencode export --sanitize` loads transcripts. Provider output is normalized into canonical models, repository identity is resolved before parent/child relationships are aggregated, evidence retains provenance, and report generation stays independent of OpenCode-specific schemas. Direct SQLite access, JSON output, `inspect`, Codex, and Claude Code are deliberately outside the first release gate.

**Tech Stack:** Python 3.11+, Typer, Pydantic 2, pydantic-settings, Rich, Jinja2, httpx, platformdirs, PyYAML, pytest, pytest-cov, Ruff, Pyright, Hatchling, uv.

## Global Constraints

- Product name: `Agent Worklog`.
- PyPI distribution and CLI: `agent-worklog`; Python package: `agent_worklog`.
- Minimum Python version: `3.11`.
- Primary supported harness: OpenCode.
- OpenCode access is CLI-first through `opencode db` and `opencode export --sanitize`.
- Session discovery must include all OpenCode projects and must not depend on the process current working directory.
- Candidate sessions use interval-overlap filtering: `created_at < until` and `updated_at >= since`; activity timestamps perform the final exact filter.
- Date intervals are half-open: `since <= timestamp < until`.
- Default timezone: `Asia/Taipei`.
- Project grouping uses normalized Git origin first, Git common directory second, harness project ID third, normalized path fourth, and a per-session unknown identity last.
- Repository resolution happens before parent/child aggregation; a child session in another repository must remain in that repository.
- Evidence must retain source activity IDs, extraction method, and confidence.
- Full transcripts must never be sent to an external LLM.
- Sanitized temporary exports are deleted by default; temporary directories use mode `0700`, and report files use mode `0600` where supported.
- A single failed session export is a warning; all exports failing is an error.
- Existing report files are not overwritten unless `--force` is supplied.
- MVP report output is Markdown. JSON output and direct SQLite access are post-MVP.
- No live LLM calls in CI.
- Each task follows test-driven development and ends with an intentional commit.

---

## Release Stages

| Stage | Outcome | Release gate |
|---|---|---|
| Phase 1 | Installable CLI foundation | `agent-worklog --help` and date-range tests pass |
| Phase 2 | OpenCode cross-project discovery and sanitized export | `scan` finds sessions independent of current directory |
| Phase 3 | Canonical Git repository grouping | worktrees merge; different repository owners do not |
| Phase 4 | Provenance-aware evidence and secure handling | redacted evidence is safe to render or send to an LLM |
| Phase 5 | Deterministic Markdown worklog | `report --no-llm` produces a useful file |
| Phase 6 | Optional LLM summaries with fallback | LLM failure still produces a deterministic report |
| Phase 7 | Release hardening | package installs via `pipx`; end-to-end acceptance suite passes |

---

## File Structure

```text
agent-worklog/
├── pyproject.toml
├── README.md
├── LICENSE
├── CHANGELOG.md
├── src/
│   └── agent_worklog/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── errors.py
│       ├── logging.py
│       ├── models/
│       │   ├── __init__.py
│       │   ├── time_range.py
│       │   ├── session.py
│       │   ├── repository.py
│       │   ├── evidence.py
│       │   └── report.py
│       ├── harnesses/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   └── opencode/
│       │       ├── __init__.py
│       │       ├── cli_runner.py
│       │       ├── source.py
│       │       └── mapper.py
│       ├── repositories/
│       │   ├── __init__.py
│       │   ├── remote.py
│       │   └── resolver.py
│       ├── sessions/
│       │   ├── __init__.py
│       │   ├── filtering.py
│       │   └── hierarchy.py
│       ├── extraction/
│       │   ├── __init__.py
│       │   ├── pipeline.py
│       │   └── rules.py
│       ├── security/
│       │   ├── __init__.py
│       │   ├── redactor.py
│       │   └── secure_files.py
│       ├── summarizers/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── rule_based.py
│       │   └── openai_compatible.py
│       ├── renderers/
│       │   ├── __init__.py
│       │   └── markdown.py
│       ├── services/
│       │   ├── __init__.py
│       │   ├── doctor.py
│       │   ├── scan.py
│       │   └── report.py
│       └── templates/
│           └── worklog.md.j2
└── tests/
    ├── fixtures/
    │   └── opencode/
    │       ├── db-response.json
    │       ├── export-root.json
    │       ├── export-child.json
    │       ├── export-cross-repo-child.json
    │       └── export-secret.json
    ├── conftest.py
    ├── unit/
    └── integration/
```

Responsibilities are intentionally narrow:

- `harnesses/opencode/*` knows OpenCode CLI syntax and export shapes only.
- `repositories/*` knows Git identity only.
- `sessions/*` handles timestamps and parent/child relationships only.
- `extraction/*` converts canonical activities into evidence only.
- `security/*` removes secrets and manages local file permissions only.
- `summarizers/*` converts evidence into report summaries only.
- `renderers/*` converts report models into Markdown only.
- `services/*` orchestrates use cases without parsing provider payloads.

---

## Phase 1 — CLI and Domain Foundation

### Task 1: Package Skeleton and Quality Tooling

**Files:**
- Create: `pyproject.toml`
- Create: `src/agent_worklog/__init__.py`
- Create: `src/agent_worklog/cli.py`
- Create: `src/agent_worklog/errors.py`
- Create: `tests/unit/test_cli.py`
- Create: `README.md`
- Create: `CHANGELOG.md`
- Create: `LICENSE`

**Interfaces:**
- Consumes: none.
- Produces: Typer application `agent_worklog.cli.app`; package constant `agent_worklog.__version__`.

- [ ] **Step 1: Write the failing CLI smoke test**

```python
from typer.testing import CliRunner

from agent_worklog.cli import app

runner = CliRunner()


def test_help_lists_core_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "doctor" in result.stdout
    assert "scan" in result.stdout
    assert "report" in result.stdout
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/unit/test_cli.py::test_help_lists_core_commands -v
```

Expected: collection fails because `agent_worklog.cli` does not exist.

- [ ] **Step 3: Create package metadata and minimal CLI**

Use this dependency and tooling configuration in `pyproject.toml`:

```toml
[project]
name = "agent-worklog"
version = "0.1.0a1"
description = "Turn coding-agent sessions into repository-based engineering reports"
requires-python = ">=3.11"
dependencies = [
  "httpx>=0.28,<1",
  "Jinja2>=3.1,<4",
  "platformdirs>=4,<5",
  "pydantic>=2.10,<3",
  "pydantic-settings>=2.7,<3",
  "PyYAML>=6,<7",
  "rich>=14,<15",
  "typer>=0.16,<1",
]

[project.optional-dependencies]
dev = [
  "pyright>=1.1.400",
  "pytest>=8.3",
  "pytest-cov>=6",
  "ruff>=0.12",
]

[project.scripts]
agent-worklog = "agent_worklog.cli:app"

[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
addopts = "-ra"
testpaths = ["tests"]

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.pyright]
pythonVersion = "3.11"
typeCheckingMode = "strict"
include = ["src", "tests"]
```

Implement `src/agent_worklog/__init__.py`:

```python
__version__ = "0.1.0a1"
```

Implement `src/agent_worklog/errors.py`:

```python
class AgentWorklogError(Exception):
    """Base class for expected application failures."""


class ConfigurationError(AgentWorklogError):
    pass


class HarnessSourceError(AgentWorklogError):
    pass


class SessionParseError(HarnessSourceError):
    pass


class ReportOutputError(AgentWorklogError):
    pass
```

Implement `src/agent_worklog/cli.py`:

```python
import typer

app = typer.Typer(
    no_args_is_help=True,
    help="Turn coding-agent sessions into repository-based engineering reports.",
)


@app.command()
def doctor() -> None:
    """Validate OpenCode and Git dependencies."""


@app.command()
def scan() -> None:
    """Find OpenCode sessions and group them by Git repository."""


@app.command()
def report() -> None:
    """Generate a Markdown engineering worklog."""
```

- [ ] **Step 4: Run quality checks**

```bash
uv sync --extra dev
uv run pytest tests/unit/test_cli.py -v
uv run ruff check .
uv run pyright
```

Expected: all commands pass.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src tests README.md CHANGELOG.md LICENSE
git commit -m "chore: bootstrap agent worklog package"
```

---

### Task 2: Configuration and Date-Range Contract

**Files:**
- Create: `src/agent_worklog/config.py`
- Create: `src/agent_worklog/models/__init__.py`
- Create: `src/agent_worklog/models/time_range.py`
- Create: `tests/unit/test_config.py`
- Create: `tests/unit/models/test_time_range.py`

**Interfaces:**
- Consumes: none.
- Produces: `AppSettings`, `DateRange`, `DateRange.from_days()`, `DateRange.previous_week()`.

- [ ] **Step 1: Write failing date-range tests**

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from agent_worklog.models.time_range import DateRange

TZ = ZoneInfo("Asia/Taipei")


def test_from_days_returns_half_open_range() -> None:
    now = datetime(2026, 7, 29, 20, 0, tzinfo=TZ)

    period = DateRange.from_days(days=7, now=now)

    assert period.since == datetime(2026, 7, 22, 20, 0, tzinfo=TZ)
    assert period.until == now


def test_previous_week_is_monday_to_monday() -> None:
    now = datetime(2026, 7, 29, 20, 0, tzinfo=TZ)

    period = DateRange.previous_week(now=now)

    assert period.since == datetime(2026, 7, 20, 0, 0, tzinfo=TZ)
    assert period.until == datetime(2026, 7, 27, 0, 0, tzinfo=TZ)
```

- [ ] **Step 2: Run the tests to verify failure**

```bash
uv run pytest tests/unit/models/test_time_range.py -v
```

Expected: import failure for `DateRange`.

- [ ] **Step 3: Implement exact date semantics and settings**

Implement `DateRange`:

```python
from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, model_validator


class DateRange(BaseModel):
    since: datetime
    until: datetime

    @model_validator(mode="after")
    def validate_order(self) -> "DateRange":
        if self.since.tzinfo is None or self.until.tzinfo is None:
            raise ValueError("date range values must be timezone-aware")
        if self.since >= self.until:
            raise ValueError("since must be earlier than until")
        return self

    @classmethod
    def from_days(cls, *, days: int, now: datetime) -> "DateRange":
        if days < 1:
            raise ValueError("days must be at least 1")
        return cls(since=now - timedelta(days=days), until=now)

    @classmethod
    def previous_week(cls, *, now: datetime) -> "DateRange":
        current_monday = (now - timedelta(days=now.weekday())).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        return cls(
            since=current_monday - timedelta(days=7),
            until=current_monday,
        )
```

Implement `AppSettings` with one canonical `harnesses` key:

```python
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OpenCodeCliSettings(BaseModel):
    executable: str = "opencode"
    timeout_seconds: float = 30.0


class OpenCodeSettings(BaseModel):
    enabled: bool = True
    source: str = "cli"
    cli: OpenCodeCliSettings = Field(default_factory=OpenCodeCliSettings)


class HarnessSettings(BaseModel):
    opencode: OpenCodeSettings = Field(default_factory=OpenCodeSettings)


class ReportSettings(BaseModel):
    timezone: str = "Asia/Taipei"
    output_directory: Path = Path("reports")


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENT_WORKLOG_",
        env_nested_delimiter="__",
    )

    harnesses: HarnessSettings = Field(default_factory=HarnessSettings)
    report: ReportSettings = Field(default_factory=ReportSettings)
```

- [ ] **Step 4: Run tests and static checks**

```bash
uv run pytest tests/unit/test_config.py tests/unit/models/test_time_range.py -v
uv run ruff check .
uv run pyright
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_worklog/config.py src/agent_worklog/models tests/unit
git commit -m "feat: define configuration and report periods"
```

---

### Task 3: Canonical Session, Repository, Evidence, and Report Models

**Files:**
- Create: `src/agent_worklog/models/session.py`
- Create: `src/agent_worklog/models/repository.py`
- Create: `src/agent_worklog/models/evidence.py`
- Create: `src/agent_worklog/models/report.py`
- Create: `tests/unit/models/test_models.py`

**Interfaces:**
- Consumes: `DateRange`.
- Produces: `SessionDescriptor`, `SessionActivity`, `AgentSession`, `ResolvedSession`, `RepositoryIdentity`, `EvidenceItem`, `SessionEvidence`, `RepositoryEvidence`, `RepositorySummary`, `WorklogReport`.

- [ ] **Step 1: Write failing provenance and unknown-usage tests**

```python
from agent_worklog.models.evidence import EvidenceConfidence, EvidenceItem
from agent_worklog.models.session import TokenUsage, UsageSemantics


def test_evidence_requires_provenance() -> None:
    item = EvidenceItem(
        text="Tests passed",
        source_activity_ids=["activity-1"],
        confidence=EvidenceConfidence.HIGH,
        extraction_method="successful_test_command",
    )

    assert item.source_activity_ids == ["activity-1"]


def test_unknown_token_usage_is_not_zero() -> None:
    usage = TokenUsage(semantics=UsageSemantics.UNKNOWN)

    assert usage.input_tokens is None
    assert usage.output_tokens is None
```

- [ ] **Step 2: Run the tests to verify failure**

```bash
uv run pytest tests/unit/models/test_models.py -v
```

Expected: import failure for the model modules.

- [ ] **Step 3: Implement canonical models**

Use these exact public contracts:

```python
# models/session.py
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ActivityType(StrEnum):
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    COMMAND = "command"
    FILE_CHANGE = "file_change"
    ERROR = "error"
    SYSTEM = "system"


class UsageSemantics(StrEnum):
    INCREMENTAL = "incremental"
    CUMULATIVE = "cumulative"
    UNKNOWN = "unknown"


class TokenUsage(BaseModel):
    semantics: UsageSemantics = UsageSemantics.UNKNOWN
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None


class SessionDescriptor(BaseModel):
    harness: str
    session_id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    working_directory_hint: str | None = None
    project_id_hint: str | None = None
    parent_session_id: str | None = None


class SessionActivity(BaseModel):
    activity_id: str
    activity_type: ActivityType
    timestamp: datetime | None = None
    content: str = ""
    tool_name: str | None = None
    tool_call_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class AgentSession(BaseModel):
    harness: str
    session_id: str
    parent_session_id: str | None = None
    title: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    working_directory: str | None = None
    project_id_hint: str | None = None
    activities: list[SessionActivity] = Field(default_factory=list)
    token_usage: TokenUsage | None = None
```

```python
# models/repository.py
from enum import StrEnum

from pydantic import BaseModel, Field

from agent_worklog.models.session import AgentSession


class RepositoryIdentityType(StrEnum):
    GIT_REMOTE = "git_remote"
    GIT_COMMON_DIR = "git_common_dir"
    HARNESS_PROJECT = "harness_project"
    PATH_FALLBACK = "path_fallback"
    UNKNOWN = "unknown"


class RepositoryIdentity(BaseModel):
    repository_id: str
    display_name: str
    identity_type: RepositoryIdentityType
    normalized_remote: str | None = None
    branch: str | None = None
    working_directory: str | None = None
    resolution_method: str


class ResolvedSession(BaseModel):
    session: AgentSession
    repository: RepositoryIdentity
```

```python
# models/evidence.py
from enum import StrEnum

from pydantic import BaseModel, Field


class EvidenceConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EvidenceStatus(StrEnum):
    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class EvidenceItem(BaseModel):
    text: str
    source_activity_ids: list[str]
    confidence: EvidenceConfidence
    extraction_method: str
    status: EvidenceStatus = EvidenceStatus.UNKNOWN


class SessionEvidence(BaseModel):
    session_id: str
    repository_id: str
    goals: list[EvidenceItem] = Field(default_factory=list)
    commands: list[EvidenceItem] = Field(default_factory=list)
    files_changed: list[EvidenceItem] = Field(default_factory=list)
    errors: list[EvidenceItem] = Field(default_factory=list)
    outcomes: list[EvidenceItem] = Field(default_factory=list)


class RepositoryEvidence(BaseModel):
    repository_id: str
    display_name: str
    normalized_remote: str | None = None
    branches: list[str] = Field(default_factory=list)
    sessions: list[SessionEvidence] = Field(default_factory=list)
    child_session_count: int = 0
```

```python
# models/report.py
from datetime import datetime

from pydantic import BaseModel, Field

from agent_worklog.models.time_range import DateRange


class RepositorySummary(BaseModel):
    repository_id: str
    display_name: str
    normalized_remote: str | None = None
    summary: str = ""
    completed: list[str] = Field(default_factory=list)
    problems_resolved: list[str] = Field(default_factory=list)
    in_progress: list[str] = Field(default_factory=list)
    key_files: list[str] = Field(default_factory=list)
    session_count: int = 0
    child_session_count: int = 0
    branches: list[str] = Field(default_factory=list)


class WorklogReport(BaseModel):
    schema_version: str = "1"
    generated_at: datetime
    period: DateRange
    repositories: list[RepositorySummary]
    warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run tests and type checks**

```bash
uv run pytest tests/unit/models -v
uv run ruff check .
uv run pyright
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_worklog/models tests/unit/models
git commit -m "feat: add canonical worklog domain models"
```

---

## Phase 2 — OpenCode CLI Source

### Task 4: Safe External Command Runner and Doctor Checks

**Files:**
- Create: `src/agent_worklog/harnesses/__init__.py`
- Create: `src/agent_worklog/harnesses/base.py`
- Create: `src/agent_worklog/harnesses/opencode/__init__.py`
- Create: `src/agent_worklog/harnesses/opencode/cli_runner.py`
- Create: `src/agent_worklog/services/__init__.py`
- Create: `src/agent_worklog/services/doctor.py`
- Create: `tests/conftest.py`
- Create: `tests/unit/harnesses/opencode/test_cli_runner.py`
- Create: `tests/unit/services/test_doctor.py`

**Interfaces:**
- Consumes: `AppSettings`.
- Produces: `CommandResult`, `CommandRunner.run()`, `DoctorResult`, `run_doctor()`.

- [ ] **Step 1: Write failing command-runner tests**

```python
from agent_worklog.harnesses.opencode.cli_runner import CommandRunner


def test_runner_disables_interactive_git_and_uses_argument_list() -> None:
    runner = CommandRunner(timeout_seconds=1)

    result = runner.run(["python", "-c", "print('ok')"])

    assert result.returncode == 0
    assert result.stdout.strip() == "ok"
```

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/unit/harnesses/opencode/test_cli_runner.py -v
```

Expected: import failure.

- [ ] **Step 3: Implement the runner and doctor contract**

```python
from dataclasses import dataclass
import os
import subprocess


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    def __init__(self, *, timeout_seconds: float) -> None:
        self._timeout_seconds = timeout_seconds

    def run(self, args: list[str]) -> CommandResult:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=self._timeout_seconds,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        return CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
```

Define the harness interface in `harnesses/base.py`:

```python
from abc import ABC, abstractmethod

from agent_worklog.models.session import AgentSession, SessionDescriptor
from agent_worklog.models.time_range import DateRange


class HarnessSessionSource(ABC):
    @abstractmethod
    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        raise NotImplementedError

    @abstractmethod
    def load(self, descriptor: SessionDescriptor) -> AgentSession:
        raise NotImplementedError
```

Create a reusable fake in `tests/conftest.py`:

```python
from dataclasses import dataclass, field

import pytest

from agent_worklog.harnesses.opencode.cli_runner import CommandResult


@dataclass
class FakeCommandRunner:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    calls: list[list[str]] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)

    def set_output(self, command_suffix: str, output: str) -> None:
        self.outputs[command_suffix] = output

    def run(self, args: list[str]) -> CommandResult:
        self.calls.append(args)
        joined = " ".join(args)
        stdout = next(
            (value for suffix, value in self.outputs.items() if joined.endswith(suffix)),
            self.stdout,
        )
        return CommandResult(self.returncode, stdout, self.stderr)


@pytest.fixture
def fake_runner() -> FakeCommandRunner:
    return FakeCommandRunner()


@pytest.fixture
def fake_git_runner() -> FakeCommandRunner:
    return FakeCommandRunner()
```

`run_doctor()` must check these exact commands:

```text
opencode --version
opencode db path
git --version
```

It must never print environment variable values or credentials.

- [ ] **Step 4: Run focused and full tests**

```bash
uv run pytest tests/unit/harnesses/opencode/test_cli_runner.py tests/unit/services/test_doctor.py -v
uv run pytest -q
uv run ruff check .
uv run pyright
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_worklog/harnesses src/agent_worklog/services tests/unit
git commit -m "feat: add safe command runner and environment doctor"
```

---

### Task 5: Cross-Project Candidate Discovery with Interval Overlap

**Files:**
- Create: `src/agent_worklog/harnesses/opencode/source.py`
- Create: `tests/fixtures/opencode/db-response.json`
- Create: `tests/unit/harnesses/opencode/test_source_discovery.py`

**Interfaces:**
- Consumes: `CommandRunner`, `DateRange`, `SessionDescriptor`.
- Produces: `OpenCodeCliSource.discover(period: DateRange) -> list[SessionDescriptor]`.

- [ ] **Step 1: Write failing discovery tests**

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from agent_worklog.harnesses.opencode.source import OpenCodeCliSource
from agent_worklog.models.time_range import DateRange

TZ = ZoneInfo("Asia/Taipei")


def test_discovery_uses_interval_overlap_and_no_project_filter(fake_runner) -> None:
    fake_runner.stdout = '[{"id":"s1","time_created":1,"time_updated":2}]'
    source = OpenCodeCliSource(runner=fake_runner, executable="opencode")
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )

    source.discover(period)

    query = fake_runner.calls[0][2]
    assert "time_created <" in query
    assert "COALESCE(time_updated, time_created, 0) >=" in query
    assert "project_id =" not in query
    assert "directory =" not in query
```

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/unit/harnesses/opencode/test_source_discovery.py -v
```

Expected: import failure.

- [ ] **Step 3: Implement discovery**

Use this SQL shape, converting the timezone-aware period to Unix milliseconds:

```sql
SELECT
  id,
  project_id,
  parent_id,
  directory,
  title,
  time_created,
  time_updated
FROM session
WHERE time_created < :until_ms
  AND COALESCE(time_updated, time_created, 0) >= :since_ms
ORDER BY COALESCE(time_updated, time_created, 0) DESC;
```

Execute it as:

```python
result = self._runner.run(
    [self._executable, "db", query, "--format", "json"]
)
```

Accept OpenCode JSON responses in any of these shapes:

```json
[]
```

```json
{"data": []}
```

```json
{"rows": []}
```

Map `time_created` and `time_updated` from milliseconds to UTC-aware datetimes. Raise `HarnessSourceError` when the command fails or the response is invalid JSON.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/harnesses/opencode/test_source_discovery.py -v
uv run pytest -q
uv run ruff check .
uv run pyright
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_worklog/harnesses/opencode/source.py tests
git commit -m "feat: discover opencode sessions across all projects"
```

---

### Task 6: Sanitized Session Export and Canonical Mapping

**Files:**
- Create: `src/agent_worklog/harnesses/opencode/mapper.py`
- Create: `tests/fixtures/opencode/export-root.json`
- Create: `tests/fixtures/opencode/export-secret.json`
- Create: `tests/unit/harnesses/opencode/test_mapper.py`
- Modify: `src/agent_worklog/harnesses/opencode/source.py`

**Interfaces:**
- Consumes: `SessionDescriptor`, `CommandRunner`.
- Produces: `OpenCodeCliSource.load(descriptor) -> AgentSession`; `OpenCodeExportMapper.map()`.

- [ ] **Step 1: Write failing export tests**

```python
from agent_worklog.harnesses.opencode.source import OpenCodeCliSource
from agent_worklog.models.session import SessionDescriptor


def test_load_uses_sanitize_flag(fake_runner) -> None:
    fake_runner.stdout = '{"messages": []}'
    source = OpenCodeCliSource(runner=fake_runner, executable="opencode")

    source.load(SessionDescriptor(harness="opencode", session_id="s1"))

    assert fake_runner.calls[0] == ["opencode", "export", "s1", "--sanitize"]
```

Add a mapper test asserting text parts become `SessionActivity` records with stable IDs derived from message ID plus part index.

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/unit/harnesses/opencode/test_mapper.py -v
```

Expected: import or attribute failure.

- [ ] **Step 3: Implement sanitized loading and flexible mapping**

The mapper must support:

- message role from `message.info.role` or `message.role`;
- message timestamps from `info.time.created`, `info.time.completed`, `time_created`, or descriptor timestamps;
- text from `parts[*].text` where `type == "text"`;
- tool calls from parts where `type == "tool"`;
- token usage only when the export exposes unambiguous incremental fields; otherwise use `UsageSemantics.UNKNOWN`.

The source must treat a single failed export as `SessionParseError`. Higher-level services decide whether to continue.

- [ ] **Step 4: Run provider tests**

```bash
uv run pytest tests/unit/harnesses/opencode -v
uv run pytest -q
uv run ruff check .
uv run pyright
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_worklog/harnesses/opencode tests/fixtures/opencode tests/unit/harnesses
git commit -m "feat: export and normalize sanitized opencode sessions"
```

---

### Task 7: Exact Activity Filtering

**Files:**
- Create: `src/agent_worklog/sessions/filtering.py`
- Create: `tests/unit/sessions/test_filtering.py`

**Interfaces:**
- Consumes: `AgentSession`, `DateRange`.
- Produces: `filter_session_to_period(session, period) -> AgentSession | None`.

- [ ] **Step 1: Write failing exact-filter tests**

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from agent_worklog.models.session import ActivityType, AgentSession, SessionActivity
from agent_worklog.models.time_range import DateRange
from agent_worklog.sessions.filtering import filter_session_to_period

TZ = ZoneInfo("Asia/Taipei")


def test_old_session_with_in_range_activity_is_included() -> None:
    session = AgentSession(
        harness="opencode",
        session_id="s1",
        created_at=datetime(2026, 7, 1, tzinfo=TZ),
        activities=[
            SessionActivity(
                activity_id="a1",
                activity_type=ActivityType.USER_MESSAGE,
                timestamp=datetime(2026, 7, 22, tzinfo=TZ),
                content="implement report",
            )
        ],
    )
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )

    filtered = filter_session_to_period(session, period)

    assert filtered is not None
    assert [item.activity_id for item in filtered.activities] == ["a1"]
```

Add a test proving an activity exactly at `until` is excluded.

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/unit/sessions/test_filtering.py -v
```

Expected: import failure.

- [ ] **Step 3: Implement half-open filtering**

```python
from copy import deepcopy

from agent_worklog.models.session import AgentSession
from agent_worklog.models.time_range import DateRange


def filter_session_to_period(
    session: AgentSession,
    period: DateRange,
) -> AgentSession | None:
    activities = [
        activity
        for activity in session.activities
        if activity.timestamp is not None
        and period.since <= activity.timestamp < period.until
    ]
    if not activities:
        return None
    filtered = deepcopy(session)
    filtered.activities = activities
    return filtered
```

Activities with no usable timestamp are excluded and counted as warnings by the report service.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/sessions/test_filtering.py -v
uv run pytest -q
uv run ruff check .
uv run pyright
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_worklog/sessions tests/unit/sessions
git commit -m "feat: filter session activities by exact report period"
```

---

## Phase 3 — Git Repository Resolution and Session Relationships

### Task 8: Git Remote Normalization

**Files:**
- Create: `src/agent_worklog/repositories/remote.py`
- Create: `tests/unit/repositories/test_remote.py`

**Interfaces:**
- Consumes: raw Git remote strings.
- Produces: `normalize_git_remote(remote: str) -> str`; `repository_display_name(identity: str) -> str`.

- [ ] **Step 1: Write failing normalization tests**

```python
import pytest

from agent_worklog.repositories.remote import normalize_git_remote


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("git@github.com:mike/assets-tracker.git", "github.com/mike/assets-tracker"),
        ("https://github.com/mike/assets-tracker.git", "github.com/mike/assets-tracker"),
        ("ssh://git@github.com/mike/assets-tracker.git", "github.com/mike/assets-tracker"),
    ],
)
def test_remote_protocols_normalize_to_same_identity(raw: str, expected: str) -> None:
    assert normalize_git_remote(raw) == expected


def test_remote_credentials_are_removed() -> None:
    assert normalize_git_remote("https://token@github.com/mike/repo.git") == "github.com/mike/repo"
```

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/unit/repositories/test_remote.py -v
```

Expected: import failure.

- [ ] **Step 3: Implement normalization**

Support HTTPS, HTTP, `ssh://`, `git://`, and SCP-like SSH syntax. Remove protocol, user info, query, fragment, trailing slash, and `.git`; lowercase the host; preserve repository path case.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/repositories/test_remote.py -v
uv run ruff check .
uv run pyright
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_worklog/repositories/remote.py tests/unit/repositories
git commit -m "feat: normalize git repository remotes"
```

---

### Task 9: Repository Resolver with Worktree and Fallback Support

**Files:**
- Create: `src/agent_worklog/repositories/resolver.py`
- Create: `tests/unit/repositories/test_resolver.py`

**Interfaces:**
- Consumes: `AgentSession`, `CommandRunner`.
- Produces: `RepositoryResolver.resolve(session) -> RepositoryIdentity`.

- [ ] **Step 1: Write failing resolver tests**

```python
from agent_worklog.models.session import AgentSession
from agent_worklog.repositories.resolver import RepositoryResolver


def test_same_remote_groups_different_worktrees(fake_git_runner) -> None:
    fake_git_runner.set_output("remote get-url origin", "git@github.com:mike/repo.git")
    fake_git_runner.set_output("rev-parse --git-common-dir", "/repo/.git")
    resolver = RepositoryResolver(runner=fake_git_runner)

    first = resolver.resolve(
        AgentSession(harness="opencode", session_id="s1", working_directory="/worktree/a")
    )
    second = resolver.resolve(
        AgentSession(harness="opencode", session_id="s2", working_directory="/worktree/b")
    )

    assert first.repository_id == second.repository_id == "git:github.com/mike/repo"
```

Add tests for:

- same basename but different owners remain different;
- no remote falls back to hashed absolute Git common directory;
- deleted path falls back to `harness:opencode:<project-id>`;
- no hints returns `unknown:opencode:<session-id>`.

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/unit/repositories/test_resolver.py -v
```

Expected: import failure.

- [ ] **Step 3: Implement resolution priority**

Run, with a five-second timeout:

```text
git -C <cwd> remote get-url origin
git -C <cwd> rev-parse --git-common-dir
git -C <cwd> branch --show-current
```

Return identities in this order:

```text
git:<normalized-remote>
git-common:<sha256(common-dir)[:12]>
harness:<harness>:<project-id>
path:<sha256(normalized-path)[:12]>
unknown:<harness>:<session-id>
```

Do not expose full common directories in `repository_id`.

- [ ] **Step 4: Run repository tests**

```bash
uv run pytest tests/unit/repositories -v
uv run pytest -q
uv run ruff check .
uv run pyright
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_worklog/repositories tests/unit/repositories
git commit -m "feat: resolve sessions to canonical git repositories"
```

---

### Task 10: Resolve Repository Before Building Parent/Child Relationships

**Files:**
- Create: `src/agent_worklog/sessions/hierarchy.py`
- Create: `tests/fixtures/opencode/export-child.json`
- Create: `tests/fixtures/opencode/export-cross-repo-child.json`
- Create: `tests/unit/sessions/test_hierarchy.py`

**Interfaces:**
- Consumes: `list[ResolvedSession]`.
- Produces: `SessionRelationshipIndex`; `count_child_sessions_by_repository()`.

- [ ] **Step 1: Write the cross-repository child regression test**

```python
from agent_worklog.sessions.hierarchy import group_resolved_sessions


def test_child_session_in_another_repository_stays_in_that_repository(
    resolved_root,
    resolved_cross_repo_child,
) -> None:
    grouped = group_resolved_sessions([resolved_root, resolved_cross_repo_child])

    assert [item.session.session_id for item in grouped["git:github.com/org/backend"]] == ["root"]
    assert [item.session.session_id for item in grouped["git:github.com/org/frontend"]] == ["child"]
```

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/unit/sessions/test_hierarchy.py -v
```

Expected: import failure.

- [ ] **Step 3: Implement repository-first grouping**

```python
from collections import defaultdict

from agent_worklog.models.repository import ResolvedSession


def group_resolved_sessions(
    sessions: list[ResolvedSession],
) -> dict[str, list[ResolvedSession]]:
    grouped: dict[str, list[ResolvedSession]] = defaultdict(list)
    for resolved in sessions:
        grouped[resolved.repository.repository_id].append(resolved)
    return dict(grouped)
```

Build parent/child metadata only for counts and deduplication. Never move child activities from one repository bucket into the parent repository bucket.

- [ ] **Step 4: Run hierarchy and repository tests**

```bash
uv run pytest tests/unit/sessions/test_hierarchy.py tests/unit/repositories -v
uv run pytest -q
uv run ruff check .
uv run pyright
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_worklog/sessions/hierarchy.py tests
git commit -m "fix: preserve repository ownership across child sessions"
```

---

## Phase 4 — Evidence and Security

### Task 11: Provenance-Aware Evidence Extraction

**Files:**
- Create: `src/agent_worklog/extraction/rules.py`
- Create: `src/agent_worklog/extraction/pipeline.py`
- Create: `tests/unit/extraction/test_pipeline.py`

**Interfaces:**
- Consumes: `ResolvedSession`.
- Produces: `extract_evidence(resolved: ResolvedSession) -> SessionEvidence`.

- [ ] **Step 1: Write failing evidence tests**

```python
from agent_worklog.extraction.pipeline import extract_evidence


def test_user_request_becomes_goal_with_provenance(resolved_session_with_user_message) -> None:
    evidence = extract_evidence(resolved_session_with_user_message)

    goal = evidence.goals[0]
    assert goal.text == "Add weekly report generation"
    assert goal.source_activity_ids == ["message-1:part-0"]
    assert goal.extraction_method == "user_message"


def test_successful_test_command_becomes_completed_outcome(
    resolved_session_with_successful_pytest,
) -> None:
    evidence = extract_evidence(resolved_session_with_successful_pytest)

    assert evidence.outcomes[0].status == "completed"
    assert evidence.outcomes[0].confidence == "high"
```

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/unit/extraction/test_pipeline.py -v
```

Expected: import failure.

- [ ] **Step 3: Implement conservative deterministic rules**

Implement these MVP rules only:

- meaningful user text becomes a goal;
- shell/tool command metadata becomes command evidence;
- edit/write/patch tool metadata becomes file evidence;
- non-zero exit code becomes error evidence;
- successful commands matching `pytest`, `ruff`, `pyright`, `npm test`, `pnpm test`, or `npm run build` become high-confidence completed outcomes;
- assistant claims without supporting successful tool evidence remain low-confidence `unknown`, not completed;
- deduplicate evidence by normalized text plus repository ID.

Every item must include at least one source activity ID.

- [ ] **Step 4: Run extraction tests**

```bash
uv run pytest tests/unit/extraction -v
uv run pytest -q
uv run ruff check .
uv run pyright
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_worklog/extraction tests/unit/extraction
git commit -m "feat: extract provenance-aware session evidence"
```

---

### Task 12: Recursive Secret Redaction and Secure Files

**Files:**
- Create: `src/agent_worklog/security/redactor.py`
- Create: `src/agent_worklog/security/secure_files.py`
- Create: `tests/unit/security/test_redactor.py`
- Create: `tests/unit/security/test_secure_files.py`

**Interfaces:**
- Consumes: strings, dictionaries, lists, output paths.
- Produces: `redact_text()`, `redact_value()`, `secure_temporary_directory()`, `atomic_secure_write()`.

- [ ] **Step 1: Write failing redaction and permission tests**

```python
from agent_worklog.security.redactor import redact_value


def test_recursive_metadata_redaction() -> None:
    value = {
        "headers": {"Authorization": "Bearer abc.def.ghi"},
        "command": "curl -u mike:secret https://example.com",
    }

    redacted = redact_value(value)

    assert "abc.def.ghi" not in str(redacted)
    assert "mike:secret" not in str(redacted)
```

Add a POSIX-only test asserting an atomically written report has mode `0600`.

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/unit/security -v
```

Expected: import failure.

- [ ] **Step 3: Implement multi-stage redaction and secure writes**

Redact at least:

- bearer/basic authorization;
- GitHub tokens;
- common OpenAI/Anthropic keys;
- AWS access and secret keys;
- JWT-like values;
- passwords in URLs;
- `password=`, `token=`, `secret=` assignments;
- private key blocks.

`atomic_secure_write(path, content, force=False)` must:

1. reject an existing path unless `force=True`;
2. create the parent directory;
3. write to a temporary sibling;
4. set mode `0600` on POSIX;
5. atomically replace the destination;
6. remove the temporary file on failure.

- [ ] **Step 4: Run security tests**

```bash
uv run pytest tests/unit/security -v
uv run pytest -q
uv run ruff check .
uv run pyright
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_worklog/security tests/unit/security
git commit -m "feat: redact secrets and write reports securely"
```

---

## Phase 5 — Deterministic Worklog

### Task 13: Rule-Based Repository Summarization

**Files:**
- Create: `src/agent_worklog/summarizers/base.py`
- Create: `src/agent_worklog/summarizers/rule_based.py`
- Create: `tests/unit/summarizers/test_rule_based.py`

**Interfaces:**
- Consumes: `repository_id`, display metadata, `list[SessionEvidence]`.
- Produces: `RuleBasedSummarizer.summarize(evidence: RepositoryEvidence) -> RepositorySummary`.

- [ ] **Step 1: Write failing summarizer tests**

```python
from agent_worklog.summarizers.rule_based import RuleBasedSummarizer


def test_rule_summary_separates_completed_and_in_progress(repository_evidence) -> None:
    summary = RuleBasedSummarizer().summarize(repository_evidence)

    assert "Tests passed" in summary.completed
    assert "Add cache" in summary.in_progress
```

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/unit/summarizers/test_rule_based.py -v
```

Expected: import failure.

- [ ] **Step 3: Implement deterministic mapping**

Use these rules:

- high-confidence completed outcomes -> `completed`;
- resolved high-confidence errors -> `problems_resolved`;
- goals with no completed outcome -> `in_progress`;
- file evidence -> `key_files`;
- low-confidence assistant claims do not enter `completed`;
- stable alphabetical ordering after preserving first occurrence;
- maximum 20 entries per section with a final `Additional items omitted: N` line.

- [ ] **Step 4: Run summarizer tests**

```bash
uv run pytest tests/unit/summarizers -v
uv run pytest -q
uv run ruff check .
uv run pyright
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_worklog/summarizers tests/unit/summarizers
git commit -m "feat: generate deterministic repository summaries"
```

---

### Task 14: Markdown Renderer

**Files:**
- Create: `src/agent_worklog/templates/worklog.md.j2`
- Create: `src/agent_worklog/renderers/markdown.py`
- Create: `tests/unit/renderers/test_markdown.py`

**Interfaces:**
- Consumes: `WorklogReport`.
- Produces: `MarkdownRenderer.render(report) -> str`.

- [ ] **Step 1: Write failing snapshot assertions**

```python
from agent_worklog.renderers.markdown import MarkdownRenderer


def test_markdown_contains_period_repository_and_warnings(sample_report) -> None:
    output = MarkdownRenderer().render(sample_report)

    assert "# Engineering Worklog" in output
    assert "## Repositories" in output
    assert "### Agent Worklog" in output
    assert "## Warnings" in output
```

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/unit/renderers/test_markdown.py -v
```

Expected: import failure.

- [ ] **Step 3: Implement renderer and template**

The template must include:

- report period and timezone;
- one section per repository;
- repository remote when available;
- completed, problems resolved, in progress, key files;
- session and child-session counts;
- branches;
- warnings;
- no empty section headers.

Do not include raw prompts, raw transcript blocks, or full command output.

- [ ] **Step 4: Run renderer tests**

```bash
uv run pytest tests/unit/renderers -v
uv run pytest -q
uv run ruff check .
uv run pyright
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_worklog/templates src/agent_worklog/renderers tests/unit/renderers
git commit -m "feat: render repository worklogs as markdown"
```

---

### Task 15: Scan and Report Services with Partial Failure

**Files:**
- Create: `src/agent_worklog/services/scan.py`
- Create: `src/agent_worklog/services/report.py`
- Create: `tests/integration/test_scan_service.py`
- Create: `tests/integration/test_report_service.py`

**Interfaces:**
- Consumes: OpenCode source, date range, repository resolver, evidence pipeline, summarizer, renderer.
- Produces: `ScanResult`; `ReportService.generate()`.

- [ ] **Step 1: Write failing integration tests**

```python
import pytest

from agent_worklog.errors import HarnessSourceError


def test_scan_continues_after_one_export_failure(scan_service, fake_source) -> None:
    fake_source.fail_session_ids = {"bad"}

    result = scan_service.scan()

    assert result.loaded_session_count == 2
    assert result.failed_session_count == 1
    assert any("bad" in warning for warning in result.warnings)


def test_all_exports_failing_is_an_error(report_service, fake_source) -> None:
    fake_source.fail_all = True

    with pytest.raises(HarnessSourceError):
        report_service.generate(force=False)
```

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/integration/test_scan_service.py tests/integration/test_report_service.py -v
```

Expected: import failure.

- [ ] **Step 3: Implement the orchestration order**

The exact pipeline must be:

```text
discover candidates
→ load sanitized sessions independently
→ exact activity filtering
→ resolve repository for each session
→ build parent/child metadata without moving repository ownership
→ extract and redact evidence
→ summarize per repository
→ render Markdown
→ atomic secure write
```

Warnings must include failed exports, timestamp-less activities, and fallback repository identities.

- [ ] **Step 4: Run integration and full tests**

```bash
uv run pytest tests/integration -v
uv run pytest --cov=agent_worklog --cov-report=term-missing
uv run ruff check .
uv run pyright
```

Expected: all pass; coverage is at least 80% for core modules.

- [ ] **Step 5: Commit**

```bash
git add src/agent_worklog/services tests/integration
git commit -m "feat: orchestrate cross-project scan and worklog generation"
```

---

### Task 16: Complete `doctor`, `scan`, and `report` CLI Contracts

**Files:**
- Modify: `src/agent_worklog/cli.py`
- Modify: `src/agent_worklog/errors.py`
- Create: `src/agent_worklog/logging.py`
- Create: `tests/integration/test_cli.py`

**Interfaces:**
- Consumes: `run_doctor()`, `ScanService`, `ReportService`, `DateRange`.
- Produces: user-facing CLI and exit codes.

- [ ] **Step 1: Write failing CLI behavior tests**

```python
from typer.testing import CliRunner

from agent_worklog.cli import app

runner = CliRunner()


def test_report_refuses_overwrite_without_force(existing_report, app_dependencies) -> None:
    result = runner.invoke(
        app,
        ["report", "--days", "7", "--output", str(existing_report)],
    )

    assert result.exit_code == 7
    assert "already exists" in result.stdout


def test_report_supports_previous_calendar_week(app_dependencies) -> None:
    result = runner.invoke(app, ["report", "--period", "last-week", "--dry-run"])

    assert result.exit_code == 0
```

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/integration/test_cli.py -v
```

Expected: command option failures.

- [ ] **Step 3: Implement exact CLI**

Commands:

```text
agent-worklog doctor
agent-worklog scan --days 7
agent-worklog scan --period last-week
agent-worklog report --days 7 --output report.md
agent-worklog report --period last-week --no-llm
```

Options:

```text
--days INTEGER
--period last-week
--since ISO_DATETIME
--until ISO_DATETIME
--output PATH
--dry-run
--no-llm
--force
--verbose
--quiet
```

Validation:

- exactly one of `--days`, `--period`, or `--since` may be used;
- `--until` requires `--since`;
- `--days >= 1`;
- `--period` accepts only `last-week` in MVP;
- output overwrite requires `--force`.

Implement `logging.py` with Rich console helpers that accept already-redacted strings only. `--quiet` prints only the output path; `--verbose` may print repository resolution methods and warnings but never raw transcript content.

Exit codes:

```text
0 success
2 invalid CLI usage
3 configuration error
4 no sessions found
5 OpenCode source error
7 report generation or output error
```

- [ ] **Step 4: Run CLI and full checks**

```bash
uv run pytest tests/integration/test_cli.py -v
uv run pytest --cov=agent_worklog --cov-fail-under=80
uv run ruff check .
uv run pyright
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_worklog/cli.py src/agent_worklog/errors.py src/agent_worklog/logging.py tests/integration/test_cli.py
git commit -m "feat: expose doctor scan and report commands"
```

At this commit, **v0.1-alpha is usable without an LLM**.

---

## Phase 6 — Optional LLM Summaries

### Task 17: OpenAI-Compatible Summarizer with Strict Redacted Input

**Files:**
- Create: `src/agent_worklog/summarizers/openai_compatible.py`
- Create: `tests/unit/summarizers/test_openai_compatible.py`
- Modify: `src/agent_worklog/config.py`

**Interfaces:**
- Consumes: redacted `SessionEvidence` only.
- Produces: `OpenAICompatibleSummarizer.summarize(evidence: RepositoryEvidence) -> RepositorySummary`.

- [ ] **Step 1: Write failing LLM boundary tests**

```python
def test_llm_payload_contains_evidence_not_raw_transcript(
    mock_transport,
    llm_summarizer,
    repository_evidence,
) -> None:
    llm_summarizer.summarize(repository_evidence)

    payload = mock_transport.last_json
    serialized = str(payload)
    assert "source_activity_ids" in serialized
    assert "raw_metadata" not in serialized
    assert "messages" not in serialized


def test_invalid_llm_json_falls_back_to_rule_summary(
    invalid_json_transport,
    fallback_summarizer,
    repository_evidence,
) -> None:
    summary = fallback_summarizer.summarize(repository_evidence)

    assert summary.completed
```

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/unit/summarizers/test_openai_compatible.py -v
```

Expected: import failure.

- [ ] **Step 3: Implement structured output and one retry**

Use `httpx.Client` with configured base URL, model, API-key environment variable name, and timeout. Send only redacted evidence fields. Validate the response against this shape:

```json
{
  "summary": "string",
  "completed": ["string"],
  "problems_resolved": ["string"],
  "in_progress": ["string"],
  "key_files": ["string"]
}
```

Retry once for timeout, HTTP 429/5xx, or invalid structured output. After the retry, return `RuleBasedSummarizer` output and add a warning.

- [ ] **Step 4: Run mocked LLM tests**

```bash
uv run pytest tests/unit/summarizers/test_openai_compatible.py -v
uv run pytest -q
uv run ruff check .
uv run pyright
```

Expected: all pass without a network call.

- [ ] **Step 5: Commit**

```bash
git add src/agent_worklog/summarizers/openai_compatible.py src/agent_worklog/config.py tests/unit/summarizers
git commit -m "feat: add optional evidence-grounded llm summaries"
```

---

### Task 18: Wire LLM Selection into Report Service and CLI

**Files:**
- Modify: `src/agent_worklog/services/report.py`
- Modify: `src/agent_worklog/cli.py`
- Modify: `tests/integration/test_report_service.py`
- Modify: `tests/integration/test_cli.py`

**Interfaces:**
- Consumes: `--no-llm`, LLM settings.
- Produces: deterministic fallback and warning propagation.

- [ ] **Step 1: Write failing selection tests**

```python
def test_no_llm_never_constructs_http_client(report_service_factory) -> None:
    service = report_service_factory(use_llm=False)

    service.generate(force=False)

    assert service.llm_client_created is False


def test_llm_failure_still_writes_report(report_service_with_failing_llm, output_path) -> None:
    result = report_service_with_failing_llm.generate(output=output_path, force=False)

    assert output_path.exists()
    assert any("LLM" in warning for warning in result.warnings)
```

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/integration/test_report_service.py tests/integration/test_cli.py -v
```

Expected: failing selection assertions.

- [ ] **Step 3: Implement lazy LLM construction**

Construct the HTTP client only when:

```text
LLM is enabled in config
AND --no-llm is not supplied
AND the configured API-key environment variable exists
```

Otherwise use the rule-based summarizer. Never log the key value.

- [ ] **Step 4: Run all tests**

```bash
uv run pytest --cov=agent_worklog --cov-fail-under=80
uv run ruff check .
uv run pyright
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_worklog/services/report.py src/agent_worklog/cli.py tests/integration
git commit -m "feat: select llm summaries with deterministic fallback"
```

---

## Phase 7 — Release Hardening

### Task 19: End-to-End Acceptance Fixture

**Files:**
- Create: `tests/integration/test_end_to_end.py`
- Create: `tests/fixtures/opencode/export-cross-repo-child.json`
- Create: `tests/fixtures/opencode/export-secret.json`
- Modify: test fake command runner fixtures under `tests/conftest.py`

**Interfaces:**
- Consumes: complete CLI pipeline with mocked OpenCode and LLM commands.
- Produces: one acceptance test proving the release gate.

- [ ] **Step 1: Write the full acceptance test**

```python
from pathlib import Path

from agent_worklog.cli import app


def test_end_to_end_weekly_worklog(
    cli_runner,
    mocked_opencode,
    isolated_filesystem,
) -> None:
    result = cli_runner.invoke(
        app,
        [
            "report",
            "--period",
            "last-week",
            "--no-llm",
            "--output",
            "worklog.md",
        ],
    )

    assert result.exit_code == 0
    content = Path("worklog.md").read_text(encoding="utf-8")
    assert "github.com/mike/agent-worklog" in content
    assert "github.com/mike/assets-tracker" in content
    assert "super-secret-token" not in content
    assert content.count("### Agent Worklog") == 1
```

The fixture must include:

- sessions from at least two OpenCode projects;
- two worktrees for the same Git repository;
- a child session in another repository;
- a session created before the period with an in-period activity;
- one failed export;
- one secret-containing export;
- two repositories sharing the same basename but different owners.

- [ ] **Step 2: Verify the acceptance test initially finds fixture gaps**

```bash
uv run pytest tests/integration/test_end_to_end.py -v
```

Expected: failure until every fixture and orchestration path is connected.

- [ ] **Step 3: Make only the integration wiring changes required by the test**

Do not add new product behavior. Fix dependency injection, fixtures, and output formatting until the acceptance scenario passes.

- [ ] **Step 4: Run the release test suite**

```bash
uv run pytest --cov=agent_worklog --cov-fail-under=80
uv run ruff check .
uv run pyright
uv build
```

Expected: tests, lint, typing, and build all pass.

- [ ] **Step 5: Commit**

```bash
git add tests src pyproject.toml
git commit -m "test: cover the complete agent worklog workflow"
```

---

### Task 20: Documentation, Installation, and Release Workflow

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/release.yml`
- Create: `docs/configuration.md`
- Create: `docs/privacy.md`

**Interfaces:**
- Consumes: final CLI contracts.
- Produces: installable and documented `0.1.0` package.

- [ ] **Step 1: Add documentation smoke assertions**

Create `tests/unit/test_documentation.py`:

```python
from pathlib import Path


def test_readme_documents_release_gate_commands() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "pipx install agent-worklog" in readme
    assert "agent-worklog doctor" in readme
    assert "agent-worklog scan --period last-week" in readme
    assert "agent-worklog report --period last-week" in readme
```

- [ ] **Step 2: Run the documentation test to verify failure**

```bash
uv run pytest tests/unit/test_documentation.py -v
```

Expected: one or more commands are absent.

- [ ] **Step 3: Document exact operational behavior**

README must cover:

- installation with `pipx` and `pip`;
- OpenCode and Git prerequisites;
- `doctor`, `scan`, and `report` examples;
- rolling days versus previous complete week;
- Git repository grouping and worktree behavior;
- sanitized OpenCode export;
- LLM opt-in and `--no-llm`;
- overwrite protection and `--force`;
- partial-failure warnings;
- current MVP limitations.

`docs/privacy.md` must state that reports can still contain proprietary work descriptions even after token redaction.

CI must run Python 3.11, 3.12, and 3.13 with:

```bash
uv run pytest --cov=agent_worklog --cov-fail-under=80
uv run ruff check .
uv run pyright
uv build
```

Release workflow must publish only on a signed `v*` tag using PyPI trusted publishing.

- [ ] **Step 4: Verify install and package metadata locally**

```bash
uv run pytest tests/unit/test_documentation.py -v
uv build
python -m venv /tmp/agent-worklog-release-test
/tmp/agent-worklog-release-test/bin/pip install dist/*.whl
/tmp/agent-worklog-release-test/bin/agent-worklog --help
```

Expected: wheel installs and help lists `doctor`, `scan`, and `report`.

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md docs .github tests/unit/test_documentation.py
git commit -m "docs: prepare agent worklog v0.1 release"
```

---

## Release Gate Checklist

The MVP is ready to tag `v0.1.0` only when every item below is true:

- [ ] `agent-worklog doctor` validates OpenCode and Git without exposing secrets.
- [ ] `agent-worklog scan --period last-week` finds sessions across all OpenCode projects.
- [ ] The process current working directory does not change discovery results.
- [ ] Candidate selection uses interval overlap and final filtering uses activity timestamps.
- [ ] `opencode export` always receives `--sanitize`.
- [ ] One failed session export produces a warning; all failed exports produce exit code 5.
- [ ] Same Git repository across worktrees is grouped once.
- [ ] Same basename under different repository owners remains separate.
- [ ] A child session in another repository remains in the child repository.
- [ ] Unknown sessions are not all merged.
- [ ] Every extracted evidence item includes source activity IDs and confidence.
- [ ] Token usage with unknown semantics is not rendered as zero or summed.
- [ ] Raw transcripts and raw metadata never enter the LLM request.
- [ ] Secrets are redacted recursively before rendering and before LLM calls.
- [ ] Temporary exports are removed by default.
- [ ] Existing reports are not overwritten without `--force`.
- [ ] `agent-worklog report --period last-week --no-llm` creates a useful Markdown report.
- [ ] LLM timeout, 429, 5xx, or invalid JSON falls back to the rule-based summary.
- [ ] Test coverage is at least 80% for core modules.
- [ ] Ruff, Pyright, pytest, and package build pass on Python 3.11–3.13.

---

## Explicitly Deferred Beyond v0.1

These items require separate specs and implementation plans after the MVP release:

1. Direct read-only SQLite OpenCode source and schema adapters.
2. JSON report output and public JSON schema evolution policy.
3. `agent-worklog inspect` command.
4. Persistent Agent Worklog cache and deleted-worktree repository mappings.
5. Codex SQLite/JSONL hybrid adapter.
6. Claude Code transcript and hook adapters.
7. Git commit, pull request, and work-item correlation.
8. Team aggregation, scheduled delivery, Slack, email, and Google Docs output.
