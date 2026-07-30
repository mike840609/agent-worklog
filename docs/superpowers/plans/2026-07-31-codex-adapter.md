# Codex Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Codex as a third harness so `agent-worklog doctor|scan|report --harness codex` produces the same repository-grouped Markdown report the OpenCode and Claude Code harnesses already produce.

**Architecture:** A new `harnesses/codex/` package implements `HarnessSessionSource`. Discovery prefers `~/.codex/state_<n>.sqlite`, which already indexes every session with its rollout path, cwd, timestamps and parent edge, and falls back to scanning the rollout JSONL files when that database is absent or its schema has drifted. A mapper turns one rollout file into a canonical `AgentSession`. The shared extraction pipeline, repository resolver, redactor, summarizers and renderers are not modified.

**Tech Stack:** Python 3.11+, pydantic v2 / pydantic-settings, Typer, pytest, stdlib `sqlite3`, `uv` for dependency and task running.

Spec: `docs/superpowers/specs/2026-07-31-codex-adapter-design.md`

## Global Constraints

- Python 3.11+. No new third-party dependencies — `sqlite3` and `json` are stdlib.
- `--harness` default stays `opencode`. OpenCode and Claude Code behaviour must not change.
- `src/agent_worklog/extraction/pipeline.py` and `src/agent_worklog/extraction/rules.py` must not be modified. The Codex adapter's conservatism is expressed by what the mapper puts in `SessionActivity.metadata`, not by new pipeline branches.
- The Codex mapper must never set `metadata["exit_code"]` or `metadata["stderr_empty"]`. No Codex report may contain the string `Verification passed`.
- `patch_apply_end.changes` values contain whole file contents. Only the dict's keys (file paths) may leave the mapper.
- `exec` tool inputs are arbitrary JavaScript and must never reach `SessionActivity.content`.
- Harness name string is `"codex"`; `Harness` enum member is `CODEX = "codex"`.
- Every commit must keep `uv run pytest --cov=agent_worklog --cov-fail-under=80`, `uv run ruff check .` and `uv run pyright` green.
- Code comments explain *why*, matching the density of the surrounding modules. American English in code and docs; the two READMEs are English and Traditional Chinese.

---

### Task 1: Settings, enum member, and the enabled check

**Files:**
- Modify: `src/agent_worklog/config.py:23-40`
- Modify: `src/agent_worklog/cli.py:38-41`, `src/agent_worklog/cli.py:122-140`
- Test: `tests/unit/test_config.py` (create), `tests/integration/test_cli.py` (modify)

**Interfaces:**
- Consumes: nothing.
- Produces: `agent_worklog.config.CodexSettings` with fields `enabled: bool` and `home_directory: Path`; `AppSettings.harnesses.codex: CodexSettings`; `agent_worklog.cli.Harness.CODEX` with value `"codex"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_config.py`:

```python
from pathlib import Path

from agent_worklog.config import AppSettings


def test_codex_defaults_to_the_user_codex_home() -> None:
    settings = AppSettings()

    assert settings.harnesses.codex.enabled is True
    assert settings.harnesses.codex.home_directory == Path.home() / ".codex"


def test_codex_home_directory_is_configurable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(
        "AGENT_WORKLOG_HARNESSES__CODEX__HOME_DIRECTORY", str(tmp_path / "codex")
    )

    settings = AppSettings()

    assert settings.harnesses.codex.home_directory == tmp_path / "codex"
```

Append to `tests/integration/test_cli.py`:

```python
def test_disabled_codex_harness_is_refused(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_WORKLOG_HARNESSES__CODEX__ENABLED", "false")

    result = CliRunner().invoke(cli.app, ["doctor", "--harness", "codex"])

    assert result.exit_code == 3
    assert "AGENT_WORKLOG_HARNESSES__CODEX__ENABLED" in result.stdout
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_config.py tests/integration/test_cli.py::test_disabled_codex_harness_is_refused -v`
Expected: FAIL — `AttributeError: 'HarnessSettings' object has no attribute 'codex'`, and the CLI rejects `codex` as an invalid `--harness` value.

- [ ] **Step 3: Add the settings model**

In `src/agent_worklog/config.py`, after `ClaudeCodeSettings`:

```python
class CodexSettings(BaseModel):
    """Codex harness settings."""

    # `false` makes `--harness codex` fail with a configuration error, so an
    # operator can forbid reading `~/.codex` on a whole machine.
    enabled: bool = True
    # One setting, not three: the state database, `sessions/` and
    # `archived_sessions/` are all fixed positions under this directory.
    home_directory: Path = Field(default_factory=lambda: Path.home() / ".codex")
```

and add the field to `HarnessSettings`:

```python
class HarnessSettings(BaseModel):
    """Configured coding-agent harnesses."""

    opencode: OpenCodeSettings = Field(default_factory=OpenCodeSettings)
    claude_code: ClaudeCodeSettings = Field(default_factory=ClaudeCodeSettings)
    codex: CodexSettings = Field(default_factory=CodexSettings)
```

- [ ] **Step 4: Add the enum member and simplify the enabled check**

In `src/agent_worklog/cli.py`:

```python
class Harness(StrEnum):
    OPENCODE = "opencode"
    CLAUDE_CODE = "claude-code"
    CODEX = "codex"
```

Replace the body of `_require_enabled_harness` (`cli.py:122-140`) with:

```python
def _require_enabled_harness(settings: AppSettings, harness: Harness) -> None:
    """Refuse a harness its configuration has turned off.

    A privacy tool must not advertise an off switch that does nothing: reading
    `~/.claude/projects` or `~/.codex` is exactly the kind of thing an operator
    may need to forbid for a whole machine.

    Each enum member's name is the settings field name, so a new harness needs
    no edit here.
    """

    if not getattr(settings.harnesses, harness.name.lower()).enabled:
        variable = f"AGENT_WORKLOG_HARNESSES__{harness.name}__ENABLED"
        raise ConfigurationError(
            f"harness {harness.value} is disabled by configuration; "
            f"set {variable}=true to use it"
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_config.py tests/integration/test_cli.py -v`
Expected: PASS, including the existing OpenCode and Claude Code disabled-harness tests, which prove the `getattr` lookup is equivalent to the if/else it replaced.

- [ ] **Step 6: Commit**

```bash
git add src/agent_worklog/config.py src/agent_worklog/cli.py tests/unit/test_config.py tests/integration/test_cli.py
git commit -m "feat: add Codex harness settings and enum member"
```

---

### Task 2: `thread_catalog.py` — discovery from the state database

**Files:**
- Create: `src/agent_worklog/harnesses/codex/__init__.py` (empty)
- Create: `src/agent_worklog/harnesses/codex/thread_catalog.py`
- Test: `tests/unit/harnesses/codex/__init__.py` (empty), `tests/unit/harnesses/codex/test_thread_catalog.py`

**Interfaces:**
- Consumes: `agent_worklog.models.session.SessionDescriptor`, `agent_worklog.models.time_range.DateRange`.
- Produces:
  - `HARNESS_NAME: str = "codex"`
  - `find_state_database(home_directory: Path) -> Path | None`
  - `discover_threads(database: Path, period: DateRange, *, root_only: bool) -> list[SessionDescriptor]` — raises `sqlite3.Error` on an unreadable or drifted database.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/harnesses/codex/__init__.py` (empty) and `tests/unit/harnesses/codex/test_thread_catalog.py`:

```python
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from agent_worklog.harnesses.codex.thread_catalog import (
    discover_threads,
    find_state_database,
)
from agent_worklog.models.time_range import DateRange

TZ = ZoneInfo("Asia/Taipei")
PERIOD = DateRange(
    since=datetime(2026, 7, 20, tzinfo=TZ),
    until=datetime(2026, 7, 27, tzinfo=TZ),
)

_SCHEMA = """
CREATE TABLE threads (
    id TEXT PRIMARY KEY,
    rollout_path TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    cwd TEXT NOT NULL,
    title TEXT NOT NULL,
    agent_nickname TEXT,
    thread_source TEXT,
    archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE thread_spawn_edges (
    parent_thread_id TEXT NOT NULL,
    child_thread_id TEXT NOT NULL PRIMARY KEY,
    status TEXT NOT NULL
);
"""


def _seconds(value: datetime) -> int:
    return int(value.timestamp())


def _write_database(path: Path, rows: list[tuple], edges: list[tuple] = []) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_SCHEMA)
        connection.executemany(
            "INSERT INTO threads (id, rollout_path, created_at, updated_at, cwd,"
            " title, agent_nickname, thread_source, archived)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.executemany(
            "INSERT INTO thread_spawn_edges"
            " (parent_thread_id, child_thread_id, status) VALUES (?, ?, ?)",
            edges,
        )
        connection.commit()
    finally:
        connection.close()


@pytest.fixture
def home(tmp_path: Path) -> Path:
    rollout = tmp_path / "sessions" / "rollout-root.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text("{}\n", encoding="utf-8")
    archived = tmp_path / "archived_sessions" / "rollout-old.jsonl"
    archived.parent.mkdir(parents=True)
    archived.write_text("{}\n", encoding="utf-8")

    _write_database(
        tmp_path / "state_5.sqlite",
        rows=[
            (
                "root-1",
                str(rollout),
                _seconds(datetime(2026, 7, 21, tzinfo=TZ)),
                _seconds(datetime(2026, 7, 22, tzinfo=TZ)),
                "/worktrees/agent",
                "Add retry",
                None,
                "user",
                0,
            ),
            (
                "sub-1",
                str(rollout),
                _seconds(datetime(2026, 7, 21, 2, tzinfo=TZ)),
                _seconds(datetime(2026, 7, 21, 3, tzinfo=TZ)),
                "/worktrees/agent",
                "",
                "Ampere",
                "subagent",
                0,
            ),
            (
                "archived-1",
                str(archived),
                _seconds(datetime(2026, 7, 23, tzinfo=TZ)),
                _seconds(datetime(2026, 7, 23, 1, tzinfo=TZ)),
                "/worktrees/assets",
                "Archived work",
                None,
                "user",
                1,
            ),
            (
                "stale-1",
                str(rollout),
                _seconds(datetime(2026, 7, 1, tzinfo=TZ)),
                _seconds(datetime(2026, 7, 2, tzinfo=TZ)),
                "/worktrees/agent",
                "Old work",
                None,
                "user",
                0,
            ),
        ],
        edges=[("root-1", "sub-1", "completed")],
    )
    return tmp_path


def test_finds_the_highest_versioned_state_database(home: Path) -> None:
    (home / "state_10.sqlite").write_text("", encoding="utf-8")
    (home / "state_2.sqlite").write_text("", encoding="utf-8")

    assert find_state_database(home) == home / "state_10.sqlite"


def test_returns_none_without_a_state_database(tmp_path: Path) -> None:
    assert find_state_database(tmp_path) is None


def test_discovers_sessions_overlapping_the_period(home: Path) -> None:
    descriptors = discover_threads(
        find_state_database(home), PERIOD, root_only=False
    )

    ids = {descriptor.session_id for descriptor in descriptors}
    assert ids == {"root-1", "sub-1", "archived-1"}


def test_archived_sessions_are_not_excluded(home: Path) -> None:
    descriptors = discover_threads(
        find_state_database(home), PERIOD, root_only=False
    )

    assert "archived-1" in {descriptor.session_id for descriptor in descriptors}


def test_root_only_excludes_subagent_threads(home: Path) -> None:
    descriptors = discover_threads(find_state_database(home), PERIOD, root_only=True)

    assert "sub-1" not in {descriptor.session_id for descriptor in descriptors}


def test_descriptor_carries_metadata_and_parent_edge(home: Path) -> None:
    descriptors = discover_threads(
        find_state_database(home), PERIOD, root_only=False
    )
    by_id = {descriptor.session_id: descriptor for descriptor in descriptors}

    root = by_id["root-1"]
    assert root.harness == "codex"
    assert root.title == "Add retry"
    assert root.working_directory_hint == "/worktrees/agent"
    assert root.created_at == datetime(2026, 7, 21, tzinfo=TZ).astimezone(UTC)
    assert root.parent_session_id is None
    assert by_id["sub-1"].parent_session_id == "root-1"


def test_empty_title_falls_back_to_the_agent_nickname(home: Path) -> None:
    descriptors = discover_threads(
        find_state_database(home), PERIOD, root_only=False
    )
    by_id = {descriptor.session_id: descriptor for descriptor in descriptors}

    assert by_id["sub-1"].title == "Ampere"


def test_schema_drift_raises_for_the_caller_to_fall_back(tmp_path: Path) -> None:
    database = tmp_path / "state_5.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE unrelated (id TEXT)")
    connection.commit()
    connection.close()

    with pytest.raises(sqlite3.Error):
        discover_threads(database, PERIOD, root_only=False)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/harnesses/codex/test_thread_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_worklog.harnesses.codex'`.

- [ ] **Step 3: Write the implementation**

Create `src/agent_worklog/harnesses/codex/__init__.py` as an empty file, and `src/agent_worklog/harnesses/codex/thread_catalog.py`:

```python
"""Discover Codex sessions from the Codex state database."""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from agent_worklog.models.session import SessionDescriptor
from agent_worklog.models.time_range import DateRange

HARNESS_NAME = "codex"

# The file name carries the schema version, so a Codex upgrade introduces
# `state_6.sqlite` beside `state_5.sqlite` rather than migrating it in place.
_STATE_VERSION_PATTERN = re.compile(r"^state_(\d+)\.sqlite$")

_QUERY = """
SELECT t.id AS id,
       t.rollout_path AS rollout_path,
       t.created_at AS created_at,
       t.updated_at AS updated_at,
       t.cwd AS cwd,
       t.title AS title,
       t.agent_nickname AS agent_nickname,
       e.parent_thread_id AS parent_thread_id
  FROM threads t
  LEFT JOIN thread_spawn_edges e ON e.child_thread_id = t.id
 WHERE t.updated_at >= ? AND t.created_at < ?
"""

# `archived` is deliberately absent from the filter: archiving is a Codex UI
# state, not a statement that the work did not happen that week.
_ROOT_ONLY_CLAUSE = " AND t.thread_source != 'subagent'"


def find_state_database(home_directory: Path) -> Path | None:
    """Return the highest-versioned `state_<n>.sqlite`, or None if there is none."""

    try:
        entries = list(home_directory.iterdir())
    except OSError:
        return None
    candidates: list[tuple[int, Path]] = []
    for entry in entries:
        match = _STATE_VERSION_PATTERN.match(entry.name)
        if match is not None and entry.is_file():
            candidates.append((int(match.group(1)), entry))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate[0])[1]


def _timestamp(value: object) -> datetime | None:
    # bool is an int subclass; a stray JSON true must not become 1970-01-01.
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return datetime.fromtimestamp(value, tz=UTC)


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def discover_threads(
    database: Path,
    period: DateRange,
    *,
    root_only: bool,
) -> list[SessionDescriptor]:
    """Return descriptors for threads whose activity overlaps the period.

    `created_at` and `updated_at` are unix seconds. The overlap test mirrors the
    Claude Code source's mtime/`created_at` pair: a session counts when it was
    still being written after the period opened and had already started before
    the period closed.

    Raises `sqlite3.Error` when the database cannot be read or its schema has
    drifted, which is the caller's signal to fall back to the rollout scan.
    """

    query = _QUERY + (_ROOT_ONLY_CLAUSE if root_only else "")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            query,
            (int(period.since.timestamp()), int(period.until.timestamp())),
        ).fetchall()
    finally:
        connection.close()

    descriptors: list[SessionDescriptor] = []
    for row in rows:
        session_id = _text(row["id"])
        rollout_path = _text(row["rollout_path"])
        if session_id is None or rollout_path is None:
            continue
        # A missing rollout file is not filtered here on purpose: letting `load`
        # fail turns it into a report warning, which is more visible than a
        # session silently absent from the week.
        descriptors.append(
            SessionDescriptor(
                harness=HARNESS_NAME,
                session_id=session_id,
                source_location=rollout_path,
                title=_text(row["title"]) or _text(row["agent_nickname"]),
                created_at=_timestamp(row["created_at"]),
                updated_at=_timestamp(row["updated_at"]),
                working_directory_hint=_text(row["cwd"]),
                parent_session_id=_text(row["parent_thread_id"]),
            )
        )
    return descriptors
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/harnesses/codex/test_thread_catalog.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Run the linters**

Run: `uv run ruff check . && uv run pyright`
Expected: no findings.

- [ ] **Step 6: Commit**

```bash
git add src/agent_worklog/harnesses/codex tests/unit/harnesses/codex
git commit -m "feat: discover Codex sessions from the state database"
```

---

### Task 3: `rollout_catalog.py` — discovery by scanning rollout files

**Files:**
- Create: `src/agent_worklog/harnesses/codex/rollout_catalog.py`
- Test: `tests/unit/harnesses/codex/test_rollout_catalog.py`

**Interfaces:**
- Consumes: `HARNESS_NAME` from `agent_worklog.harnesses.codex.thread_catalog`.
- Produces:
  - `discover_rollouts(home_directory: Path, period: DateRange, *, root_only: bool) -> list[SessionDescriptor]`
  - `parse_timestamp(value: object) -> datetime | None` — reused by the mapper in Task 5.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/harnesses/codex/test_rollout_catalog.py`:

```python
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from agent_worklog.harnesses.codex.rollout_catalog import discover_rollouts
from agent_worklog.models.time_range import DateRange

TZ = ZoneInfo("Asia/Taipei")
PERIOD = DateRange(
    since=datetime(2026, 7, 20, tzinfo=TZ),
    until=datetime(2026, 7, 27, tzinfo=TZ),
)


def _session_meta(
    session_id: str,
    timestamp: str,
    *,
    cwd: str = "/worktrees/agent",
    thread_source: str = "user",
    parent: str | None = None,
    nickname: str | None = None,
) -> str:
    return json.dumps(
        {
            "timestamp": timestamp,
            "type": "session_meta",
            "payload": {
                "session_id": session_id,
                "timestamp": timestamp,
                "cwd": cwd,
                "thread_source": thread_source,
                "parent_thread_id": parent,
                "agent_nickname": nickname,
            },
        }
    )


def _write(path: Path, lines: list[str], mtime: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    stamp = mtime.timestamp()
    os.utime(path, (stamp, stamp))


@pytest.fixture
def home(tmp_path: Path) -> Path:
    _write(
        tmp_path / "sessions" / "2026" / "07" / "21" / "rollout-root.jsonl",
        [
            _session_meta("root-1", "2026-07-20T17:00:00.000Z"),
            # A resumed session appends a second session_meta; the first wins.
            _session_meta("root-1", "2026-07-24T17:00:00.000Z", cwd="/elsewhere"),
        ],
        mtime=datetime(2026, 7, 22, tzinfo=TZ),
    )
    _write(
        tmp_path / "sessions" / "2026" / "07" / "21" / "rollout-sub.jsonl",
        [
            _session_meta(
                "sub-1",
                "2026-07-20T18:00:00.000Z",
                thread_source="subagent",
                parent="root-1",
                nickname="Ampere",
            )
        ],
        mtime=datetime(2026, 7, 22, tzinfo=TZ),
    )
    _write(
        tmp_path / "archived_sessions" / "rollout-archived.jsonl",
        [_session_meta("archived-1", "2026-07-22T17:00:00.000Z")],
        mtime=datetime(2026, 7, 23, tzinfo=TZ),
    )
    _write(
        tmp_path / "sessions" / "2026" / "07" / "01" / "rollout-stale.jsonl",
        [_session_meta("stale-1", "2026-07-01T17:00:00.000Z")],
        mtime=datetime(2026, 7, 1, tzinfo=TZ),
    )
    return tmp_path


def test_discovers_sessions_and_archived_sessions_in_the_period(home: Path) -> None:
    descriptors = discover_rollouts(home, PERIOD, root_only=False)

    ids = {descriptor.session_id for descriptor in descriptors}
    assert ids == {"root-1", "sub-1", "archived-1"}


def test_root_only_excludes_subagent_rollouts(home: Path) -> None:
    descriptors = discover_rollouts(home, PERIOD, root_only=True)

    assert "sub-1" not in {descriptor.session_id for descriptor in descriptors}


def test_uses_the_first_session_meta_record(home: Path) -> None:
    descriptors = discover_rollouts(home, PERIOD, root_only=False)
    by_id = {descriptor.session_id: descriptor for descriptor in descriptors}

    assert by_id["root-1"].working_directory_hint == "/worktrees/agent"


def test_carries_parent_and_nickname(home: Path) -> None:
    descriptors = discover_rollouts(home, PERIOD, root_only=False)
    by_id = {descriptor.session_id: descriptor for descriptor in descriptors}

    assert by_id["sub-1"].parent_session_id == "root-1"
    assert by_id["sub-1"].title == "Ampere"


def test_missing_directories_are_not_an_error(tmp_path: Path) -> None:
    assert discover_rollouts(tmp_path, PERIOD, root_only=False) == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/harnesses/codex/test_rollout_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_worklog.harnesses.codex.rollout_catalog'`.

- [ ] **Step 3: Write the implementation**

Create `src/agent_worklog/harnesses/codex/rollout_catalog.py`:

```python
"""Discover Codex sessions by scanning rollout files.

The fallback for a machine with no Codex state database, or one whose schema
this version does not understand. It reads the same facts from the first
`session_meta` record of each rollout file, at the cost of opening every file.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_worklog.harnesses.codex.thread_catalog import HARNESS_NAME
from agent_worklog.models.session import SessionDescriptor
from agent_worklog.models.time_range import DateRange

# `session_meta` is the opening record; reading further just to date a file
# would defeat the point of the mtime pre-filter.
_HEAD_RECORD_LIMIT = 50


def parse_timestamp(value: object) -> datetime | None:
    """Parse a Codex ISO-8601 timestamp, assuming UTC when no offset is given."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _rollout_files(home_directory: Path) -> list[Path]:
    files = sorted((home_directory / "sessions").rglob("rollout-*.jsonl"))
    files.extend(sorted((home_directory / "archived_sessions").glob("rollout-*.jsonl")))
    return files


def _first_session_meta(path: Path) -> Mapping[str, Any] | None:
    """Return the first `session_meta` payload.

    A resumed or forked session appends further `session_meta` records — one
    measured file holds 68 — and the later ones describe the resumption, not the
    session, so only the first is authoritative.
    """

    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index >= _HEAD_RECORD_LIMIT:
                    return None
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, Mapping):
                    continue
                if record.get("type") != "session_meta":
                    continue
                payload = record.get("payload")
                return payload if isinstance(payload, Mapping) else None
    except OSError:
        return None
    return None


def discover_rollouts(
    home_directory: Path,
    period: DateRange,
    *,
    root_only: bool,
) -> list[SessionDescriptor]:
    """Return descriptors for rollout files whose activity overlaps the period."""

    descriptors: list[SessionDescriptor] = []
    for path in _rollout_files(home_directory):
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        except OSError:
            continue
        if mtime < period.since:
            continue

        meta = _first_session_meta(path)
        if meta is None:
            continue
        if root_only and meta.get("thread_source") == "subagent":
            continue

        created_at = parse_timestamp(meta.get("timestamp"))
        if created_at is not None and created_at >= period.until:
            continue

        session_id = _text(meta.get("session_id")) or _text(meta.get("id")) or path.stem
        descriptors.append(
            SessionDescriptor(
                harness=HARNESS_NAME,
                session_id=session_id,
                source_location=str(path),
                title=_text(meta.get("agent_nickname")),
                created_at=created_at,
                updated_at=mtime,
                working_directory_hint=_text(meta.get("cwd")),
                parent_session_id=_text(meta.get("parent_thread_id")),
            )
        )
    return descriptors
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/harnesses/codex/test_rollout_catalog.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/agent_worklog/harnesses/codex/rollout_catalog.py tests/unit/harnesses/codex/test_rollout_catalog.py
git commit -m "feat: add the Codex rollout-scan discovery fallback"
```

---

### Task 4: `source.py` — path selection and loading

**Files:**
- Create: `src/agent_worklog/harnesses/codex/source.py`
- Test: `tests/unit/harnesses/codex/test_source.py`

**Interfaces:**
- Consumes: `find_state_database`, `discover_threads` (Task 2); `discover_rollouts` (Task 3); `CodexRolloutMapper` (Task 5).
- Produces:
  - `class CodexSource(HarnessSessionSource)` with `__init__(self, *, home_directory: Path, root_only: bool = False)`
  - `describe_discovery(home_directory: Path) -> str` — returns `"state_5.sqlite"` or `"directory scan"`, used by `doctor` in Task 8.

**Note for the implementer:** Task 5 creates `CodexRolloutMapper`. Until Task 5 lands, `load` cannot be exercised, so this task's tests cover `discover` and `describe_discovery` only, and the `load` tests live in Task 5.

**Deliberate divergence from spec §9:** the spec's error table says an unreadable state database should produce a warning as well as falling back. `ScanService` collects warnings only from `load`, so emitting one from `discover` would mean a new interface between the source and the service for a single message. The fallback is silent instead, and `describe_discovery` makes it visible where it matters — `doctor` names the discovery path before a report is ever run. Do not add a warnings channel for this.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/harnesses/codex/test_source.py`:

```python
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from agent_worklog.errors import HarnessSourceError
from agent_worklog.harnesses.codex.source import CodexSource, describe_discovery
from agent_worklog.models.time_range import DateRange

TZ = ZoneInfo("Asia/Taipei")
PERIOD = DateRange(
    since=datetime(2026, 7, 20, tzinfo=TZ),
    until=datetime(2026, 7, 27, tzinfo=TZ),
)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    rollout = tmp_path / "sessions" / "2026" / "07" / "21" / "rollout-root.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text(
        '{"timestamp":"2026-07-20T17:00:00.000Z","type":"session_meta",'
        '"payload":{"session_id":"root-1","timestamp":"2026-07-20T17:00:00.000Z",'
        '"cwd":"/worktrees/agent","thread_source":"user"}}\n',
        encoding="utf-8",
    )
    import os

    stamp = datetime(2026, 7, 22, tzinfo=TZ).timestamp()
    os.utime(rollout, (stamp, stamp))
    return tmp_path


def test_missing_home_directory_is_a_harness_error(tmp_path: Path) -> None:
    source = CodexSource(home_directory=tmp_path / "absent")

    with pytest.raises(HarnessSourceError):
        source.discover(PERIOD)


def test_falls_back_to_the_rollout_scan_without_a_database(home: Path) -> None:
    descriptors = CodexSource(home_directory=home).discover(PERIOD)

    assert [descriptor.session_id for descriptor in descriptors] == ["root-1"]


def test_falls_back_to_the_rollout_scan_on_schema_drift(home: Path) -> None:
    connection = sqlite3.connect(home / "state_5.sqlite")
    connection.execute("CREATE TABLE unrelated (id TEXT)")
    connection.commit()
    connection.close()

    descriptors = CodexSource(home_directory=home).discover(PERIOD)

    assert [descriptor.session_id for descriptor in descriptors] == ["root-1"]


def test_describes_the_discovery_path(home: Path) -> None:
    assert describe_discovery(home) == "directory scan"

    (home / "state_5.sqlite").write_text("", encoding="utf-8")

    assert describe_discovery(home) == "state_5.sqlite"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/harnesses/codex/test_source.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_worklog.harnesses.codex.source'`.

- [ ] **Step 3: Write the implementation**

Create `src/agent_worklog/harnesses/codex/source.py`:

```python
"""Codex session discovery and loading."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agent_worklog.errors import HarnessSourceError, SessionParseError
from agent_worklog.harnesses.base import HarnessSessionSource
from agent_worklog.harnesses.codex.mapper import CodexRolloutMapper
from agent_worklog.harnesses.codex.rollout_catalog import discover_rollouts
from agent_worklog.harnesses.codex.thread_catalog import (
    discover_threads,
    find_state_database,
)
from agent_worklog.models.session import AgentSession, SessionDescriptor
from agent_worklog.models.time_range import DateRange


def describe_discovery(home_directory: Path) -> str:
    """Name the discovery path `doctor` will take, so a fallback is visible."""

    database = find_state_database(home_directory)
    return database.name if database is not None else "directory scan"


def _iter_records(text: str) -> list[Mapping[str, Any]]:
    records: list[Mapping[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            # Codex appends live, so the final line can be torn. Skipping it
            # keeps the rest of the session usable.
            continue
        if isinstance(record, Mapping):
            records.append(record)
    return records


class CodexSource(HarnessSessionSource):
    """Read Codex sessions, preferring the state database over a directory scan."""

    def __init__(self, *, home_directory: Path, root_only: bool = False) -> None:
        self._home_directory = home_directory
        self._root_only = root_only

    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        if not self._home_directory.is_dir():
            raise HarnessSourceError(
                f"Codex home directory not found: {self._home_directory}"
            )

        database = find_state_database(self._home_directory)
        if database is not None:
            try:
                return discover_threads(
                    database, period, root_only=self._root_only
                )
            except sqlite3.Error:
                # A drifted schema or a locked database must not lose the week's
                # work: the rollout files carry the same facts, only slower.
                pass

        return discover_rollouts(
            self._home_directory, period, root_only=self._root_only
        )

    def load(self, descriptor: SessionDescriptor) -> AgentSession:
        if descriptor.source_location is None:
            raise SessionParseError(
                f"Codex session {descriptor.session_id} has no source location"
            )
        path = Path(descriptor.source_location)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise SessionParseError(
                f"Codex rollout unreadable for {descriptor.session_id}: {exc}"
            ) from exc
        return CodexRolloutMapper().map(_iter_records(text), descriptor)
```

- [ ] **Step 4: Create a placeholder mapper so the import resolves**

Task 5 replaces this file wholesale. Create `src/agent_worklog/harnesses/codex/mapper.py` with just enough to import:

```python
"""Map Codex rollout JSONL records into canonical session models."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent_worklog.models.session import AgentSession, SessionDescriptor


class CodexRolloutMapper:
    """Convert Codex rollout records to an AgentSession."""

    def map(
        self,
        records: list[Mapping[str, Any]],
        descriptor: SessionDescriptor,
    ) -> AgentSession:
        return AgentSession(
            harness="codex",
            session_id=descriptor.session_id,
            parent_session_id=descriptor.parent_session_id,
            title=descriptor.title,
            created_at=descriptor.created_at,
            updated_at=descriptor.updated_at,
            working_directory=descriptor.working_directory_hint,
        )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/unit/harnesses/codex/ -v`
Expected: PASS (17 tests across the three files).

- [ ] **Step 6: Commit**

```bash
git add src/agent_worklog/harnesses/codex/source.py src/agent_worklog/harnesses/codex/mapper.py tests/unit/harnesses/codex/test_source.py
git commit -m "feat: add the Codex session source with a discovery fallback"
```

---

### Task 5: `mapper.py` — activities

**Files:**
- Modify: `src/agent_worklog/harnesses/codex/mapper.py` (replaces the Task 4 placeholder)
- Test: `tests/unit/harnesses/codex/test_mapper.py`

**Interfaces:**
- Consumes: `parse_timestamp` from `agent_worklog.harnesses.codex.rollout_catalog`.
- Produces: `CodexRolloutMapper.map(records: list[Mapping[str, Any]], descriptor: SessionDescriptor) -> AgentSession`, emitting `SessionActivity` objects. Task 6 adds usage to the same class.

**Why the content rules matter:** `COMMAND_TOOL_NAMES` in `extraction/rules.py:30` already contains `"exec"`, and `FILE_TOOL_NAMES` on line 29 already contains `"apply_patch"`. An `exec` activity whose `content` held the JavaScript would therefore be extracted as a shell command and copied into the report and into outbound LLM requests. Empty content is what stops it, at `pipeline.py:228` (`if is_command and content`) and `pipeline.py:277` (`if path`).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/harnesses/codex/test_mapper.py`:

```python
from datetime import datetime
from typing import Any

from agent_worklog.harnesses.codex.mapper import CodexRolloutMapper
from agent_worklog.models.session import ActivityType, SessionDescriptor

DESCRIPTOR = SessionDescriptor(
    harness="codex",
    session_id="thread-1",
    source_location="/rollouts/thread-1.jsonl",
    title="Add retry",
    working_directory_hint="/worktrees/agent",
)


def _record(timestamp: str, record_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"timestamp": timestamp, "type": record_type, "payload": payload}


def _map(records: list[dict[str, Any]]):
    return CodexRolloutMapper().map(records, DESCRIPTOR)


def test_user_messages_become_user_activities() -> None:
    session = _map(
        [
            _record(
                "2026-07-21T01:00:00.000Z",
                "event_msg",
                {"type": "user_message", "message": "Add retry to the price fetcher"},
            )
        ]
    )

    assert [activity.activity_type for activity in session.activities] == [
        ActivityType.USER_MESSAGE
    ]
    assert session.activities[0].content == "Add retry to the price fetcher"
    assert session.activities[0].timestamp == datetime.fromisoformat(
        "2026-07-21T01:00:00+00:00"
    )


def test_agent_messages_become_assistant_activities() -> None:
    session = _map(
        [
            _record(
                "2026-07-21T01:00:01.000Z",
                "event_msg",
                {"type": "agent_message", "message": "I implemented the retry."},
            )
        ]
    )

    assert session.activities[0].activity_type == ActivityType.ASSISTANT_MESSAGE
    assert session.activities[0].content == "I implemented the retry."


def test_exec_command_becomes_a_command_activity() -> None:
    session = _map(
        [
            _record(
                "2026-07-21T01:00:02.000Z",
                "response_item",
                {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "call-1",
                    "arguments": '{"cmd": "pytest -q", "workdir": "/worktrees/agent"}',
                },
            )
        ]
    )

    activity = session.activities[0]
    assert activity.activity_type == ActivityType.COMMAND
    assert activity.content == "pytest -q"
    assert activity.tool_name == "exec_command"
    assert activity.tool_call_id == "call-1"
    assert activity.metadata["workdir"] == "/worktrees/agent"


def test_no_outcome_signal_is_ever_recorded() -> None:
    session = _map(
        [
            _record(
                "2026-07-21T01:00:02.000Z",
                "response_item",
                {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "call-1",
                    "arguments": '{"cmd": "pytest -q"}',
                },
            )
        ]
    )

    metadata = session.activities[0].metadata
    assert "exit_code" not in metadata
    assert "stderr_empty" not in metadata


def test_exec_javascript_never_reaches_activity_content() -> None:
    javascript = 'const r = await tools.exec_command({"cmd":"rm -rf /"}); text(r);'
    session = _map(
        [
            _record(
                "2026-07-21T01:00:03.000Z",
                "response_item",
                {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": "call-2",
                    "input": javascript,
                },
            )
        ]
    )

    activity = session.activities[0]
    assert activity.activity_type == ActivityType.TOOL_CALL
    assert activity.content == ""
    assert activity.tool_name == "exec"
    assert javascript not in str(session.model_dump())


def test_applied_patches_become_one_file_change_per_path() -> None:
    session = _map(
        [
            _record(
                "2026-07-21T01:00:04.000Z",
                "event_msg",
                {
                    "type": "patch_apply_end",
                    "call_id": "call-3",
                    "success": True,
                    "changes": {
                        "/worktrees/agent/src/fetch.py": {
                            "type": "update",
                            "content": "SECRET_FILE_BODY",
                        },
                        "/worktrees/agent/tests/test_fetch.py": {
                            "type": "add",
                            "content": "SECRET_FILE_BODY",
                        },
                    },
                },
            )
        ]
    )

    paths = [activity.content for activity in session.activities]
    assert sorted(paths) == [
        "/worktrees/agent/src/fetch.py",
        "/worktrees/agent/tests/test_fetch.py",
    ]
    assert all(
        activity.activity_type == ActivityType.FILE_CHANGE
        for activity in session.activities
    )
    assert len({activity.activity_id for activity in session.activities}) == 2
    assert "SECRET_FILE_BODY" not in str(session.model_dump())


def test_failed_patches_produce_no_file_change() -> None:
    session = _map(
        [
            _record(
                "2026-07-21T01:00:05.000Z",
                "event_msg",
                {
                    "type": "patch_apply_end",
                    "call_id": "call-4",
                    "success": False,
                    "changes": {"/worktrees/agent/src/fetch.py": {"type": "update"}},
                },
            )
        ]
    )

    assert session.activities == []


def test_working_directory_follows_the_last_turn_context() -> None:
    session = _map(
        [
            _record(
                "2026-07-21T01:00:00.000Z",
                "session_meta",
                {"session_id": "thread-1", "cwd": "/worktrees/agent"},
            ),
            _record(
                "2026-07-21T01:00:06.000Z",
                "turn_context",
                {"turn_id": "t-1", "cwd": "/worktrees/assets", "model": "gpt-5.6-sol"},
            ),
        ]
    )

    assert session.working_directory == "/worktrees/assets"


def test_session_identity_comes_from_the_descriptor() -> None:
    session = _map([])

    assert session.harness == "codex"
    assert session.session_id == "thread-1"
    assert session.title == "Add retry"
    assert session.working_directory == "/worktrees/agent"


def test_torn_records_do_not_stop_the_mapping() -> None:
    session = _map(
        [
            {"timestamp": "2026-07-21T01:00:00.000Z", "type": "event_msg"},
            _record(
                "2026-07-21T01:00:01.000Z",
                "event_msg",
                {"type": "agent_message", "message": "still mapped"},
            ),
        ]
    )

    assert [activity.content for activity in session.activities] == ["still mapped"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/harnesses/codex/test_mapper.py -v`
Expected: FAIL — the placeholder mapper emits no activities, so every assertion about `session.activities` fails.

- [ ] **Step 3: Write the implementation**

Replace `src/agent_worklog/harnesses/codex/mapper.py` with:

```python
"""Map Codex rollout JSONL records into canonical session models."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from agent_worklog.harnesses.codex.rollout_catalog import parse_timestamp
from agent_worklog.models.session import (
    ActivityType,
    AgentSession,
    SessionActivity,
    SessionDescriptor,
)

HARNESS_NAME = "codex"

# The one Codex tool whose arguments name a command as a field. `exec` is a
# general JavaScript sandbox — its input calls MCP tools, drives a browser, or
# loops over `tools.exec_command` — so it is not a command source. A strict parse
# for a single wrapped `exec_command` call matched 0 of 4,963 measured `exec`
# calls, which is why none is attempted.
_COMMAND_TOOL = "exec_command"

_TOOL_CALL_TYPES = frozenset({"function_call", "custom_tool_call"})


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _tool_arguments(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a `function_call`'s parsed arguments.

    A `custom_tool_call` carries free-form `input` instead, which is never parsed
    — see `_COMMAND_TOOL`.
    """

    raw = payload.get("arguments")
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, Mapping) else {}


class CodexRolloutMapper:
    """Convert Codex rollout records to an AgentSession, dropping raw output.

    Two things never leave this mapper: the JavaScript an `exec` call carries,
    and the file bodies a `patch_apply_end` record carries in
    `changes[path].content`. Codex has no `--sanitize` upstream, and the
    300-character evidence cap downstream is a backstop, not a reason to carry
    them this far.
    """

    def map(
        self,
        records: list[Mapping[str, Any]],
        descriptor: SessionDescriptor,
    ) -> AgentSession:
        activities: list[SessionActivity] = []
        working_directory: str | None = None
        first_timestamp: datetime | None = None
        last_timestamp: datetime | None = None

        for index, record in enumerate(records):
            payload = _as_mapping(record.get("payload"))
            if not payload:
                continue
            record_type = record.get("type")
            timestamp = parse_timestamp(record.get("timestamp"))
            if timestamp is not None:
                if first_timestamp is None:
                    first_timestamp = timestamp
                last_timestamp = timestamp

            if record_type in {"session_meta", "turn_context"}:
                # A session can move between worktrees; the last one is where the
                # work ended, which is what the repository resolver should see.
                working_directory = _text(payload.get("cwd")) or working_directory
                continue

            if record_type == "event_msg":
                activities.extend(
                    self._event_activities(
                        payload=payload,
                        record_index=index,
                        timestamp=timestamp,
                    )
                )
                continue

            if record_type == "response_item" and payload.get("type") in _TOOL_CALL_TYPES:
                activity = self._tool_activity(
                    payload=payload,
                    record_index=index,
                    timestamp=timestamp,
                )
                if activity is not None:
                    activities.append(activity)

        return AgentSession(
            harness=HARNESS_NAME,
            session_id=descriptor.session_id,
            parent_session_id=descriptor.parent_session_id,
            title=descriptor.title,
            created_at=first_timestamp or descriptor.created_at,
            updated_at=last_timestamp or descriptor.updated_at,
            working_directory=working_directory or descriptor.working_directory_hint,
            project_id_hint=descriptor.project_id_hint,
            activities=activities,
        )

    def _event_activities(
        self,
        *,
        payload: Mapping[str, Any],
        record_index: int,
        timestamp: datetime | None,
    ) -> list[SessionActivity]:
        event_type = payload.get("type")

        if event_type in {"user_message", "agent_message"}:
            message = _text(payload.get("message"))
            if message is None:
                return []
            activity_type = (
                ActivityType.USER_MESSAGE
                if event_type == "user_message"
                else ActivityType.ASSISTANT_MESSAGE
            )
            return [
                SessionActivity(
                    activity_id=str(record_index),
                    activity_type=activity_type,
                    timestamp=timestamp,
                    content=message,
                )
            ]

        if event_type == "patch_apply_end":
            # `success` is the only structured outcome signal Codex records.
            # A failed patch changed nothing, so listing its paths under Key
            # Files would be wrong.
            if payload.get("success") is not True:
                return []
            changes = _as_mapping(payload.get("changes"))
            call_id = _text(payload.get("call_id")) or str(record_index)
            activities: list[SessionActivity] = []
            # Only the keys. Each value holds the whole file body.
            for offset, path in enumerate(changes):
                if not isinstance(path, str) or not path.strip():
                    continue
                activities.append(
                    SessionActivity(
                        activity_id=f"{call_id}:{offset}",
                        activity_type=ActivityType.FILE_CHANGE,
                        timestamp=timestamp,
                        content=path.strip(),
                    )
                )
            return activities

        return []

    def _tool_activity(
        self,
        *,
        payload: Mapping[str, Any],
        record_index: int,
        timestamp: datetime | None,
    ) -> SessionActivity | None:
        name = _text(payload.get("name"))
        call_id = _text(payload.get("call_id")) or str(record_index)

        if name == _COMMAND_TOOL:
            arguments = _tool_arguments(payload)
            command = _text(arguments.get("cmd"))
            if command is None:
                return None
            metadata: dict[str, object] = {}
            workdir = _text(arguments.get("workdir"))
            if workdir is not None:
                metadata["workdir"] = workdir
            # No `exit_code` and no `stderr_empty`: Codex records exit codes only
            # inside free-form output text, in at least three formats, and a regex
            # over that would fail silently the day Codex changes it. Their absence
            # routes every command through `pipeline.py:264`, which claims nothing.
            return SessionActivity(
                activity_id=call_id,
                activity_type=ActivityType.COMMAND,
                timestamp=timestamp,
                content=command,
                tool_name=name,
                tool_call_id=call_id,
                metadata=metadata,
            )

        # Every other tool, `exec` included, is recorded with empty content. The
        # activity still exists because Task 6's usage rides on activities, and a
        # turn made only of tool calls would otherwise vanish from the usage table.
        return SessionActivity(
            activity_id=call_id,
            activity_type=ActivityType.TOOL_CALL,
            timestamp=timestamp,
            content="",
            tool_name=name,
            tool_call_id=call_id,
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/harnesses/codex/test_mapper.py -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Run the full suite and linters**

Run: `uv run pytest -q && uv run ruff check . && uv run pyright`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/agent_worklog/harnesses/codex/mapper.py tests/unit/harnesses/codex/test_mapper.py
git commit -m "feat: map Codex rollout records into canonical activities"
```

---

### Task 6: `mapper.py` — token usage

**Files:**
- Modify: `src/agent_worklog/harnesses/codex/mapper.py`
- Test: `tests/unit/harnesses/codex/test_mapper.py` (append)

**Interfaces:**
- Consumes: `CodexRolloutMapper` from Task 5.
- Produces: activities carrying `metadata["model"]: str` and `metadata["usage"]: dict[str, int]` with keys `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`; and `AgentSession.token_usage` as a `TokenUsage` with `semantics=UsageSemantics.INCREMENTAL`. This is the exact shape `renderers/usage.py` reads in Task 7.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/harnesses/codex/test_mapper.py`:

```python
def _token_count(timestamp: str, total: dict[str, int]) -> dict[str, Any]:
    return _record(
        timestamp,
        "event_msg",
        {"type": "token_count", "info": {"total_token_usage": total}},
    )


def _turn_context(timestamp: str, model: str) -> dict[str, Any]:
    return _record(timestamp, "turn_context", {"turn_id": "t", "model": model})


def test_usage_is_the_delta_of_the_running_total() -> None:
    session = _map(
        [
            _turn_context("2026-07-21T01:00:00.000Z", "gpt-5.6-sol"),
            _record(
                "2026-07-21T01:00:01.000Z",
                "event_msg",
                {"type": "agent_message", "message": "first"},
            ),
            _token_count(
                "2026-07-21T01:00:02.000Z",
                {
                    "input_tokens": 100,
                    "output_tokens": 10,
                    "cached_input_tokens": 40,
                    "cache_write_input_tokens": 5,
                },
            ),
            _record(
                "2026-07-21T01:00:03.000Z",
                "event_msg",
                {"type": "agent_message", "message": "second"},
            ),
            _token_count(
                "2026-07-21T01:00:04.000Z",
                {
                    "input_tokens": 250,
                    "output_tokens": 30,
                    "cached_input_tokens": 90,
                    "cache_write_input_tokens": 5,
                },
            ),
        ]
    )

    first, second = session.activities
    assert first.metadata["usage"] == {
        "input_tokens": 100,
        "output_tokens": 10,
        "cache_read_tokens": 40,
        "cache_write_tokens": 5,
    }
    # The second turn's delta, not its running total.
    assert second.metadata["usage"] == {
        "input_tokens": 150,
        "output_tokens": 20,
        "cache_read_tokens": 50,
    }
    assert session.token_usage.input_tokens == 250
    assert session.token_usage.output_tokens == 30
    assert session.token_usage.cache_read_tokens == 90
    assert session.token_usage.cache_write_tokens == 5


def test_a_reset_running_total_is_taken_at_face_value() -> None:
    session = _map(
        [
            _turn_context("2026-07-21T01:00:00.000Z", "gpt-5.6-sol"),
            _record(
                "2026-07-21T01:00:01.000Z",
                "event_msg",
                {"type": "agent_message", "message": "first"},
            ),
            _token_count(
                "2026-07-21T01:00:02.000Z", {"input_tokens": 500, "output_tokens": 50}
            ),
            _record(
                "2026-07-21T01:00:03.000Z",
                "event_msg",
                {"type": "agent_message", "message": "after compaction"},
            ),
            _token_count(
                "2026-07-21T01:00:04.000Z", {"input_tokens": 20, "output_tokens": 3}
            ),
        ]
    )

    assert session.activities[1].metadata["usage"] == {
        "input_tokens": 20,
        "output_tokens": 3,
    }


def test_usage_follows_the_model_the_turn_context_names() -> None:
    session = _map(
        [
            _turn_context("2026-07-21T01:00:00.000Z", "gpt-5.6-sol"),
            _record(
                "2026-07-21T01:00:01.000Z",
                "event_msg",
                {"type": "agent_message", "message": "first"},
            ),
            _token_count("2026-07-21T01:00:02.000Z", {"output_tokens": 10}),
            _turn_context("2026-07-21T01:00:03.000Z", "gpt-5.6-terra"),
            _record(
                "2026-07-21T01:00:04.000Z",
                "event_msg",
                {"type": "agent_message", "message": "second"},
            ),
            _token_count("2026-07-21T01:00:05.000Z", {"output_tokens": 25}),
        ]
    )

    assert session.activities[0].metadata["model"] == "gpt-5.6-sol"
    assert session.activities[1].metadata["model"] == "gpt-5.6-terra"


def test_usage_with_no_activity_yet_joins_the_next_one() -> None:
    session = _map(
        [
            _turn_context("2026-07-21T01:00:00.000Z", "gpt-5.6-sol"),
            _token_count("2026-07-21T01:00:01.000Z", {"output_tokens": 40}),
            _record(
                "2026-07-21T01:00:02.000Z",
                "event_msg",
                {"type": "agent_message", "message": "after the reasoning"},
            ),
            _token_count("2026-07-21T01:00:03.000Z", {"output_tokens": 60}),
        ]
    )

    assert session.activities[0].metadata["usage"] == {"output_tokens": 60}


def test_trailing_usage_joins_the_last_activity_of_that_model() -> None:
    session = _map(
        [
            _turn_context("2026-07-21T01:00:00.000Z", "gpt-5.6-sol"),
            _record(
                "2026-07-21T01:00:01.000Z",
                "event_msg",
                {"type": "agent_message", "message": "answer"},
            ),
            _token_count("2026-07-21T01:00:02.000Z", {"output_tokens": 10}),
            # A trailing reasoning-only turn emits no activity of its own.
            _token_count("2026-07-21T01:00:03.000Z", {"output_tokens": 18}),
        ]
    )

    assert session.activities[0].metadata["usage"] == {"output_tokens": 18}


def test_reasoning_output_tokens_are_not_counted_twice() -> None:
    session = _map(
        [
            _turn_context("2026-07-21T01:00:00.000Z", "gpt-5.6-sol"),
            _record(
                "2026-07-21T01:00:01.000Z",
                "event_msg",
                {"type": "agent_message", "message": "answer"},
            ),
            _token_count(
                "2026-07-21T01:00:02.000Z",
                {"output_tokens": 100, "reasoning_output_tokens": 40},
            ),
        ]
    )

    assert session.activities[0].metadata["usage"] == {"output_tokens": 100}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/harnesses/codex/test_mapper.py -k usage -v`
Expected: FAIL with `KeyError: 'usage'` — the mapper ignores `token_count` records.

- [ ] **Step 3: Write the implementation**

In `src/agent_worklog/harnesses/codex/mapper.py`, add to the imports:

```python
from agent_worklog.models.session import (
    ActivityType,
    AgentSession,
    SessionActivity,
    SessionDescriptor,
    TokenUsage,
    UsageSemantics,
)
```

Add the module-level constants and helpers after `_TOOL_CALL_TYPES`:

```python
# Canonical name -> Codex `total_token_usage` key. `reasoning_output_tokens` is
# deliberately absent: it is a subset of `output_tokens`, so counting it would
# double the reasoning tokens in every row of the usage table.
_USAGE_FIELDS = {
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "cache_read_tokens": "cached_input_tokens",
    "cache_write_tokens": "cache_write_input_tokens",
}
```

```python
def _int_value(value: object) -> int | None:
    # bool is an int subclass; a JSON true would otherwise add 1 to a token total.
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _accumulate(target: dict[str, int], source: Mapping[str, int]) -> dict[str, int]:
    for key, value in source.items():
        target[key] = target.get(key, 0) + value
    return target


def _usage_delta(
    total: Mapping[str, Any],
    previous: dict[str, int],
) -> dict[str, int]:
    """Return one turn's usage from Codex's running totals.

    Summing `last_token_usage` instead over-counts: Codex emits some
    `token_count` events more than once, which on one measured session inflated
    the sum to 2,635,327 against Codex's own total of 2,540,568. Differencing the
    running total reproduces that total exactly, and still attributes the tokens
    to a point in the session so period filtering can narrow them.

    A total that has gone backwards means Codex reset it — a fork or a context
    compaction — so the raw value is taken as that turn's usage.
    """

    values: dict[str, int] = {}
    reset = False
    for canonical, source_key in _USAGE_FIELDS.items():
        value = _int_value(total.get(source_key))
        if value is None:
            continue
        values[canonical] = value
        if value < previous.get(canonical, 0):
            reset = True

    delta = {
        canonical: value if reset else value - previous.get(canonical, 0)
        for canonical, value in values.items()
    }
    previous.update(values)
    return {canonical: value for canonical, value in delta.items() if value}
```

In `map`, add the usage state beside the existing locals:

```python
        totals: dict[str, int] = {}
        previous_total: dict[str, int] = {}
        pending_usage: dict[str, dict[str, int]] = {}
        attached_usage: dict[str, dict[str, int]] = {}
        model: str | None = None
```

Change the `session_meta` / `turn_context` branch to also read the model:

```python
            if record_type in {"session_meta", "turn_context"}:
                # A session can move between worktrees; the last one is where the
                # work ended, which is what the repository resolver should see.
                working_directory = _text(payload.get("cwd")) or working_directory
                # The model changes mid-session — one measured session alternates
                # between two — so the turn's own context beats the thread's.
                model = _text(payload.get("model")) or model
                continue
```

Inside the `event_msg` branch, handle `token_count` before delegating:

```python
            if record_type == "event_msg":
                if payload.get("type") == "token_count":
                    delta = _usage_delta(
                        _as_mapping(_as_mapping(payload.get("info")).get(
                            "total_token_usage"
                        )),
                        previous_total,
                    )
                    if delta:
                        _accumulate(totals, delta)
                        self._attach_usage(
                            delta=delta,
                            model=model,
                            activities=activities,
                            pending_usage=pending_usage,
                            attached_usage=attached_usage,
                        )
                    continue
                activities.extend(
                    self._event_activities(
                        payload=payload,
                        record_index=index,
                        timestamp=timestamp,
                    )
                )
                continue
```

Add the attachment helper to the class:

```python
    @staticmethod
    def _attach_usage(
        *,
        delta: dict[str, int],
        model: str | None,
        activities: list[SessionActivity],
        pending_usage: dict[str, dict[str, int]],
        attached_usage: dict[str, dict[str, int]],
    ) -> None:
        """Hang one turn's usage on an activity so period filtering can see it.

        A model that has not been named yet — usage before the first
        `turn_context` — still reaches `AgentSession.token_usage`, but cannot
        reach the per-model table, which reads activities.
        """

        if model is None:
            return
        carrier = activities[-1] if activities else None
        if carrier is not None and "usage" not in carrier.metadata:
            usage = _accumulate(pending_usage.pop(model, {}), delta)
            carrier.metadata["model"] = model
            carrier.metadata["usage"] = usage
            attached_usage[model] = usage
            return
        _accumulate(pending_usage.setdefault(model, {}), delta)
```

Before building the `AgentSession`, drain what is still pending:

```python
        # Usage still held when the rollout ends — a session whose last turns
        # were reasoning-only — joins the last activity that carried the same
        # model, so the table's total matches the session's own total.
        for pending_model, leftover in pending_usage.items():
            attached = attached_usage.get(pending_model)
            if attached is not None:
                _accumulate(attached, leftover)
```

and add `token_usage` to the returned session:

```python
            activities=activities,
            token_usage=TokenUsage(
                semantics=UsageSemantics.INCREMENTAL,
                input_tokens=totals.get("input_tokens"),
                output_tokens=totals.get("output_tokens"),
                cache_read_tokens=totals.get("cache_read_tokens"),
                cache_write_tokens=totals.get("cache_write_tokens"),
            ),
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/harnesses/codex/test_mapper.py -v`
Expected: PASS (16 tests).

- [ ] **Step 5: Commit**

```bash
git add src/agent_worklog/harnesses/codex/mapper.py tests/unit/harnesses/codex/test_mapper.py
git commit -m "feat: derive Codex token usage from its running totals"
```

---

### Task 7: Move the usage renderer out of the Claude Code package

**Files:**
- Create: `src/agent_worklog/renderers/usage.py`
- Delete: `src/agent_worklog/harnesses/claude_code/usage.py`
- Modify: `src/agent_worklog/cli.py:24`, `src/agent_worklog/cli.py:177-192`
- Move: `tests/unit/harnesses/claude_code/test_usage.py` → `tests/unit/renderers/test_usage.py`

**Interfaces:**
- Consumes: `ScanResult` from `agent_worklog.services.scan`.
- Produces: `render_activity_usage(scan: ScanResult, *, harness: str) -> str` — the same aligned per-model table as before, with the harness name in the "no usage" error message.

**Behaviour must not change.** The Claude Code acceptance test pins four usage numbers and must keep passing untouched.

- [ ] **Step 1: Move the module and rename the function**

```bash
git mv src/agent_worklog/harnesses/claude_code/usage.py src/agent_worklog/renderers/usage.py
git mv tests/unit/harnesses/claude_code/test_usage.py tests/unit/renderers/test_usage.py
```

In `src/agent_worklog/renderers/usage.py`, change the module docstring and the public function:

```python
"""Aggregate per-model token usage from mapped session activities.

Harness-agnostic: it reads only `activity.metadata["model"]` and
`activity.metadata["usage"]`, which the Claude Code and Codex mappers both
populate. OpenCode does not use this — `opencode stats` reports its own totals.
"""
```

```python
def render_activity_usage(scan: ScanResult, *, harness: str) -> str:
    """Return an aligned per-model token table for the scanned sessions.

    Unlike `opencode stats`, this needs no trailing window: usage rides on the
    activities that `filter_session_to_period` already narrowed, so the table
    covers the report period instead of one ending at generation time.

    It is exact to the activity rather than to the second. Usage from a model
    turn that emitted no activity of its own is carried by a neighbouring
    activity from the same model, so a turn sitting on the period boundary can
    be counted on the other side of it.
    """

    totals = _totals_by_model(scan)
    if not totals:
        raise HarnessSourceError(f"{harness} sessions carried no token usage")
```

Update the `_totals_by_model` comment, which currently names only Claude Code:

```python
    # Claude Code writes `model: "<synthetic>"` for local and error placeholders,
    # and a Codex turn can report a zero delta; either would otherwise add a row
    # that reports nothing.
    return {model: row for model, row in totals.items() if any(row.values())}
```

- [ ] **Step 2: Update the callers**

In `src/agent_worklog/cli.py`, replace the import on line 24:

```python
from agent_worklog.renderers.usage import render_activity_usage
```

and the Claude Code branch of `_usage_provider`:

```python
    if harness is Harness.CLAUDE_CODE:
        # Usage rides on the already-filtered activities, so the window is exact
        # and needs no "wider than the period" caveat.
        return partial(render_activity_usage, harness=harness.value), None
```

Add `from functools import partial` to the imports.

- [ ] **Step 3: Update the moved test**

In `tests/unit/renderers/test_usage.py`, update the import and every call site:

```python
from agent_worklog.renderers.usage import render_activity_usage
```

Each `render_claude_code_usage(scan)` becomes `render_activity_usage(scan, harness="claude-code")`. In the test that asserts the empty-usage error, assert the message now names the harness:

```python
    with pytest.raises(HarnessSourceError, match="claude-code sessions carried no"):
        render_activity_usage(scan, harness="claude-code")
```

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q && uv run ruff check . && uv run pyright`
Expected: all green, including `tests/integration/test_claude_code_end_to_end.py`, which is unmodified and proves the rendered output is byte-identical.

- [ ] **Step 5: Commit**

```bash
git add -A src/agent_worklog tests
git commit -m "refactor: share the activity usage table between harnesses"
```

---

### Task 8: Wire Codex into the CLI and `doctor`

**Files:**
- Modify: `src/agent_worklog/cli.py:142-197`, `src/agent_worklog/cli.py:258-278`
- Modify: `src/agent_worklog/services/doctor.py:39-64`
- Test: `tests/unit/services/test_doctor.py` (append), `tests/integration/test_cli.py` (append)

**Interfaces:**
- Consumes: `CodexSource`, `describe_discovery` (Task 4); `render_activity_usage` (Task 7).
- Produces: `--harness codex` accepted by `doctor`, `scan` and `report`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/services/test_doctor.py`:

```python
def test_codex_doctor_reports_the_home_directory_and_discovery_path(
    tmp_path, monkeypatch, fake_runner
) -> None:
    monkeypatch.setenv(
        "AGENT_WORKLOG_HARNESSES__CODEX__HOME_DIRECTORY", str(tmp_path)
    )
    (tmp_path / "state_5.sqlite").write_text("", encoding="utf-8")
    settings = AppSettings()

    result = run_doctor(settings, runner=fake_runner, harness="codex")

    check = result.checks[0]
    assert check.name == "codex home directory"
    assert check.ok is True
    assert check.detail == f"{tmp_path} (state_5.sqlite)"


def test_codex_doctor_fails_on_a_missing_home_directory(
    tmp_path, monkeypatch, fake_runner
) -> None:
    monkeypatch.setenv(
        "AGENT_WORKLOG_HARNESSES__CODEX__HOME_DIRECTORY", str(tmp_path / "absent")
    )
    settings = AppSettings()

    result = run_doctor(settings, runner=fake_runner, harness="codex")

    assert result.checks[0].ok is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/services/test_doctor.py -v`
Expected: FAIL — `run_doctor` falls into the OpenCode branch and returns an `opencode version` check.

- [ ] **Step 3: Add the doctor branch**

In `src/agent_worklog/services/doctor.py`, add the import and the branch:

```python
from agent_worklog.harnesses.codex.source import describe_discovery
```

```python
    if harness == "claude-code":
        directory = settings.harnesses.claude_code.projects_directory
        readable = directory.is_dir() and os.access(directory, os.R_OK)
        checks.append(
            DoctorCheck(
                name="claude code projects directory",
                ok=readable,
                detail=str(directory),
            )
        )
    elif harness == "codex":
        directory = settings.harnesses.codex.home_directory
        readable = directory.is_dir() and os.access(directory, os.R_OK)
        # Naming the discovery path makes a silent fallback to the slower
        # directory scan visible before a report takes minutes to produce.
        detail = (
            f"{directory} ({describe_discovery(directory)})"
            if readable
            else str(directory)
        )
        checks.append(
            DoctorCheck(name="codex home directory", ok=readable, detail=detail)
        )
    else:
        executable = settings.harnesses.opencode.cli.executable
        checks.append(_check(runner, "opencode version", [executable, "--version"]))
        checks.append(_check(runner, "opencode database", [executable, "db", "path"]))
```

- [ ] **Step 4: Add the source and usage-provider branches**

In `src/agent_worklog/cli.py`, add the import:

```python
from agent_worklog.harnesses.codex.source import CodexSource
```

In `_build_scan_service`, extend the chain:

```python
    if harness is Harness.CLAUDE_CODE:
        source = ClaudeCodeFileSource(
            projects_directory=settings.harnesses.claude_code.projects_directory,
            root_only=root_only,
        )
    elif harness is Harness.CODEX:
        source = CodexSource(
            home_directory=settings.harnesses.codex.home_directory,
            root_only=root_only,
        )
    else:
        cli_settings = settings.harnesses.opencode.cli
        source = OpenCodeCliSource(
            runner=CommandRunner(timeout_seconds=cli_settings.timeout_seconds),
            executable=cli_settings.executable,
            root_only=root_only,
        )
```

In `_usage_provider`:

```python
    if harness in {Harness.CLAUDE_CODE, Harness.CODEX}:
        # Usage rides on the already-filtered activities, so the window is exact
        # and needs no "wider than the period" caveat.
        return partial(render_activity_usage, harness=harness.value), None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/services/test_doctor.py tests/integration/test_cli.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agent_worklog/cli.py src/agent_worklog/services/doctor.py tests/unit/services/test_doctor.py tests/integration/test_cli.py
git commit -m "feat: accept --harness codex in doctor, scan, and report"
```

---

### Task 9: Make the missing-prompt warning harness-neutral

**Files:**
- Modify: `src/agent_worklog/services/scan.py:30-53`, `src/agent_worklog/services/scan.py:110-117`
- Test: `tests/integration/test_scan_service.py` (append)

**Why this task exists:** `_has_assistant_work_but_no_prompt` fires for any harness, but the warning it appends names Claude Code and a Claude Code version: *"a Claude Code transcript written before version 2.1.187 does not mark human prompts"*. A Codex root session with tool calls but no `user_message` — 1,327 `user_message` records across 412 measured rollout files means many sessions have none — would emit that sentence about a Codex session. The spec does not cover this; it was found while planning.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_scan_service.py`:

```python
def test_missing_prompt_warning_does_not_name_claude_code_for_other_harnesses(
    fake_git_runner,
) -> None:
    session = AgentSession(
        harness="codex",
        session_id="thread-1",
        working_directory="/worktrees/agent",
        created_at=datetime(2026, 7, 21, tzinfo=TZ),
        updated_at=datetime(2026, 7, 21, tzinfo=TZ),
        activities=[
            SessionActivity(
                activity_id="a-1",
                activity_type=ActivityType.TOOL_CALL,
                timestamp=datetime(2026, 7, 21, 1, tzinfo=TZ),
                content="",
                tool_name="exec",
            )
        ],
    )
    service = ScanService(
        source=StubSource([session]),
        period=PERIOD,
        resolver=RepositoryResolver(runner=fake_git_runner),
    )

    result = service.scan()

    warning = next(w for w in result.warnings if "contributes no goals" in w)
    assert "Claude Code" not in warning
    assert "2.1.187" not in warning
```

The file already defines `PERIOD`, `TZ` and a stub source; reuse them. If the existing stub is named differently, use that name — do not add a second stub.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/integration/test_scan_service.py -k missing_prompt -v`
Expected: FAIL — the warning contains "Claude Code" and "2.1.187".

- [ ] **Step 3: Split the warning by harness**

In `src/agent_worklog/services/scan.py`, replace the warning append (lines 110-117) with:

```python
                if _has_assistant_work_but_no_prompt(session):
                    warnings.append(_missing_prompt_warning(session))
```

and add the helper next to `_has_assistant_work_but_no_prompt`:

```python
def _missing_prompt_warning(session: AgentSession) -> str:
    """Explain a session that recorded work but no prompts, per harness.

    The Claude Code case has a known cause worth naming. No other harness does,
    so the generic sentence stops the report from blaming a Claude Code version
    for a Codex or OpenCode session.
    """

    base = (
        f"Session {session.session_id} recorded assistant work but no user "
        "messages, so it contributes no goals"
    )
    if session.harness == "claude-code":
        return (
            f"{base}; a Claude Code transcript written before version 2.1.187 "
            "does not mark human prompts"
        )
    return base
```

Update the docstring of `_has_assistant_work_but_no_prompt` so its Claude Code-specific measurements read as an example rather than the only case: change the opening line to *"Detect a root session whose user prompts were all filtered out of the mapping, or that never had any."*

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/integration/test_scan_service.py tests/integration/test_claude_code_end_to_end.py -v`
Expected: PASS — the Claude Code wording is unchanged for Claude Code sessions.

- [ ] **Step 5: Commit**

```bash
git add src/agent_worklog/services/scan.py tests/integration/test_scan_service.py
git commit -m "fix: stop blaming a Claude Code version for other harnesses"
```

---

### Task 10: End-to-end acceptance

**Files:**
- Modify: `tests/conftest.py` (append a `codex_home` fixture)
- Create: `tests/integration/test_codex_end_to_end.py`

**Interfaces:**
- Consumes: everything from Tasks 1-9.
- Produces: `codex_home` pytest fixture returning a `Path` to a complete fake `~/.codex`.

- [ ] **Step 1: Write the fixture**

Append to `tests/conftest.py`:

```python
def _codex_record(timestamp: str, record_type: str, payload: dict) -> str:
    return json.dumps({"timestamp": timestamp, "type": record_type, "payload": payload})


@pytest.fixture
def codex_home(tmp_path: Path) -> Path:
    """A Codex home with a state database, one root session and one subagent."""

    home = tmp_path / "codex"
    rollouts = home / "sessions" / "2026" / "07" / "21"
    rollouts.mkdir(parents=True)

    root_path = rollouts / "rollout-root.jsonl"
    root_path.write_text(
        "\n".join(
            [
                _codex_record(
                    "2026-07-21T01:00:00.000Z",
                    "session_meta",
                    {
                        "session_id": "thread-root",
                        "timestamp": "2026-07-21T01:00:00.000Z",
                        "cwd": "/worktrees/agent-main",
                        "thread_source": "user",
                    },
                ),
                _codex_record(
                    "2026-07-21T01:00:01.000Z",
                    "turn_context",
                    {"turn_id": "t-1", "cwd": "/worktrees/agent-main",
                     "model": "gpt-5.6-sol"},
                ),
                _codex_record(
                    "2026-07-21T01:00:02.000Z",
                    "event_msg",
                    {"type": "user_message",
                     "message": "Add retry to the price fetcher"},
                ),
                _codex_record(
                    "2026-07-21T01:00:03.000Z",
                    "event_msg",
                    {"type": "agent_message", "message": "I implemented the retry."},
                ),
                _codex_record(
                    "2026-07-21T01:00:04.000Z",
                    "response_item",
                    {
                        "type": "function_call",
                        "name": "exec_command",
                        "call_id": "call-1",
                        "arguments": json.dumps(
                            {"cmd": "pytest -q", "workdir": "/worktrees/agent-main"}
                        ),
                    },
                ),
                _codex_record(
                    "2026-07-21T01:00:05.000Z",
                    "response_item",
                    {
                        "type": "custom_tool_call",
                        "name": "exec",
                        "call_id": "call-2",
                        "input": 'const r = await tools.exec_command('
                                 '{"cmd":"CODEX_JS_MARKER"}); text(r);',
                    },
                ),
                _codex_record(
                    "2026-07-21T01:00:06.000Z",
                    "event_msg",
                    {
                        "type": "patch_apply_end",
                        "call_id": "call-3",
                        "success": True,
                        "changes": {
                            "/worktrees/agent-main/src/fetch.py": {
                                "type": "update",
                                "content": "CODEX_FILE_BODY_MARKER",
                            }
                        },
                    },
                ),
                _codex_record(
                    "2026-07-21T01:00:07.000Z",
                    "event_msg",
                    {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {
                                "input_tokens": 1500,
                                "output_tokens": 300,
                                "cached_input_tokens": 1000,
                                "cache_write_input_tokens": 75,
                                "reasoning_output_tokens": 90,
                            }
                        },
                    },
                ),
                # A trailing reasoning-only turn: no activity, tokens still count.
                _codex_record(
                    "2026-07-21T01:00:08.000Z",
                    "event_msg",
                    {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {
                                "input_tokens": 1515,
                                "output_tokens": 400,
                                "cached_input_tokens": 1500,
                                "cache_write_input_tokens": 75,
                            }
                        },
                    },
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    sub_path = rollouts / "rollout-sub.jsonl"
    sub_path.write_text(
        "\n".join(
            [
                _codex_record(
                    "2026-07-22T01:00:00.000Z",
                    "session_meta",
                    {
                        "session_id": "thread-sub",
                        "timestamp": "2026-07-22T01:00:00.000Z",
                        "cwd": "/worktrees/assets",
                        "thread_source": "subagent",
                        "parent_thread_id": "thread-root",
                    },
                ),
                _codex_record(
                    "2026-07-22T01:00:01.000Z",
                    "event_msg",
                    {"type": "user_message", "message": "Review the retry helper"},
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    connection = sqlite3.connect(home / "state_5.sqlite")
    try:
        connection.executescript(
            """
            CREATE TABLE threads (
                id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL,
                created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
                cwd TEXT NOT NULL, title TEXT NOT NULL, agent_nickname TEXT,
                thread_source TEXT, archived INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE thread_spawn_edges (
                parent_thread_id TEXT NOT NULL,
                child_thread_id TEXT NOT NULL PRIMARY KEY,
                status TEXT NOT NULL
            );
            """
        )
        connection.executemany(
            "INSERT INTO threads (id, rollout_path, created_at, updated_at, cwd,"
            " title, agent_nickname, thread_source, archived)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "thread-root",
                    str(root_path),
                    int(datetime(2026, 7, 21, tzinfo=_ACCEPTANCE_TZ).timestamp()),
                    int(datetime(2026, 7, 21, 2, tzinfo=_ACCEPTANCE_TZ).timestamp()),
                    "/worktrees/agent-main",
                    "Retry for the price fetcher",
                    None,
                    "user",
                    0,
                ),
                (
                    "thread-sub",
                    str(sub_path),
                    int(datetime(2026, 7, 22, tzinfo=_ACCEPTANCE_TZ).timestamp()),
                    int(datetime(2026, 7, 22, 1, tzinfo=_ACCEPTANCE_TZ).timestamp()),
                    "/worktrees/assets",
                    "",
                    "Ampere",
                    "subagent",
                    0,
                ),
            ],
        )
        connection.executemany(
            "INSERT INTO thread_spawn_edges"
            " (parent_thread_id, child_thread_id, status) VALUES (?, ?, ?)",
            [("thread-root", "thread-sub", "completed")],
        )
        connection.commit()
    finally:
        connection.close()
    return home
```

Add `import sqlite3` to the top of `tests/conftest.py`.

- [ ] **Step 2: Write the failing acceptance test**

Create `tests/integration/test_codex_end_to_end.py`:

```python
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from typer.testing import CliRunner

import agent_worklog.cli as cli

TZ = ZoneInfo("Asia/Taipei")


def _invoke(monkeypatch, codex_home: Path, git_only_runner, output: Path, *extra: str):
    monkeypatch.setattr(
        cli,
        "_now_in_timezone",
        lambda timezone: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )
    monkeypatch.setattr(cli, "CommandRunner", lambda timeout_seconds: git_only_runner)
    monkeypatch.setenv(
        "AGENT_WORKLOG_HARNESSES__CODEX__HOME_DIRECTORY", str(codex_home)
    )
    return CliRunner().invoke(
        cli.app,
        [
            "report",
            "--harness",
            "codex",
            "--period",
            "last-week",
            "--no-llm",
            "--output",
            str(output),
            *extra,
        ],
    )


def test_codex_report_groups_by_repository_and_reports_usage(
    tmp_path: Path, monkeypatch, codex_home: Path, git_only_runner
) -> None:
    output = tmp_path / "worklog.md"

    result = _invoke(monkeypatch, codex_home, git_only_runner, output)

    assert result.exit_code == 0, result.stdout
    content = output.read_text(encoding="utf-8")
    assert "github.com/mike/agent-worklog" in content
    assert "github.com/mike/assets-tracker" in content
    assert "Retry for the price fetcher" in content
    assert "Add retry to the price fetcher" in content
    assert "## Usage" in content
    # Pin the four aggregated numbers to the fixture's running totals. The second
    # token_count is a reasoning-only turn that emits no activity of its own, so
    # the row is the final running total: 1,515 / 400 / 1,500 / 75.
    assert "gpt-5.6-sol  1,515     400       1,500           75" in content
    assert "Total        1,515     400       1,500           75" in content
    assert "Window: the last" not in content


def test_codex_report_claims_no_verification_outcome(
    tmp_path: Path, monkeypatch, codex_home: Path, git_only_runner
) -> None:
    output = tmp_path / "worklog.md"

    _invoke(monkeypatch, codex_home, git_only_runner, output)
    content = output.read_text(encoding="utf-8")

    assert "Verification passed" not in content
    assert "pytest -q" in content


def test_codex_report_leaks_neither_patch_bodies_nor_javascript(
    tmp_path: Path, monkeypatch, codex_home: Path, git_only_runner
) -> None:
    output = tmp_path / "worklog.md"

    _invoke(monkeypatch, codex_home, git_only_runner, output)
    content = output.read_text(encoding="utf-8")

    assert "CODEX_FILE_BODY_MARKER" not in content
    assert "CODEX_JS_MARKER" not in content
    assert "/worktrees/agent-main/src/fetch.py" in content


def test_root_only_excludes_the_subagent_repository(
    tmp_path: Path, monkeypatch, codex_home: Path, git_only_runner
) -> None:
    output = tmp_path / "worklog.md"

    result = _invoke(
        monkeypatch, codex_home, git_only_runner, output, "--root-only"
    )

    assert result.exit_code == 0, result.stdout
    content = output.read_text(encoding="utf-8")
    assert "github.com/mike/agent-worklog" in content
    assert "github.com/mike/assets-tracker" not in content


def test_report_works_without_the_state_database(
    tmp_path: Path, monkeypatch, codex_home: Path, git_only_runner
) -> None:
    (codex_home / "state_5.sqlite").unlink()
    output = tmp_path / "worklog.md"

    result = _invoke(monkeypatch, codex_home, git_only_runner, output)

    assert result.exit_code == 0, result.stdout
    content = output.read_text(encoding="utf-8")
    assert "github.com/mike/agent-worklog" in content
    assert "github.com/mike/assets-tracker" in content


def test_scan_reports_the_codex_sessions(
    monkeypatch, codex_home: Path, git_only_runner
) -> None:
    monkeypatch.setattr(
        cli,
        "_now_in_timezone",
        lambda timezone: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )
    monkeypatch.setattr(cli, "CommandRunner", lambda timeout_seconds: git_only_runner)
    monkeypatch.setenv(
        "AGENT_WORKLOG_HARNESSES__CODEX__HOME_DIRECTORY", str(codex_home)
    )

    result = CliRunner().invoke(
        cli.app, ["scan", "--harness", "codex", "--period", "last-week"]
    )

    assert result.exit_code == 0, result.stdout
```

- [ ] **Step 3: Run the acceptance tests**

Run: `uv run pytest tests/integration/test_codex_end_to_end.py -v`
Expected: PASS. If the usage-table assertion fails on column alignment, run with `-vv`, read the actual line out of the failure output, and correct the expected string to match — the column widths come from `renderers/usage.py`, not from anything this task controls. Do not change the numbers to match the output; if the numbers differ, the mapper is wrong.

- [ ] **Step 4: Run the whole suite with coverage**

Run: `uv run pytest --cov=agent_worklog --cov-fail-under=80 && uv run ruff check . && uv run pyright`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/integration/test_codex_end_to_end.py
git commit -m "test: pin Codex report grouping, usage, and redaction"
```

---

### Task 11: Documentation

**Files:**
- Modify: `README.md`, `README.zh-TW.md`, `docs/configuration.md`, `docs/privacy.md`, `CHANGELOG.md`
- Test: `tests/unit/test_documentation.py` (this repo already has one; extend it if it asserts on harness lists)

- [ ] **Step 1: Extend the documentation test first**

`tests/unit/test_documentation.py:13` asserts the README documents `--harness` and mentions `claude-code`, and line 24 asserts the privacy doc mentions Claude Code. Add the Codex equivalents so the prose edits are test-driven:

```python
def test_readme_documents_the_codex_harness() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "codex" in readme
    assert "Codex is not currently supported" not in readme


def test_privacy_documents_the_codex_harness() -> None:
    privacy = (ROOT / "docs" / "privacy.md").read_text(encoding="utf-8")

    assert "Codex" in privacy
```

Use whatever the file already names its repository-root constant instead of `ROOT` if it differs.

Run: `uv run pytest tests/unit/test_documentation.py -v`
Expected: FAIL — the README still says Codex is not supported.

- [ ] **Step 2: Update `README.md`**

- Capabilities: add "Read Codex sessions from `~/.codex`, using the Codex state database when it is present and scanning the rollout files when it is not."
- Requirements: add a `--harness codex` block — Python 3.11+, Git, a readable `~/.codex` (or `AGENT_WORKLOG_HARNESSES__CODEX__HOME_DIRECTORY`). No Codex CLI required.
- The `--harness NAME` row becomes: `Harness to read sessions from: opencode (default), claude-code, or codex.`
- Getting started: add `agent-worklog report --harness codex --period last-week --no-llm`.
- Privacy: add the Codex paragraph from Step 4.
- **Delete** the line `- Codex is not currently supported.` from "Current support and limits" and add:

```markdown
- Codex reports do not claim that a command passed or failed. Codex records exit
  codes only inside free-form tool output, in several formats, so only
  `patch_apply_end`'s structured `success` flag is trusted, and it reports a file
  change rather than a verification result.
- Commands run from inside Codex's `exec` tool do not appear in the report.
  `exec` takes a JavaScript program, not a command, so there is no command to
  report; commands run through `exec_command` do appear.
- Codex usage counts each API request's full input, which is what Codex itself
  reports. It is not a count of distinct tokens.
```

- [ ] **Step 3: Mirror every change in `README.zh-TW.md`**

Keep the two files structurally identical — same sections, same rows, same order.

- [ ] **Step 4: Update `docs/privacy.md` and `docs/configuration.md`**

`docs/privacy.md`, Codex section:

```markdown
Codex has no export command either, so `--harness codex` reads the rollout JSONL
files directly. Two kinds of content are dropped in the mapper rather than
downstream: the `content` field of every `patch_apply_end` change, which holds
the whole file the patch wrote, and the input of every `exec` call, which is an
arbitrary JavaScript program. Only the changed file's path and the tool's name
survive. Commands survive only from `exec_command`, whose arguments name the
command in a field.
```

`docs/configuration.md`, harness settings table:

```markdown
| `AGENT_WORKLOG_HARNESSES__CODEX__ENABLED` | `true` | Set to `false` to make `--harness codex` fail with a configuration error (exit code 3). |
| `AGENT_WORKLOG_HARNESSES__CODEX__HOME_DIRECTORY` | `~/.codex` | Directory holding the Codex state database and rollout files. |
```

with the note: *"One setting covers all three locations Agent Worklog reads — `state_<n>.sqlite`, `sessions/`, and `archived_sessions/` are fixed positions under it."*

- [ ] **Step 5: Update `CHANGELOG.md`**

Add to the `## Unreleased` section:

```markdown
- Add `codex` to `--harness`. Sessions are discovered from `~/.codex/state_<n>.sqlite`,
  which already indexes every session with its rollout path, working directory,
  timestamps, and parent edge, so a period query is one SQL statement instead of
  opening every rollout file; a scan of `sessions/` and `archived_sessions/` is the
  fallback when that database is absent or its schema has changed.
- No Codex report claims that a command passed or failed. Codex records exit codes
  only inside free-form tool output text, in at least three formats, so a regex over
  it would fail silently the day Codex changes it. `patch_apply_end`'s `success` flag
  is the one structured signal used, and it reports a file change.
- Leave commands run from inside Codex's `exec` tool out of the report. `exec` takes
  an arbitrary JavaScript program rather than a command — a strict parse for a single
  wrapped `exec_command` call matched none of 4,963 measured calls — so its input is
  never put in an activity, which also keeps it out of outbound LLM requests.
- Build the Codex usage table by differencing the running `total_token_usage` rather
  than summing `last_token_usage`, which over-counted by 3.7% on a measured session
  because Codex emits some `token_count` events more than once.
- Drop the file bodies Codex records in `patch_apply_end.changes` in the mapper. Only
  the changed paths reach a session, so a patch that writes a whole file no longer
  carries that file toward the report's 300-character cap.
- Move the per-model usage table out of the Claude Code package. It reads only
  activity metadata, so Claude Code and Codex now share one implementation.
- Stop naming Claude Code in the missing-prompt warning for sessions from other
  harnesses.
```

- [ ] **Step 6: Verify and commit**

Run: `uv run pytest -q && uv run ruff check .`

```bash
git add README.md README.zh-TW.md docs/configuration.md docs/privacy.md CHANGELOG.md tests/unit/test_documentation.py
git commit -m "docs: document the Codex harness and its limits"
```

---

## Post-Implementation Verification

- [ ] `uv run pytest --cov=agent_worklog --cov-fail-under=80` passes.
- [ ] `uv run ruff check .` and `uv run pyright` are clean.
- [ ] `uv build` succeeds.
- [ ] `grep -rn "Codex is not currently supported" README.md README.zh-TW.md` returns nothing.
- [ ] `agent-worklog doctor --harness codex` against the real `~/.codex` reports the state database by name.
- [ ] `agent-worklog report --harness codex --period last-week --no-llm --dry-run` against the real `~/.codex` produces a report containing no `Verification passed`.
