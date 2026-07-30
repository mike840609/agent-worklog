# Claude Code Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Claude Code as a second harness so `agent-worklog scan|report --harness claude-code` produces the same repository-grouped Markdown worklog that OpenCode does.

**Architecture:** A new `ClaudeCodeFileSource` implements the existing `HarnessSessionSource` contract by reading `~/.claude/projects/**/*.jsonl` directly — Claude Code has no export command. Because there is no `--sanitize` upstream, the mapper deliberately drops data at map time rather than relying on `security/redactor.py` alone. The shared pipeline (resolver, filtering, hierarchy, extraction, summarizers, renderer) is unchanged except for one new MEDIUM-confidence branch in `extraction/pipeline.py`.

**Tech Stack:** Python 3.11+, pydantic v2, pydantic-settings, Typer, Jinja2, pytest. **No new dependencies** — JSONL parsing uses stdlib `json` and `pathlib`.

**Spec:** [docs/claude-code-adapter-design.md](../claude-code-adapter-design.md)

## Global Constraints

- `requires-python = ">=3.11"` — no 3.12+ only syntax.
- ruff: `line-length = 100`, lint rules `["E", "F", "I", "UP", "B", "SIM"]`.
- pyright: `typeCheckingMode = "standard"`, `include = ["src"]`.
- Coverage gate: `uv run pytest --cov=agent_worklog --cov-fail-under=80`.
- No new runtime dependencies.
- `--harness` defaults to `opencode`; every existing OpenCode test must pass unmodified except for the mechanical import moves in Task 1 and the signature change in Task 4.
- `stdout` and `stderr` text from `toolUseResult` must never enter `AgentSession`. Only derived booleans cross that boundary.
- All work happens on branch `feat/claude-code-adapter`.

## Deviations From the Spec (approved changes to note)

1. **Usage output is plain-text aligned columns, not a Markdown pipe table.** `templates/worklog.md.j2:77-79` wraps `report.usage_text` in a ```` ```text ```` fence, so a pipe table would render as literal text. Aligned columns render correctly inside the fence and match how `opencode stats` output already looks. The spec's "template zero change" goal is preserved.
2. **`SessionDescriptor` gains `source_location: str | None = None`.** `load()` needs to find the JSONL file that `discover()` found. The MVP design §9.1 originally specified this field; the implemented model dropped it. Additive and unused by OpenCode.
3. **`RuleBasedSummarizer` must accept MEDIUM confidence, or the spec's §7 heuristic is dead code.** `summarizers/rule_based.py:39-45` filters outcomes to `confidence == EvidenceConfidence.HIGH`, so every MEDIUM item the stderr heuristic produces would be silently dropped from `--no-llm` reports. Task 5 widens the filter to `{HIGH, MEDIUM}` and appends `" (inferred)"` to MEDIUM items so the report reader can tell the difference. The spec did not catch this.

## File Structure

**New:**

| File | Responsibility |
|---|---|
| `src/agent_worklog/process.py` | Subprocess execution (`CommandResult`, `CommandRunner`) — moved out of `harnesses/opencode/` so shared layers stop importing harness internals |
| `src/agent_worklog/harnesses/claude_code/__init__.py` | Package marker |
| `src/agent_worklog/harnesses/claude_code/mapper.py` | JSONL records → `AgentSession`, including the deliberate data loss |
| `src/agent_worklog/harnesses/claude_code/source.py` | File discovery + load |
| `src/agent_worklog/harnesses/claude_code/usage.py` | Per-model token aggregation → plain-text table |

**Deleted:** `src/agent_worklog/harnesses/opencode/cli_runner.py` (moved to `process.py`).

**Modified:** `models/session.py`, `config.py`, `cli.py`, `services/report.py`, `services/scan.py`, `services/doctor.py`, `extraction/pipeline.py`, `repositories/resolver.py`, `harnesses/opencode/{source,stats}.py`.

---

## Task 1: Move `cli_runner` out of the OpenCode package

Purely mechanical. `repositories/resolver.py` and `services/doctor.py` currently import `CommandResult` from `harnesses.opencode.cli_runner` — shared code reaching into a harness. Nothing else in this plan can cleanly add a second harness while that holds.

**Files:**
- Create: `src/agent_worklog/process.py`
- Delete: `src/agent_worklog/harnesses/opencode/cli_runner.py`
- Modify: `src/agent_worklog/cli.py:20`, `src/agent_worklog/harnesses/opencode/source.py:11`, `src/agent_worklog/harnesses/opencode/stats.py:11`, `src/agent_worklog/repositories/resolver.py:9`, `src/agent_worklog/services/doctor.py:7`
- Test: rename `tests/unit/harnesses/opencode/test_cli_runner.py` → `tests/unit/test_process.py`; update imports in `tests/conftest.py:9`, `tests/unit/harnesses/opencode/test_source_discovery.py:7`, `tests/unit/harnesses/opencode/test_stats.py:9`, `tests/unit/harnesses/opencode/test_mapper.py:7`, `tests/unit/repositories/test_resolver.py:1`, `tests/unit/services/test_doctor.py:2`

**Interfaces:**
- Consumes: nothing
- Produces: `agent_worklog.process.CommandResult` (frozen dataclass: `returncode: int`, `stdout: str`, `stderr: str`) and `agent_worklog.process.CommandRunner(*, timeout_seconds: float)` with `.run(args: list[str]) -> CommandResult`. Every later task and every existing module imports these from `agent_worklog.process`.

- [ ] **Step 1: Create the new module with `git mv` so history follows**

```bash
git mv src/agent_worklog/harnesses/opencode/cli_runner.py src/agent_worklog/process.py
git mv tests/unit/harnesses/opencode/test_cli_runner.py tests/unit/test_process.py
```

- [ ] **Step 2: Update the module docstring**

In `src/agent_worklog/process.py`, change line 1 from:

```python
"""Safe subprocess execution for OpenCode and Git commands."""
```

to:

```python
"""Safe subprocess execution for harness and Git commands."""
```

- [ ] **Step 3: Rewrite every import**

Replace `from agent_worklog.harnesses.opencode.cli_runner import` with `from agent_worklog.process import` across `src/` and `tests/`:

```bash
grep -rl "agent_worklog.harnesses.opencode.cli_runner" src tests \
  | xargs sed -i '' 's/agent_worklog\.harnesses\.opencode\.cli_runner/agent_worklog.process/g'
grep -rl "from agent_worklog.harnesses.opencode import cli_runner" src tests \
  | xargs sed -i '' 's/from agent_worklog\.harnesses\.opencode import cli_runner/from agent_worklog import process as cli_runner/g'
```

Then verify nothing is left:

```bash
grep -rn "cli_runner" src tests --include="*.py"
```

Expected: only `tests/unit/test_process.py` matches, via the `process as cli_runner` alias. If you prefer, rename the alias to `process` and update the two `cli_runner.subprocess` references in that file — either is fine.

- [ ] **Step 4: Run the full suite to prove the move changed no behavior**

Run: `uv run pytest -q`
Expected: PASS, same test count as before the move.

- [ ] **Step 5: Lint and typecheck**

Run: `uv run ruff check . && uv run pyright`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add -A src tests
git commit -m "refactor: move CommandRunner out of the OpenCode package

Shared modules (resolver, doctor) imported CommandResult from
harnesses/opencode/cli_runner.py. Moving it to agent_worklog.process
removes that dependency before a second harness is added."
```

---

## Task 2: Claude Code JSONL mapper

The security-critical task. The mapper decides what never reaches `AgentSession`.

**Files:**
- Create: `src/agent_worklog/harnesses/claude_code/__init__.py`
- Create: `src/agent_worklog/harnesses/claude_code/mapper.py`
- Create: `tests/fixtures/claude_code/session-basic.jsonl`
- Test: `tests/unit/harnesses/claude_code/test_mapper.py`

**Interfaces:**
- Consumes: `agent_worklog.models.session.{ActivityType, AgentSession, SessionActivity, SessionDescriptor, TokenUsage, UsageSemantics}`
- Produces: `ClaudeCodeJsonlMapper().map(records: list[Mapping[str, Any]], descriptor: SessionDescriptor) -> AgentSession`. Task 3 calls this. Assistant activities carry `metadata["model"]: str` and `metadata["usage"]: dict[str, int]` (keys `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`) — Task 5 reads exactly those. Tool-call activities carry `metadata["stderr_empty"]: bool` and `metadata["interrupted"]: bool` — Task 6 reads exactly those.

- [ ] **Step 1: Write the fixture**

Create `tests/fixtures/claude_code/session-basic.jsonl`. Every marker string starting with a capitalised `_MARKER` suffix exists so a test can assert it is absent from the mapped session. One JSON object per line, no trailing blank line issues (a trailing newline is fine).

```jsonl
{"type":"mode","mode":"normal","sessionId":"sess-1"}
{"type":"attachment","attachment":{"type":"hook_success","hookName":"SessionStart:startup","stdout":"HOOK_STDOUT_MARKER install everything"},"sessionId":"sess-1","timestamp":"2026-07-21T01:00:00.000Z","cwd":"/repo/main","gitBranch":"main"}
{"type":"user","isMeta":true,"message":{"role":"user","content":"<system-reminder>SYSTEM_REMINDER_MARKER</system-reminder>"},"uuid":"u-meta","timestamp":"2026-07-21T01:00:01.000Z","cwd":"/repo/main","gitBranch":"main","sessionId":"sess-1"}
{"type":"user","origin":{"kind":"human"},"message":{"role":"user","content":"Add retry to the price fetcher"},"uuid":"u-1","timestamp":"2026-07-21T01:00:02.000Z","cwd":"/repo/main","gitBranch":"main","sessionId":"sess-1"}
{"type":"assistant","message":{"model":"claude-opus-5","role":"assistant","content":[{"type":"thinking","thinking":"THINKING_MARKER internal plan"},{"type":"text","text":"I implemented the retry."},{"type":"tool_use","id":"toolu-1","name":"Bash","input":{"command":"pytest -q"}}],"usage":{"input_tokens":10,"output_tokens":200,"cache_read_input_tokens":1000,"cache_creation_input_tokens":50}},"uuid":"a-1","timestamp":"2026-07-21T01:00:03.000Z","cwd":"/repo/main","gitBranch":"main","sessionId":"sess-1"}
{"type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu-1","content":"ok"}]},"toolUseResult":{"stdout":"STDOUT_SECRET_MARKER 42 passed","stderr":"","interrupted":false,"isImage":false},"uuid":"u-2","timestamp":"2026-07-21T01:00:04.000Z","cwd":"/repo/main","gitBranch":"main","sessionId":"sess-1"}
{"type":"assistant","message":{"model":"claude-sonnet-5","role":"assistant","content":[{"type":"tool_use","id":"toolu-2","name":"Edit","input":{"file_path":"/repo/worktree-feat/src/fetch.py","old_string":"a","new_string":"b"}}],"usage":{"input_tokens":5,"output_tokens":100,"cache_read_input_tokens":2000,"cache_creation_input_tokens":0}},"uuid":"a-2","timestamp":"2026-07-21T01:00:05.000Z","cwd":"/repo/worktree-feat","gitBranch":"feat/retry","sessionId":"sess-1"}
{"type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu-2","content":"err"}]},"toolUseResult":{"stdout":"","stderr":"STDERR_SECRET_MARKER permission denied","interrupted":false,"isImage":false},"uuid":"u-3","timestamp":"2026-07-21T01:00:06.000Z","cwd":"/repo/worktree-feat","gitBranch":"feat/retry","sessionId":"sess-1"}
{"type":"ai-title","aiTitle":"Retry for the price fetcher","sessionId":"sess-1"}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/harnesses/claude_code/test_mapper.py`:

```python
import json
from pathlib import Path

import pytest

from agent_worklog.harnesses.claude_code.mapper import ClaudeCodeJsonlMapper
from agent_worklog.models.session import ActivityType, SessionDescriptor, UsageSemantics

FIXTURE = Path("tests/fixtures/claude_code/session-basic.jsonl")

SECRET_MARKERS = (
    "HOOK_STDOUT_MARKER",
    "SYSTEM_REMINDER_MARKER",
    "THINKING_MARKER",
    "STDOUT_SECRET_MARKER",
    "STDERR_SECRET_MARKER",
)


@pytest.fixture
def descriptor() -> SessionDescriptor:
    return SessionDescriptor(
        harness="claude-code",
        session_id="sess-1",
        source_location=str(FIXTURE),
        project_id_hint="-repo-main",
    )


@pytest.fixture
def records() -> list[dict]:
    return [
        json.loads(line)
        for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_maps_only_human_prompts_to_user_messages(records, descriptor) -> None:
    session = ClaudeCodeJsonlMapper().map(records, descriptor)

    user_texts = [
        activity.content
        for activity in session.activities
        if activity.activity_type == ActivityType.USER_MESSAGE
    ]
    assert user_texts == ["Add retry to the price fetcher"]


def test_drops_every_secret_marker(records, descriptor) -> None:
    """stdout, stderr, thinking, hook output, and system reminders never reach the model."""

    session = ClaudeCodeJsonlMapper().map(records, descriptor)
    serialized = session.model_dump_json()

    for marker in SECRET_MARKERS:
        assert marker not in serialized, f"{marker} leaked into AgentSession"


def test_maps_tool_calls_with_result_flags(records, descriptor) -> None:
    session = ClaudeCodeJsonlMapper().map(records, descriptor)

    tool_calls = {
        activity.tool_call_id: activity
        for activity in session.activities
        if activity.activity_type == ActivityType.TOOL_CALL
    }

    bash = tool_calls["toolu-1"]
    assert bash.tool_name == "Bash"
    assert bash.content == "pytest -q"
    assert bash.metadata["stderr_empty"] is True
    assert bash.metadata["interrupted"] is False

    edit = tool_calls["toolu-2"]
    assert edit.tool_name == "Edit"
    assert edit.content == "/repo/worktree-feat/src/fetch.py"
    assert edit.metadata["stderr_empty"] is False


def test_uses_last_cwd_and_ai_title(records, descriptor) -> None:
    session = ClaudeCodeJsonlMapper().map(records, descriptor)

    assert session.working_directory == "/repo/worktree-feat"
    assert session.title == "Retry for the price fetcher"
    assert session.harness == "claude-code"


def test_accumulates_incremental_token_usage(records, descriptor) -> None:
    session = ClaudeCodeJsonlMapper().map(records, descriptor)

    assert session.token_usage is not None
    assert session.token_usage.semantics is UsageSemantics.INCREMENTAL
    assert session.token_usage.input_tokens == 15
    assert session.token_usage.output_tokens == 300
    assert session.token_usage.cache_read_tokens == 3000
    assert session.token_usage.cache_write_tokens == 50


def test_attaches_per_model_usage_to_one_activity_per_record(records, descriptor) -> None:
    session = ClaudeCodeJsonlMapper().map(records, descriptor)

    per_model = [
        (activity.metadata["model"], activity.metadata["usage"])
        for activity in session.activities
        if "usage" in activity.metadata
    ]
    assert per_model == [
        (
            "claude-opus-5",
            {
                "input_tokens": 10,
                "output_tokens": 200,
                "cache_read_tokens": 1000,
                "cache_write_tokens": 50,
            },
        ),
        (
            "claude-sonnet-5",
            {
                "input_tokens": 5,
                "output_tokens": 100,
                "cache_read_tokens": 2000,
                "cache_write_tokens": 0,
            },
        ),
    ]


def test_every_activity_has_a_timestamp(records, descriptor) -> None:
    """ScanService warns about timestamp-less activities; Claude Code always has them."""

    session = ClaudeCodeJsonlMapper().map(records, descriptor)

    assert session.activities
    assert all(activity.timestamp is not None for activity in session.activities)
```

- [ ] **Step 3: Add `source_location` to `SessionDescriptor`**

In `src/agent_worklog/models/session.py`, add one field to `SessionDescriptor` (after `session_id`):

```python
class SessionDescriptor(BaseModel):
    harness: str
    session_id: str
    source_location: str | None = None
    title: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    working_directory_hint: str | None = None
    project_id_hint: str | None = None
    parent_session_id: str | None = None
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/harnesses/claude_code/test_mapper.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_worklog.harnesses.claude_code'`

- [ ] **Step 5: Write the mapper**

Create `src/agent_worklog/harnesses/claude_code/__init__.py` as an empty file, then `src/agent_worklog/harnesses/claude_code/mapper.py`:

```python
"""Map Claude Code JSONL records into canonical session models."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from agent_worklog.models.session import (
    ActivityType,
    AgentSession,
    SessionActivity,
    SessionDescriptor,
    TokenUsage,
    UsageSemantics,
)

_TOOL_INPUT_MAX_LENGTH = 200
_TOOL_CONTENT_KEYS = ("command", "file_path", "path", "notebook_path")

# Canonical name -> Claude Code `message.usage` key.
_USAGE_FIELDS = {
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "cache_read_tokens": "cache_read_input_tokens",
    "cache_write_tokens": "cache_creation_input_tokens",
}


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _int_value(value: object) -> int | None:
    # bool is an int subclass; a JSON true would otherwise add 1 to a token total.
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _human_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [
            block.get("text")
            for block in content
            if isinstance(block, Mapping) and block.get("type") == "text"
        ]
        return "\n".join(text for text in texts if isinstance(text, str) and text)
    return ""


def _is_human_prompt(record: Mapping[str, Any]) -> bool:
    """Accept only real human input.

    Claude Code also writes tool results, hook injections, and system reminders
    as `type: "user"` records. Treating those as user intent would put hook
    output and skill instructions into the report's goals.
    """

    if record.get("isMeta"):
        return False
    return _as_mapping(record.get("origin")).get("kind") == "human"


def _tool_content(tool_input: object) -> str:
    mapping = _as_mapping(tool_input)
    for key in _TOOL_CONTENT_KEYS:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if tool_input is None:
        return ""
    try:
        serialized = json.dumps(tool_input, ensure_ascii=False, sort_keys=True)
    except TypeError:
        serialized = str(tool_input)
    return serialized[:_TOOL_INPUT_MAX_LENGTH]


def _tool_result_flags(
    records: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, object]]:
    """Index derived booleans by `tool_use_id`.

    Only booleans cross this boundary. `stdout` and `stderr` hold whole file
    contents, environment dumps, and hook output, and Claude Code has no
    `--sanitize` upstream, so they never enter AgentSession.
    """

    flags: dict[str, dict[str, object]] = {}
    for record in records:
        result = _as_mapping(record.get("toolUseResult"))
        if not result:
            continue
        content = _as_mapping(record.get("message")).get("content")
        if not isinstance(content, list):
            continue
        stderr = result.get("stderr")
        derived = {
            "stderr_empty": not (stderr.strip() if isinstance(stderr, str) else ""),
            "interrupted": result.get("interrupted") is True,
        }
        for block in content:
            if not isinstance(block, Mapping) or block.get("type") != "tool_result":
                continue
            tool_use_id = block.get("tool_use_id")
            if isinstance(tool_use_id, str) and tool_use_id:
                flags[tool_use_id] = dict(derived)
    return flags


class ClaudeCodeJsonlMapper:
    """Convert Claude Code JSONL records to an AgentSession, dropping raw output."""

    def map(
        self,
        records: list[Mapping[str, Any]],
        descriptor: SessionDescriptor,
    ) -> AgentSession:
        result_flags = _tool_result_flags(records)

        activities: list[SessionActivity] = []
        totals: dict[str, int] = {}
        title: str | None = None
        working_directory: str | None = None
        first_timestamp: datetime | None = None
        last_timestamp: datetime | None = None

        for record_index, record in enumerate(records):
            record_type = record.get("type")
            if record_type == "ai-title":
                ai_title = record.get("aiTitle")
                if isinstance(ai_title, str) and ai_title:
                    title = ai_title
                continue
            if record_type not in {"user", "assistant"}:
                continue

            timestamp = _parse_timestamp(record.get("timestamp"))
            if timestamp is not None:
                if first_timestamp is None:
                    first_timestamp = timestamp
                last_timestamp = timestamp
            cwd = record.get("cwd")
            if isinstance(cwd, str) and cwd:
                working_directory = cwd

            uuid = record.get("uuid")
            record_id = (
                uuid
                if isinstance(uuid, str) and uuid
                else f"{descriptor.session_id}:record:{record_index}"
            )
            message = _as_mapping(record.get("message"))

            if record_type == "user":
                if not _is_human_prompt(record):
                    continue
                text = _human_text(message.get("content"))
                if not text:
                    continue
                activities.append(
                    SessionActivity(
                        activity_id=f"{record_id}:0",
                        activity_type=ActivityType.USER_MESSAGE,
                        timestamp=timestamp,
                        content=text,
                    )
                )
                continue

            emitted = self._assistant_activities(
                message=message,
                record_id=record_id,
                timestamp=timestamp,
                result_flags=result_flags,
            )
            if emitted:
                self._attach_usage(emitted[0], message=message, totals=totals)
            activities.extend(emitted)

        return AgentSession(
            harness="claude-code",
            session_id=descriptor.session_id,
            parent_session_id=descriptor.parent_session_id,
            title=title or descriptor.title,
            created_at=first_timestamp or descriptor.created_at,
            updated_at=last_timestamp or descriptor.updated_at,
            working_directory=working_directory or descriptor.working_directory_hint,
            project_id_hint=descriptor.project_id_hint,
            activities=activities,
            token_usage=TokenUsage(
                semantics=UsageSemantics.INCREMENTAL,
                input_tokens=totals.get("input_tokens"),
                output_tokens=totals.get("output_tokens"),
                cache_read_tokens=totals.get("cache_read_tokens"),
                cache_write_tokens=totals.get("cache_write_tokens"),
            ),
        )

    def _assistant_activities(
        self,
        *,
        message: Mapping[str, Any],
        record_id: str,
        timestamp: datetime | None,
        result_flags: dict[str, dict[str, object]],
    ) -> list[SessionActivity]:
        content = message.get("content")
        if not isinstance(content, list):
            return []

        activities: list[SessionActivity] = []
        for index, raw_block in enumerate(content):
            if not isinstance(raw_block, Mapping):
                continue
            block_type = raw_block.get("type")
            activity_id = f"{record_id}:{index}"

            if block_type == "text":
                text = raw_block.get("text")
                if not isinstance(text, str) or not text:
                    continue
                activities.append(
                    SessionActivity(
                        activity_id=activity_id,
                        activity_type=ActivityType.ASSISTANT_MESSAGE,
                        timestamp=timestamp,
                        content=text,
                    )
                )
            elif block_type == "tool_use":
                tool_name = raw_block.get("name")
                tool_call_id = raw_block.get("id")
                metadata: dict[str, object] = {}
                if isinstance(tool_call_id, str):
                    metadata.update(result_flags.get(tool_call_id, {}))
                activities.append(
                    SessionActivity(
                        activity_id=activity_id,
                        activity_type=ActivityType.TOOL_CALL,
                        timestamp=timestamp,
                        content=_tool_content(raw_block.get("input")),
                        tool_name=tool_name if isinstance(tool_name, str) else None,
                        tool_call_id=tool_call_id if isinstance(tool_call_id, str) else None,
                        metadata=metadata,
                    )
                )
            # `thinking` blocks are dropped: internal reasoning is not work evidence.
        return activities

    def _attach_usage(
        self,
        activity: SessionActivity,
        *,
        message: Mapping[str, Any],
        totals: dict[str, int],
    ) -> None:
        """Record per-model usage on one activity per assistant record.

        ponytail: attached to the first emitted activity so a multi-block record
        is not counted twice. A record that emits no activity (thinking only)
        loses its usage; those carry few tokens. Aggregate properly if that
        undercount ever matters.
        """

        usage = _as_mapping(message.get("usage"))
        model = message.get("model")
        if not usage or not isinstance(model, str) or not model:
            return

        per_record: dict[str, int] = {}
        for canonical, source_key in _USAGE_FIELDS.items():
            value = _int_value(usage.get(source_key))
            if value is None:
                continue
            per_record[canonical] = value
            totals[canonical] = totals.get(canonical, 0) + value
        if not per_record:
            return

        activity.metadata["model"] = model
        activity.metadata["usage"] = per_record
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/harnesses/claude_code/test_mapper.py -q`
Expected: PASS, 7 tests.

- [ ] **Step 7: Lint, typecheck, full suite**

Run: `uv run ruff check . && uv run pyright && uv run pytest -q`
Expected: all clean. The `SessionDescriptor` change is additive so OpenCode tests are unaffected.

- [ ] **Step 8: Commit**

```bash
git add src/agent_worklog/harnesses/claude_code src/agent_worklog/models/session.py \
        tests/unit/harnesses/claude_code tests/fixtures/claude_code
git commit -m "feat: map Claude Code JSONL records to canonical sessions

Claude Code has no export --sanitize, so the mapper drops raw output at
map time instead of relying on redaction: only text blocks, tool names,
and a command or path slice survive. toolUseResult contributes two
booleans and never its stdout or stderr."
```

---

## Task 3: Claude Code file source

**Files:**
- Create: `src/agent_worklog/harnesses/claude_code/source.py`
- Test: `tests/unit/harnesses/claude_code/test_source.py`

**Interfaces:**
- Consumes: `ClaudeCodeJsonlMapper` (Task 2), `agent_worklog.harnesses.base.HarnessSessionSource`, `agent_worklog.models.time_range.DateRange`
- Produces: `ClaudeCodeFileSource(*, projects_directory: Path, root_only: bool = False)` implementing `discover(period: DateRange) -> list[SessionDescriptor]` and `load(descriptor: SessionDescriptor) -> AgentSession`. Task 6 constructs it.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/harnesses/claude_code/test_source.py`:

```python
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from agent_worklog.errors import SessionParseError
from agent_worklog.harnesses.claude_code.source import ClaudeCodeFileSource
from agent_worklog.models.time_range import DateRange

TZ = ZoneInfo("Asia/Taipei")
PERIOD = DateRange(
    since=datetime(2026, 7, 20, tzinfo=TZ),
    until=datetime(2026, 7, 27, tzinfo=TZ),
)


def _record(uuid: str, timestamp: str, cwd: str = "/repo/main") -> str:
    return json.dumps(
        {
            "type": "user",
            "origin": {"kind": "human"},
            "message": {"role": "user", "content": f"work item {uuid}"},
            "uuid": uuid,
            "timestamp": timestamp,
            "cwd": cwd,
            "gitBranch": "main",
        }
    )


def _write_session(path: Path, *, timestamp: str, mtime: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_record("u-1", timestamp) + "\n", encoding="utf-8")
    stamp = mtime.timestamp()
    os.utime(path, (stamp, stamp))


@pytest.fixture
def projects(tmp_path: Path) -> Path:
    root = tmp_path / "projects"
    _write_session(
        root / "-repo-main" / "sess-in.jsonl",
        timestamp="2026-07-21T01:00:00.000Z",
        mtime=datetime(2026, 7, 21, tzinfo=TZ),
    )
    _write_session(
        root / "-repo-main" / "sess-stale.jsonl",
        timestamp="2026-07-01T01:00:00.000Z",
        mtime=datetime(2026, 7, 1, tzinfo=TZ),
    )
    _write_session(
        root / "-repo-main" / "sess-in" / "subagents" / "agent-abc.jsonl",
        timestamp="2026-07-21T02:00:00.000Z",
        mtime=datetime(2026, 7, 21, tzinfo=TZ),
    )
    (root / "-repo-main" / "sess-in" / "subagents" / "agent-abc.meta.json").write_text(
        json.dumps({"agentType": "general-purpose", "description": "Implement Task 1"}),
        encoding="utf-8",
    )
    return root


def test_discover_skips_files_last_touched_before_the_period(projects: Path) -> None:
    source = ClaudeCodeFileSource(projects_directory=projects)

    ids = {descriptor.session_id for descriptor in source.discover(PERIOD)}

    assert "sess-in" in ids
    assert "sess-stale" not in ids


def test_discover_includes_subagents_with_parent_and_meta_title(projects: Path) -> None:
    source = ClaudeCodeFileSource(projects_directory=projects)

    subagent = next(
        descriptor
        for descriptor in source.discover(PERIOD)
        if descriptor.session_id == "agent-abc"
    )

    assert subagent.parent_session_id == "sess-in"
    assert subagent.title == "Implement Task 1"
    assert subagent.project_id_hint == "-repo-main"


def test_root_only_excludes_subagents(projects: Path) -> None:
    source = ClaudeCodeFileSource(projects_directory=projects, root_only=True)

    ids = {descriptor.session_id for descriptor in source.discover(PERIOD)}

    assert ids == {"sess-in"}


def test_discover_returns_a_usable_source_location(projects: Path) -> None:
    source = ClaudeCodeFileSource(projects_directory=projects)

    descriptor = next(
        item for item in source.discover(PERIOD) if item.session_id == "sess-in"
    )

    assert descriptor.source_location is not None
    assert Path(descriptor.source_location).is_file()
    assert descriptor.harness == "claude-code"


def test_load_returns_a_mapped_session(projects: Path) -> None:
    source = ClaudeCodeFileSource(projects_directory=projects)
    descriptor = next(
        item for item in source.discover(PERIOD) if item.session_id == "sess-in"
    )

    session = source.load(descriptor)

    assert session.harness == "claude-code"
    assert session.working_directory == "/repo/main"
    assert [activity.content for activity in session.activities] == ["work item u-1"]


def test_load_skips_a_torn_trailing_line(projects: Path) -> None:
    """Claude Code appends live, so the last line can be half-written."""

    path = projects / "-repo-main" / "sess-in.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"type":"user","origin":{"kind":"hum')
    source = ClaudeCodeFileSource(projects_directory=projects)
    descriptor = next(
        item for item in source.discover(PERIOD) if item.session_id == "sess-in"
    )

    session = source.load(descriptor)

    assert len(session.activities) == 1


def test_load_without_source_location_raises(projects: Path) -> None:
    from agent_worklog.models.session import SessionDescriptor

    source = ClaudeCodeFileSource(projects_directory=projects)

    with pytest.raises(SessionParseError):
        source.load(SessionDescriptor(harness="claude-code", session_id="ghost"))


def test_discover_on_a_missing_projects_directory_returns_nothing(tmp_path: Path) -> None:
    source = ClaudeCodeFileSource(projects_directory=tmp_path / "absent")

    assert source.discover(PERIOD) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/harnesses/claude_code/test_source.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_worklog.harnesses.claude_code.source'`

- [ ] **Step 3: Write the source**

Create `src/agent_worklog/harnesses/claude_code/source.py`:

```python
"""Claude Code session discovery and loading from local JSONL transcripts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_worklog.errors import SessionParseError
from agent_worklog.harnesses.base import HarnessSessionSource
from agent_worklog.harnesses.claude_code.mapper import ClaudeCodeJsonlMapper
from agent_worklog.models.session import AgentSession, SessionDescriptor
from agent_worklog.models.time_range import DateRange

HARNESS_NAME = "claude-code"

# Reading a whole multi-megabyte transcript just to date it is wasteful; the
# opening records always carry the timestamp and cwd.
_HEAD_RECORD_LIMIT = 50


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _iter_records(text: str) -> list[Mapping[str, Any]]:
    records: list[Mapping[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            # Claude Code appends live, so the final line can be torn. Skipping
            # it keeps the rest of the session usable.
            continue
        if isinstance(record, Mapping):
            records.append(record)
    return records


class ClaudeCodeFileSource(HarnessSessionSource):
    """Read every Claude Code project transcript under one projects directory."""

    def __init__(
        self,
        *,
        projects_directory: Path,
        root_only: bool = False,
    ) -> None:
        self._projects_directory = projects_directory
        self._root_only = root_only

    def _session_files(self) -> list[Path]:
        root = self._projects_directory
        if not root.is_dir():
            return []
        files = sorted(root.glob("*/*.jsonl"))
        if not self._root_only:
            files.extend(sorted(root.glob("*/*/subagents/*.jsonl")))
        return files

    def _subagent_title(self, path: Path) -> str | None:
        meta_path = path.with_suffix(".meta.json")
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, Mapping):
            return None
        description = payload.get("description")
        return description if isinstance(description, str) and description else None

    def _head_hints(self, path: Path) -> tuple[datetime | None, str | None]:
        created_at: datetime | None = None
        working_directory: str | None = None
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                for index, line in enumerate(handle):
                    if index >= _HEAD_RECORD_LIMIT:
                        break
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        record = json.loads(stripped)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(record, Mapping):
                        continue
                    if created_at is None:
                        created_at = _parse_timestamp(record.get("timestamp"))
                    if working_directory is None:
                        cwd = record.get("cwd")
                        if isinstance(cwd, str) and cwd:
                            working_directory = cwd
                    if created_at is not None and working_directory is not None:
                        break
        except OSError:
            return None, None
        return created_at, working_directory

    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        descriptors: list[SessionDescriptor] = []
        for path in self._session_files():
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            except OSError:
                continue
            if mtime < period.since:
                continue

            created_at, working_directory = self._head_hints(path)
            if created_at is not None and created_at >= period.until:
                continue

            is_subagent = path.parent.name == "subagents"
            descriptors.append(
                SessionDescriptor(
                    harness=HARNESS_NAME,
                    session_id=path.stem,
                    source_location=str(path),
                    title=self._subagent_title(path) if is_subagent else None,
                    created_at=created_at,
                    updated_at=mtime,
                    working_directory_hint=working_directory,
                    project_id_hint=(
                        path.parent.parent.parent.name if is_subagent else path.parent.name
                    ),
                    parent_session_id=path.parent.parent.name if is_subagent else None,
                )
            )
        return descriptors

    def load(self, descriptor: SessionDescriptor) -> AgentSession:
        if descriptor.source_location is None:
            raise SessionParseError(
                f"Claude Code session {descriptor.session_id} has no source location"
            )
        path = Path(descriptor.source_location)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise SessionParseError(
                f"Claude Code transcript unreadable for {descriptor.session_id}: {exc}"
            ) from exc
        return ClaudeCodeJsonlMapper().map(_iter_records(text), descriptor)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/harnesses/claude_code/test_source.py -q`
Expected: PASS, 8 tests.

- [ ] **Step 5: Lint, typecheck, full suite**

Run: `uv run ruff check . && uv run pyright && uv run pytest -q`
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add src/agent_worklog/harnesses/claude_code/source.py tests/unit/harnesses/claude_code/test_source.py
git commit -m "feat: discover and load Claude Code sessions from JSONL

Glob the projects directory, prefilter on file mtime, and read only the
opening records to date each session. Exact period filtering stays with
filter_session_to_period after load, as the two-phase source contract
intends."
```

---

## Task 4: Per-model usage table and the `usage_provider` signature

`ReportService` calls `usage_provider` after the scan, but the current signature takes no arguments, so a Claude Code provider cannot see the sessions it needs. Widening it to accept the `ScanResult` is a one-line change that OpenCode ignores.

**Files:**
- Create: `src/agent_worklog/harnesses/claude_code/usage.py`
- Modify: `src/agent_worklog/services/report.py:54` (signature), `:108-112` (call site and message)
- Modify: `src/agent_worklog/cli.py:151-155` (OpenCode provider takes and ignores the argument)
- Test: `tests/unit/harnesses/claude_code/test_usage.py`

**Interfaces:**
- Consumes: `agent_worklog.services.scan.ScanResult` (has `.resolved_sessions: list[ResolvedSession]`, each with `.session.activities`), assistant activity `metadata["model"]` / `metadata["usage"]` from Task 2
- Produces: `render_claude_code_usage(scan: ScanResult) -> str`. Task 6 passes it as `usage_provider`. `ReportService.usage_provider` becomes `Callable[[ScanResult], str] | None`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/harnesses/claude_code/test_usage.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agent_worklog.errors import HarnessSourceError
from agent_worklog.harnesses.claude_code.usage import render_claude_code_usage
from agent_worklog.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from agent_worklog.models.session import ActivityType, AgentSession, SessionActivity
from agent_worklog.models.time_range import DateRange
from agent_worklog.services.scan import ScanResult

TZ = ZoneInfo("Asia/Taipei")
PERIOD = DateRange(
    since=datetime(2026, 7, 20, tzinfo=TZ),
    until=datetime(2026, 7, 27, tzinfo=TZ),
)


def _activity(activity_id: str, model: str, usage: dict[str, int]) -> SessionActivity:
    return SessionActivity(
        activity_id=activity_id,
        activity_type=ActivityType.ASSISTANT_MESSAGE,
        timestamp=datetime(2026, 7, 21, tzinfo=TZ),
        content="did the thing",
        metadata={"model": model, "usage": usage},
    )


def _scan(*activities: SessionActivity) -> ScanResult:
    session = AgentSession(
        harness="claude-code",
        session_id="sess-1",
        activities=list(activities),
    )
    resolved = ResolvedSession(
        session=session,
        repository=RepositoryIdentity(
            repository_id="git:github.com/mike/agent-worklog",
            display_name="Agent Worklog",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            resolution_method="git_origin_remote",
        ),
    )
    return ScanResult(
        period=PERIOD,
        candidate_session_count=1,
        loaded_session_count=1,
        failed_session_count=0,
        resolved_sessions=[resolved],
    )


def test_renders_one_row_per_model_plus_a_total() -> None:
    scan = _scan(
        _activity(
            "a-1",
            "claude-opus-5",
            {
                "input_tokens": 10,
                "output_tokens": 200,
                "cache_read_tokens": 1000,
                "cache_write_tokens": 50,
            },
        ),
        _activity(
            "a-2",
            "claude-opus-5",
            {"input_tokens": 5, "output_tokens": 100, "cache_read_tokens": 0},
        ),
        _activity(
            "a-3",
            "claude-sonnet-5",
            {"input_tokens": 1, "output_tokens": 2},
        ),
    )

    text = render_claude_code_usage(scan)
    lines = text.splitlines()

    assert lines[0].startswith("Model")
    for label in ("Input", "Output", "Cache read", "Cache write"):
        assert label in lines[0]
    assert "claude-opus-5" in lines[1]
    assert "300" in lines[1]  # 200 + 100 output tokens
    assert "1,000" in lines[1]  # thousands separator
    assert "claude-sonnet-5" in lines[2]
    assert lines[3].startswith("Total")
    assert "302" in lines[3]  # 300 + 2 output tokens


def test_orders_models_by_output_tokens_descending() -> None:
    scan = _scan(
        _activity("a-1", "small-model", {"output_tokens": 1}),
        _activity("a-2", "big-model", {"output_tokens": 999}),
    )

    lines = render_claude_code_usage(scan).splitlines()

    assert "big-model" in lines[1]
    assert "small-model" in lines[2]


def test_raises_when_no_activity_carries_usage() -> None:
    """ReportService turns HarnessSourceError into a report warning."""

    scan = _scan(
        SessionActivity(
            activity_id="a-1",
            activity_type=ActivityType.ASSISTANT_MESSAGE,
            timestamp=datetime(2026, 7, 21, tzinfo=TZ),
            content="no usage metadata",
        )
    )

    with pytest.raises(HarnessSourceError):
        render_claude_code_usage(scan)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/harnesses/claude_code/test_usage.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_worklog.harnesses.claude_code.usage'`

- [ ] **Step 3: Write the usage renderer**

Create `src/agent_worklog/harnesses/claude_code/usage.py`. Output is aligned plain text, not a Markdown table: `templates/worklog.md.j2` renders `usage_text` inside a ```` ```text ```` fence, where pipe syntax would show as literal characters.

```python
"""Aggregate Claude Code token usage from mapped session activities."""

from __future__ import annotations

from agent_worklog.errors import HarnessSourceError
from agent_worklog.services.scan import ScanResult

_COLUMNS = (
    ("Input", "input_tokens"),
    ("Output", "output_tokens"),
    ("Cache read", "cache_read_tokens"),
    ("Cache write", "cache_write_tokens"),
)


def _totals_by_model(scan: ScanResult) -> dict[str, dict[str, int]]:
    totals: dict[str, dict[str, int]] = {}
    for resolved in scan.resolved_sessions:
        for activity in resolved.session.activities:
            model = activity.metadata.get("model")
            usage = activity.metadata.get("usage")
            if not isinstance(model, str) or not isinstance(usage, dict):
                continue
            row = totals.setdefault(model, {})
            for _, key in _COLUMNS:
                value = usage.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    row[key] = row.get(key, 0) + value
    return totals


def render_claude_code_usage(scan: ScanResult) -> str:
    """Return an aligned per-model token table for the scanned sessions.

    Unlike `opencode stats`, this covers exactly the report period: usage rides
    on the activities that `filter_session_to_period` already narrowed.
    """

    totals = _totals_by_model(scan)
    if not totals:
        raise HarnessSourceError("Claude Code sessions carried no token usage")

    ordered = sorted(
        totals.items(),
        key=lambda item: (-item[1].get("output_tokens", 0), item[0]),
    )
    grand_total = {
        key: sum(row.get(key, 0) for _, row in ordered) for _, key in _COLUMNS
    }

    headers = ["Model", *(label for label, _ in _COLUMNS)]
    rows = [
        [model, *(f"{row.get(key, 0):,}" for _, key in _COLUMNS)]
        for model, row in ordered
    ]
    rows.append(["Total", *(f"{grand_total[key]:,}" for _, key in _COLUMNS)])

    widths = [
        max(len(cell) for cell in column) for column in zip(headers, *rows, strict=True)
    ]
    lines = [
        headers[0].ljust(widths[0])
        + "".join(f"  {header.rjust(widths[index + 1])}" for index, header in enumerate(headers[1:]))
    ]
    for row in rows:
        lines.append(
            row[0].ljust(widths[0])
            + "".join(f"  {cell.rjust(widths[index + 1])}" for index, cell in enumerate(row[1:]))
        )
    return "\n".join(lines)
```

- [ ] **Step 4: Widen the `usage_provider` signature**

In `src/agent_worklog/services/report.py`, change the constructor parameter on line 54 from `usage_provider: Callable[[], str] | None = None` to:

```python
        usage_provider: Callable[[ScanResult], str] | None = None,
```

Then change the call site (lines 108-112) from `self._usage_provider()` to pass the scan, and drop the harness name from the warning:

```python
        if self._usage_provider is not None:
            try:
                usage_text = redact_text(self._usage_provider(scan))
            except HarnessSourceError as exc:
                warnings.append(f"usage statistics unavailable: {exc}")
```

- [ ] **Step 5: Update the OpenCode provider to accept and ignore the argument**

In `src/agent_worklog/cli.py`, change the `usage_provider` lambda (lines 151-155) to take an unused parameter:

```python
        usage_provider=lambda _scan: collect_usage_stats(
            runner=stats_runner,
            executable=cli_settings.executable,
            days=days,
        ),
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/unit/harnesses/claude_code/test_usage.py -q`
Expected: PASS, 3 tests.

Then the full suite: `uv run pytest -q`
Expected: PASS. If `tests/integration/test_report_service.py` constructs a zero-argument `usage_provider`, update it to take `_scan` — that is the only expected fallout.

- [ ] **Step 7: Lint and typecheck**

Run: `uv run ruff check . && uv run pyright`
Expected: both clean.

- [ ] **Step 8: Commit**

```bash
git add src/agent_worklog/harnesses/claude_code/usage.py src/agent_worklog/services/report.py \
        src/agent_worklog/cli.py tests
git commit -m "feat: build the usage table from Claude Code token metadata

usage_provider now receives the ScanResult, so a harness can derive usage
from the sessions themselves. Claude Code usage covers exactly the report
period, unlike the widened window opencode stats requires."
```

---

## Task 5: MEDIUM-confidence evidence when no exit code exists

Claude Code's `toolUseResult` carries no exit code, so `_exit_code()` always returns `None` and both the `nonzero_exit_code` error path and the `successful_verification_command` outcome path go silent. Fall back to the stderr flags at MEDIUM confidence.

`RuleBasedSummarizer` currently drops anything that is not HIGH, so the heuristic also needs the summarizer widened — otherwise it produces evidence that never appears in a `--no-llm` report.

**Files:**
- Modify: `src/agent_worklog/extraction/pipeline.py:137-161`
- Modify: `src/agent_worklog/summarizers/rule_based.py:39-45`
- Test: `tests/unit/extraction/test_pipeline.py`, `tests/unit/summarizers/test_rule_based.py`

**Interfaces:**
- Consumes: tool-call `metadata["stderr_empty"]` / `metadata["interrupted"]` from Task 2
- Produces: nothing new — existing `EvidenceItem` shapes with `confidence=EvidenceConfidence.MEDIUM` and `extraction_method="stderr_heuristic"`. MEDIUM items reach `RepositorySummary.completed` with a `" (inferred)"` suffix; Task 7 asserts on that text.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/extraction/test_pipeline.py`:

```python
def test_clean_stderr_yields_a_medium_verification_outcome() -> None:
    resolved = ResolvedSession(
        session=AgentSession(
            harness="claude-code",
            session_id="sess-1",
            working_directory="/repo/main",
            activities=[
                SessionActivity(
                    activity_id="a-1",
                    activity_type=ActivityType.TOOL_CALL,
                    timestamp=datetime(2026, 7, 21, tzinfo=UTC),
                    content="pytest -q",
                    tool_name="Bash",
                    metadata={"stderr_empty": True, "interrupted": False},
                )
            ],
        ),
        repository=RepositoryIdentity(
            repository_id="git:github.com/mike/agent-worklog",
            display_name="Agent Worklog",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            resolution_method="git_origin_remote",
        ),
    )

    evidence = extract_evidence(resolved)

    assert len(evidence.outcomes) == 1
    outcome = evidence.outcomes[0]
    assert outcome.text == "Verification passed: pytest -q"
    assert outcome.confidence is EvidenceConfidence.MEDIUM
    assert outcome.extraction_method == "stderr_heuristic"
    assert outcome.status is EvidenceStatus.COMPLETED


def test_nonempty_stderr_yields_a_medium_error() -> None:
    resolved = ResolvedSession(
        session=AgentSession(
            harness="claude-code",
            session_id="sess-1",
            working_directory="/repo/main",
            activities=[
                SessionActivity(
                    activity_id="a-1",
                    activity_type=ActivityType.TOOL_CALL,
                    timestamp=datetime(2026, 7, 21, tzinfo=UTC),
                    content="ruff check .",
                    tool_name="Bash",
                    metadata={"stderr_empty": False, "interrupted": False},
                )
            ],
        ),
        repository=RepositoryIdentity(
            repository_id="git:github.com/mike/agent-worklog",
            display_name="Agent Worklog",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            resolution_method="git_origin_remote",
        ),
    )

    evidence = extract_evidence(resolved)

    assert len(evidence.errors) == 1
    error = evidence.errors[0]
    assert error.text == "ruff check ."
    assert error.confidence is EvidenceConfidence.MEDIUM
    assert error.extraction_method == "stderr_heuristic"
    assert error.status is EvidenceStatus.BLOCKED


def test_interrupted_command_yields_no_verification_outcome() -> None:
    resolved = ResolvedSession(
        session=AgentSession(
            harness="claude-code",
            session_id="sess-1",
            working_directory="/repo/main",
            activities=[
                SessionActivity(
                    activity_id="a-1",
                    activity_type=ActivityType.TOOL_CALL,
                    timestamp=datetime(2026, 7, 21, tzinfo=UTC),
                    content="pytest -q",
                    tool_name="Bash",
                    metadata={"stderr_empty": True, "interrupted": True},
                )
            ],
        ),
        repository=RepositoryIdentity(
            repository_id="git:github.com/mike/agent-worklog",
            display_name="Agent Worklog",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            resolution_method="git_origin_remote",
        ),
    )

    evidence = extract_evidence(resolved)

    assert evidence.outcomes == []
    assert evidence.commands  # the command itself is still evidence


def test_missing_stderr_metadata_leaves_opencode_behavior_untouched() -> None:
    """OpenCode tool calls have no stderr flags; nothing new should appear."""

    resolved = ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id="sess-1",
            working_directory="/repo/main",
            activities=[
                SessionActivity(
                    activity_id="a-1",
                    activity_type=ActivityType.TOOL_CALL,
                    timestamp=datetime(2026, 7, 21, tzinfo=UTC),
                    content="pytest -q",
                    tool_name="bash",
                )
            ],
        ),
        repository=RepositoryIdentity(
            repository_id="git:github.com/mike/agent-worklog",
            display_name="Agent Worklog",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            resolution_method="git_origin_remote",
        ),
    )

    evidence = extract_evidence(resolved)

    assert evidence.outcomes == []
    assert evidence.errors == []
```

Match the existing file's imports. If any of `EvidenceConfidence`, `EvidenceStatus`, `UTC`, `RepositoryIdentityType`, or `SessionActivity` is not already imported there, add it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/extraction/test_pipeline.py -q -k "stderr or interrupted or opencode_behavior"`
Expected: FAIL — the two MEDIUM tests find zero outcomes/errors. `test_missing_stderr_metadata_leaves_opencode_behavior_untouched` passes already; that is the regression guard.

- [ ] **Step 3: Add the heuristic branch**

In `src/agent_worklog/extraction/pipeline.py`, extend the exit-code block inside the command branch. Replace lines 137-161 with:

```python
            exit_code = _exit_code(activity)
            if exit_code is not None and exit_code != 0:
                _append_unique(
                    evidence.errors,
                    _item(
                        text=content,
                        activity=activity,
                        confidence=EvidenceConfidence.HIGH,
                        extraction_method="nonzero_exit_code",
                        status=EvidenceStatus.BLOCKED,
                    ),
                    repository_id=repository_id,
                )
            elif exit_code == 0 and is_verification_command(content):
                _append_unique(
                    evidence.outcomes,
                    _item(
                        text=f"Verification passed: {content}",
                        activity=activity,
                        confidence=EvidenceConfidence.HIGH,
                        extraction_method="successful_verification_command",
                        status=EvidenceStatus.COMPLETED,
                    ),
                    repository_id=repository_id,
                )
            elif exit_code is None:
                _append_stderr_heuristic(
                    evidence,
                    activity=activity,
                    content=content,
                    repository_id=repository_id,
                )
            continue
```

Then add the helper above `extract_evidence`:

```python
def _append_stderr_heuristic(
    evidence: SessionEvidence,
    *,
    activity: SessionActivity,
    content: str,
    repository_id: str,
) -> None:
    """Infer command success from stderr when the harness reports no exit code.

    Claude Code's tool results carry no exit code, so this is the only signal
    available. It is a guess — pytest writes failures to stdout — so everything
    it produces is MEDIUM confidence, never HIGH.
    """

    stderr_empty = activity.metadata.get("stderr_empty")
    if stderr_empty is False:
        _append_unique(
            evidence.errors,
            _item(
                text=content,
                activity=activity,
                confidence=EvidenceConfidence.MEDIUM,
                extraction_method="stderr_heuristic",
                status=EvidenceStatus.BLOCKED,
            ),
            repository_id=repository_id,
        )
        return
    if (
        stderr_empty is True
        and activity.metadata.get("interrupted") is not True
        and is_verification_command(content)
    ):
        _append_unique(
            evidence.outcomes,
            _item(
                text=f"Verification passed: {content}",
                activity=activity,
                confidence=EvidenceConfidence.MEDIUM,
                extraction_method="stderr_heuristic",
                status=EvidenceStatus.COMPLETED,
            ),
            repository_id=repository_id,
        )
```

`stderr_empty is False` / `is True` (not truthiness) is deliberate: an OpenCode activity has no such key, so `None` falls through and nothing is emitted.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/extraction/test_pipeline.py -q`
Expected: PASS, including every pre-existing test.

- [ ] **Step 5: Write the failing summarizer test**

`summarizers/rule_based.py:39-45` filters outcomes to `confidence == EvidenceConfidence.HIGH`, so every MEDIUM item produced above is currently dropped before it reaches the report. Add to `tests/unit/summarizers/test_rule_based.py`:

```python
def test_medium_confidence_outcomes_are_reported_as_inferred() -> None:
    evidence = RepositoryEvidence(
        repository_id="git:github.com/mike/agent-worklog",
        display_name="Agent Worklog",
        sessions=[
            SessionEvidence(
                session_id="sess-1",
                repository_id="git:github.com/mike/agent-worklog",
                outcomes=[
                    EvidenceItem(
                        text="Verification passed: pytest -q",
                        source_activity_ids=["a-1"],
                        confidence=EvidenceConfidence.MEDIUM,
                        extraction_method="stderr_heuristic",
                        status=EvidenceStatus.COMPLETED,
                    ),
                    EvidenceItem(
                        text="Verification passed: ruff check .",
                        source_activity_ids=["a-2"],
                        confidence=EvidenceConfidence.HIGH,
                        extraction_method="successful_verification_command",
                        status=EvidenceStatus.COMPLETED,
                    ),
                ],
            )
        ],
    )

    summary = RuleBasedSummarizer().summarize(evidence)

    assert "Verification passed: pytest -q (inferred)" in summary.completed
    assert "Verification passed: ruff check ." in summary.completed


def test_low_confidence_outcomes_are_still_excluded() -> None:
    """Assistant self-claims stay out of the report; only stderr inference is promoted."""

    evidence = RepositoryEvidence(
        repository_id="git:github.com/mike/agent-worklog",
        display_name="Agent Worklog",
        sessions=[
            SessionEvidence(
                session_id="sess-1",
                repository_id="git:github.com/mike/agent-worklog",
                outcomes=[
                    EvidenceItem(
                        text="I implemented the retry",
                        source_activity_ids=["a-1"],
                        confidence=EvidenceConfidence.LOW,
                        extraction_method="assistant_claim",
                        status=EvidenceStatus.COMPLETED,
                    )
                ],
            )
        ],
    )

    summary = RuleBasedSummarizer().summarize(evidence)

    assert summary.completed == []
```

Match the existing file's imports; add `EvidenceConfidence`, `EvidenceItem`, `EvidenceStatus`, `RepositoryEvidence`, `SessionEvidence` if missing.

Run: `uv run pytest tests/unit/summarizers/test_rule_based.py -q -k "inferred or low_confidence"`
Expected: the `inferred` test FAILS (`summary.completed` is missing the MEDIUM item); the LOW test passes already as a regression guard.

- [ ] **Step 6: Widen the summarizer filter**

In `src/agent_worklog/summarizers/rule_based.py`, replace `_completed` (lines 39-45) with:

```python
# MEDIUM evidence is inferred rather than observed, so it is labelled in the
# report instead of being presented as a confirmed outcome.
_INFERRED_SUFFIX = " (inferred)"
_REPORTABLE_CONFIDENCE = (EvidenceConfidence.HIGH, EvidenceConfidence.MEDIUM)


def _completed(items: list[EvidenceItem]) -> list[str]:
    return [
        item.text + (_INFERRED_SUFFIX if item.confidence == EvidenceConfidence.MEDIUM else "")
        for item in items
        if item.status == EvidenceStatus.COMPLETED
        and item.confidence in _REPORTABLE_CONFIDENCE
    ]
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/summarizers/test_rule_based.py tests/unit/extraction/test_pipeline.py -q`
Expected: PASS, including every pre-existing test.

- [ ] **Step 8: Lint, typecheck, full suite**

Run: `uv run ruff check . && uv run pyright && uv run pytest -q`
Expected: all clean.

- [ ] **Step 9: Commit**

```bash
git add src/agent_worklog/extraction/pipeline.py src/agent_worklog/summarizers/rule_based.py \
        tests/unit/extraction/test_pipeline.py tests/unit/summarizers/test_rule_based.py
git commit -m "feat: infer command outcomes from stderr at MEDIUM confidence

Claude Code tool results carry no exit code, which silenced both the
verification-passed outcome and the failed-command error. Fall back to the
stderr flags, marked MEDIUM because pytest writes failures to stdout.

RuleBasedSummarizer only reported HIGH evidence, so the new items would
never have reached a --no-llm report. It now reports MEDIUM too, suffixed
with '(inferred)' so the distinction survives into the Markdown."
```

---

## Task 6: `--harness` wiring, settings, and doctor dispatch

**Files:**
- Modify: `src/agent_worklog/config.py` (add `ClaudeCodeSettings`, extend `HarnessSettings`)
- Modify: `src/agent_worklog/cli.py` (add `Harness` enum, `--harness` on all three commands, dispatch in `_build_scan_service` / `_build_report_service`, harness-named `NoSessionsError` messages)
- Modify: `src/agent_worklog/services/doctor.py` (dispatch checks by harness)
- Modify: `src/agent_worklog/services/scan.py:90-91` (harness-named failure message)
- Test: `tests/unit/test_config.py`, `tests/unit/services/test_doctor.py`, `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `ClaudeCodeFileSource` (Task 3), `render_claude_code_usage` (Task 4)
- Produces: `cli.Harness` StrEnum with members `OPENCODE = "opencode"` and `CLAUDE_CODE = "claude-code"`; `AppSettings().harnesses.claude_code.projects_directory: Path`; `run_doctor(settings, *, runner, harness)`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_config.py`:

```python
def test_claude_code_projects_directory_defaults_under_home() -> None:
    from pathlib import Path

    from agent_worklog.config import AppSettings

    settings = AppSettings()

    assert settings.harnesses.claude_code.projects_directory == (
        Path.home() / ".claude" / "projects"
    )


def test_claude_code_projects_directory_is_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pathlib import Path

    from agent_worklog.config import AppSettings

    monkeypatch.setenv(
        "AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY",
        "/tmp/claude-projects",
    )

    settings = AppSettings()

    assert settings.harnesses.claude_code.projects_directory == Path("/tmp/claude-projects")
```

Add to `tests/unit/services/test_doctor.py`:

```python
def test_doctor_skips_opencode_checks_for_claude_code(tmp_path) -> None:
    from agent_worklog.config import AppSettings
    from agent_worklog.services.doctor import run_doctor

    class RecordingRunner:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def run(self, args: list[str]) -> CommandResult:
            self.calls.append(args)
            return CommandResult(0, "git version 2.0.0", "")

    settings = AppSettings()
    settings.harnesses.claude_code.projects_directory = tmp_path
    runner = RecordingRunner()

    result = run_doctor(settings, runner=runner, harness="claude-code")

    assert result.ok
    assert all(call[0] != "opencode" for call in runner.calls)
    assert any("claude code projects" in check.name for check in result.checks)


def test_doctor_fails_when_the_projects_directory_is_missing(tmp_path) -> None:
    from agent_worklog.config import AppSettings
    from agent_worklog.services.doctor import run_doctor

    class GitOnlyRunner:
        def run(self, args: list[str]) -> CommandResult:
            return CommandResult(0, "git version 2.0.0", "")

    settings = AppSettings()
    settings.harnesses.claude_code.projects_directory = tmp_path / "absent"

    result = run_doctor(settings, runner=GitOnlyRunner(), harness="claude-code")

    assert not result.ok
```

Add to `tests/unit/test_cli.py`:

```python
def test_scan_rejects_an_unknown_harness() -> None:
    from typer.testing import CliRunner

    import agent_worklog.cli as cli

    result = CliRunner().invoke(cli.app, ["scan", "--days", "7", "--harness", "codex"])

    assert result.exit_code == 2


def test_build_scan_service_selects_the_claude_code_source(tmp_path) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import agent_worklog.cli as cli
    from agent_worklog.config import AppSettings
    from agent_worklog.harnesses.claude_code.source import ClaudeCodeFileSource
    from agent_worklog.models.time_range import DateRange

    tz = ZoneInfo("Asia/Taipei")
    settings = AppSettings()
    settings.harnesses.claude_code.projects_directory = tmp_path
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=tz),
        until=datetime(2026, 7, 27, tzinfo=tz),
    )

    service = cli._build_scan_service(
        settings,
        period,
        harness=cli.Harness.CLAUDE_CODE,
    )

    assert isinstance(service._source, ClaudeCodeFileSource)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_config.py tests/unit/services/test_doctor.py tests/unit/test_cli.py -q`
Expected: FAIL — `AttributeError: 'HarnessSettings' object has no attribute 'claude_code'`, `run_doctor() got an unexpected keyword argument 'harness'`, `module 'agent_worklog.cli' has no attribute 'Harness'`.

- [ ] **Step 3: Add the settings**

In `src/agent_worklog/config.py`, import `Path` (already imported) and add after `OpenCodeSettings`:

```python
class ClaudeCodeSettings(BaseModel):
    """Claude Code harness settings."""

    enabled: bool = True
    projects_directory: Path = Field(
        default_factory=lambda: Path.home() / ".claude" / "projects"
    )
```

Then extend `HarnessSettings`:

```python
class HarnessSettings(BaseModel):
    """Configured coding-agent harnesses."""

    opencode: OpenCodeSettings = Field(default_factory=OpenCodeSettings)
    claude_code: ClaudeCodeSettings = Field(default_factory=ClaudeCodeSettings)
```

`default_factory` matters: evaluating `Path.home()` at class-definition time would bake in whichever home directory imported the module first.

- [ ] **Step 4: Dispatch the doctor checks**

Rewrite `run_doctor` in `src/agent_worklog/services/doctor.py`:

```python
def run_doctor(
    settings: AppSettings,
    *,
    runner: Runner,
    harness: str = "opencode",
) -> DoctorResult:
    """Validate the selected harness and Git without exposing env values."""

    checks: list[DoctorCheck] = []
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
    else:
        executable = settings.harnesses.opencode.cli.executable
        checks.append(_check(runner, "opencode version", [executable, "--version"]))
        checks.append(_check(runner, "opencode database", [executable, "db", "path"]))
    checks.append(_check(runner, "git", ["git", "--version"]))
    return DoctorResult(checks=checks)
```

Add `import os` at the top of the file.

- [ ] **Step 5: Wire the CLI**

In `src/agent_worklog/cli.py`:

Add imports and the enum near the top (after the existing imports):

```python
from enum import StrEnum

from agent_worklog.harnesses.claude_code.source import ClaudeCodeFileSource
from agent_worklog.harnesses.claude_code.usage import render_claude_code_usage


class Harness(StrEnum):
    OPENCODE = "opencode"
    CLAUDE_CODE = "claude-code"
```

Replace `_build_scan_service` with:

```python
def _build_scan_service(
    settings: AppSettings,
    period: DateRange,
    root_only: bool = False,
    *,
    harness: Harness = Harness.OPENCODE,
) -> ScanService:
    git_runner = CommandRunner(timeout_seconds=5.0)
    source: HarnessSessionSource
    if harness is Harness.CLAUDE_CODE:
        source = ClaudeCodeFileSource(
            projects_directory=settings.harnesses.claude_code.projects_directory,
            root_only=root_only,
        )
    else:
        cli_settings = settings.harnesses.opencode.cli
        source = OpenCodeCliSource(
            runner=CommandRunner(timeout_seconds=cli_settings.timeout_seconds),
            executable=cli_settings.executable,
            root_only=root_only,
        )
    return ScanService(
        source=source,
        period=period,
        resolver=RepositoryResolver(runner=git_runner),
    )
```

Add `from agent_worklog.harnesses.base import HarnessSessionSource` to the imports.

Add a helper that picks the usage provider, so the two harnesses' wiring stays out of `_build_report_service`:

```python
def _usage_provider(
    settings: AppSettings,
    period: DateRange,
    harness: Harness,
    now: datetime,
) -> tuple[Callable[[ScanResult], str], int | None]:
    """Return the harness usage provider and the window it covers, if narrower."""

    if harness is Harness.CLAUDE_CODE:
        # Usage rides on the already-filtered activities, so the window is exact
        # and needs no "wider than the period" caveat.
        return render_claude_code_usage, None

    cli_settings = settings.harnesses.opencode.cli
    stats_runner = CommandRunner(timeout_seconds=cli_settings.timeout_seconds)
    days = usage_days(period, now)

    def collect(_scan: ScanResult) -> str:
        return collect_usage_stats(
            runner=stats_runner,
            executable=cli_settings.executable,
            days=days,
        )

    return collect, days
```

Replace the usage wiring in `_build_report_service` (it also gains a `harness` keyword):

```python
def _build_report_service(
    settings: AppSettings,
    period: DateRange,
    output_path: Path,
    no_llm: bool,
    root_only: bool = False,
    *,
    now: datetime,
    harness: Harness = Harness.OPENCODE,
) -> ReportService:
    """Build the report service around the command's single clock read."""

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

    usage_provider, days = _usage_provider(settings, period, harness, now)

    return ReportService(
        scan_service=_build_scan_service(settings, period, root_only, harness=harness),
        summarizer=summarizer,
        renderer=MarkdownRenderer(),
        period=period,
        output_path=output_path,
        now_factory=lambda: now,
        usage_provider=usage_provider,
        usage_days=days,
    )
```

Add `from collections.abc import Callable` and `from agent_worklog.services.scan import ScanResult, ScanService` to the imports.

Add the option to all three commands, using the same declaration each time:

```python
    harness: Harness = typer.Option(
        Harness.OPENCODE,
        "--harness",
        help="Coding-agent harness to read sessions from.",
    ),
```

In `doctor`, pass it through: `result = run_doctor(settings, runner=runner, harness=harness.value)`.

In `scan`, pass `harness=harness` to `_build_scan_service` and change the `NoSessionsError` message on line 225 to:

```python
            raise NoSessionsError(f"no {harness.value} activity found in the requested period")
```

In `report`, pass `harness=harness` to `_build_report_service` and apply the same message change on line 282.

- [ ] **Step 6: Make the scan failure message harness-neutral**

In `src/agent_worklog/services/scan.py`, replace lines 90-91:

```python
        if descriptors and successful_exports == 0 and failed_count == len(descriptors):
            raise HarnessSourceError(
                f"all {descriptors[0].harness} session loads failed"
            )
```

If a test asserts the old `"all OpenCode session exports failed"` string, update it to `"all opencode session loads failed"`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_config.py tests/unit/services/test_doctor.py tests/unit/test_cli.py -q`
Expected: PASS.

- [ ] **Step 8: Run the full suite, lint, typecheck**

Run: `uv run pytest -q && uv run ruff check . && uv run pyright`
Expected: all clean. Existing OpenCode CLI tests pass because `--harness` defaults to `opencode`.

- [ ] **Step 9: Commit**

```bash
git add src/agent_worklog tests
git commit -m "feat: add --harness so Claude Code sessions can be reported

--harness defaults to opencode, so existing behavior is unchanged. doctor
checks the projects directory instead of running a harness CLI when
Claude Code is selected."
```

---

## Task 7: End-to-end acceptance run

**Files:**
- Create: `tests/fixtures/claude_code/acceptance/` (built by the fixture, not committed as files)
- Modify: `tests/conftest.py` (add a `claude_code_projects` fixture and a git-only runner)
- Test: `tests/integration/test_claude_code_end_to_end.py`

**Interfaces:**
- Consumes: everything from Tasks 1-6
- Produces: nothing — this is the acceptance gate

- [ ] **Step 1: Add the fixtures**

Append to `tests/conftest.py`:

```python
@dataclass
class GitOnlyCommandRunner:
    """Answer git queries for the Claude Code acceptance run; no harness CLI."""

    remotes: dict[str, str] = field(default_factory=dict)

    def run(self, args: list[str]) -> CommandResult:
        if len(args) >= 5 and args[:2] == ["git", "-C"]:
            cwd = args[2]
            command = args[3:]
            if command == ["remote", "get-url", "origin"]:
                remote = self.remotes.get(cwd)
                if remote:
                    return CommandResult(0, remote, "")
                return CommandResult(2, "", "no remote")
            if command == ["rev-parse", "--git-common-dir"]:
                return CommandResult(0, f"{cwd}/.git", "")
            if command == ["branch", "--show-current"]:
                return CommandResult(0, "main", "")
        if args[:1] == ["git"]:
            return CommandResult(0, "git version 2.45.0", "")
        return CommandResult(1, "", f"unexpected command: {args}")


@pytest.fixture
def claude_code_projects(tmp_path: Path) -> Path:
    """A projects directory with one root session and one subagent session."""

    root = tmp_path / "claude-projects"
    session_dir = root / "-repo-agent-worklog"
    session_dir.mkdir(parents=True)

    def record(payload: dict) -> str:
        return json.dumps(payload)

    root_lines = [
        record(
            {
                "type": "user",
                "origin": {"kind": "human"},
                "message": {
                    "role": "user",
                    "content": "Add retry to the price fetcher",
                },
                "uuid": "u-1",
                "timestamp": "2026-07-21T01:00:00.000Z",
                "cwd": "/worktrees/agent-main",
                "gitBranch": "main",
            }
        ),
        record(
            {
                "type": "assistant",
                "message": {
                    "model": "claude-opus-5",
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "I implemented the retry."},
                        {
                            "type": "tool_use",
                            "id": "toolu-1",
                            "name": "Bash",
                            "input": {"command": "pytest -q"},
                        },
                    ],
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 200,
                        "cache_read_input_tokens": 1000,
                        "cache_creation_input_tokens": 50,
                    },
                },
                "uuid": "a-1",
                "timestamp": "2026-07-21T01:00:01.000Z",
                "cwd": "/worktrees/agent-main",
                "gitBranch": "main",
            }
        ),
        record(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "toolu-1", "content": "ok"}
                    ],
                },
                "toolUseResult": {
                    "stdout": "ACCEPTANCE_SECRET_MARKER 42 passed",
                    "stderr": "",
                    "interrupted": False,
                    "isImage": False,
                },
                "uuid": "u-2",
                "timestamp": "2026-07-21T01:00:02.000Z",
                "cwd": "/worktrees/agent-main",
                "gitBranch": "main",
            }
        ),
        record({"type": "ai-title", "aiTitle": "Retry for the price fetcher"}),
    ]
    (session_dir / "root-session.jsonl").write_text(
        "\n".join(root_lines) + "\n", encoding="utf-8"
    )

    subagent_dir = session_dir / "root-session" / "subagents"
    subagent_dir.mkdir(parents=True)
    (subagent_dir / "agent-abc.jsonl").write_text(
        record(
            {
                "type": "user",
                "origin": {"kind": "human"},
                "message": {"role": "user", "content": "Review the retry helper"},
                "uuid": "u-3",
                "timestamp": "2026-07-22T01:00:00.000Z",
                "cwd": "/worktrees/assets",
                "gitBranch": "main",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (subagent_dir / "agent-abc.meta.json").write_text(
        json.dumps({"agentType": "general-purpose", "description": "Review the helper"}),
        encoding="utf-8",
    )
    return root


@pytest.fixture
def git_only_runner() -> GitOnlyCommandRunner:
    return GitOnlyCommandRunner(
        remotes={
            "/worktrees/agent-main": "git@github.com:mike/agent-worklog.git",
            "/worktrees/assets": "git@github.com:mike/assets-tracker.git",
        }
    )
```

- [ ] **Step 2: Write the failing acceptance test**

Create `tests/integration/test_claude_code_end_to_end.py`:

```python
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from typer.testing import CliRunner

import agent_worklog.cli as cli

TZ = ZoneInfo("Asia/Taipei")


def _invoke(
    monkeypatch,
    claude_code_projects: Path,
    git_only_runner,
    output: Path,
    *extra_args: str,
):
    monkeypatch.setattr(
        cli,
        "_now_in_timezone",
        lambda timezone: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )
    monkeypatch.setattr(cli, "CommandRunner", lambda timeout_seconds: git_only_runner)
    monkeypatch.setenv(
        "AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY",
        str(claude_code_projects),
    )
    return CliRunner().invoke(
        cli.app,
        [
            "report",
            "--harness",
            "claude-code",
            "--period",
            "last-week",
            "--no-llm",
            "--output",
            str(output),
            *extra_args,
        ],
    )


def test_claude_code_report_groups_by_repository_and_reports_usage(
    tmp_path: Path,
    monkeypatch,
    claude_code_projects: Path,
    git_only_runner,
) -> None:
    output = tmp_path / "worklog.md"

    result = _invoke(monkeypatch, claude_code_projects, git_only_runner, output)

    assert result.exit_code == 0, result.stdout
    content = output.read_text(encoding="utf-8")
    assert "github.com/mike/agent-worklog" in content
    assert "github.com/mike/assets-tracker" in content
    assert "Retry for the price fetcher" in content
    assert "## Usage" in content
    assert "claude-opus-5" in content
    assert "Window: the last" not in content  # exact period, no widened-window caveat
    assert "ACCEPTANCE_SECRET_MARKER" not in content
    assert "Verification passed: pytest -q (inferred)" in content


def test_root_only_excludes_the_subagent_repository(
    tmp_path: Path,
    monkeypatch,
    claude_code_projects: Path,
    git_only_runner,
) -> None:
    output = tmp_path / "worklog.md"

    result = _invoke(
        monkeypatch,
        claude_code_projects,
        git_only_runner,
        output,
        "--root-only",
    )

    assert result.exit_code == 0, result.stdout
    content = output.read_text(encoding="utf-8")
    assert "github.com/mike/agent-worklog" in content
    assert "github.com/mike/assets-tracker" not in content


def test_scan_reports_the_claude_code_sessions(
    monkeypatch,
    claude_code_projects: Path,
    git_only_runner,
) -> None:
    monkeypatch.setattr(
        cli,
        "_now_in_timezone",
        lambda timezone: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )
    monkeypatch.setattr(cli, "CommandRunner", lambda timeout_seconds: git_only_runner)
    monkeypatch.setenv(
        "AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY",
        str(claude_code_projects),
    )

    result = CliRunner().invoke(
        cli.app,
        ["scan", "--harness", "claude-code", "--period", "last-week"],
    )

    assert result.exit_code == 0, result.stdout
```

- [ ] **Step 3: Run it to verify it fails, then passes**

Run: `uv run pytest tests/integration/test_claude_code_end_to_end.py -q`

If it fails on something other than an assertion — for example the resolver receiving a path that does not exist on disk — read the failure before changing production code. The `GitOnlyCommandRunner` answers `git -C <cwd>` for paths that do not exist, which is what the OpenCode acceptance fixture already does, so resolution should reach the `GIT_REMOTE` tier.

Expected once correct: PASS, 3 tests.

- [ ] **Step 4: Full gate**

Run: `uv run pytest --cov=agent_worklog --cov-fail-under=80 -q && uv run ruff check . && uv run pyright`
Expected: all clean, coverage at or above 80%.

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/integration/test_claude_code_end_to_end.py
git commit -m "test: add the Claude Code end-to-end acceptance run

Covers repository grouping across a root session and a subagent in another
checkout, the exact-period usage table, --root-only, and the guarantee that
tool stdout never reaches the report."
```

---

## Task 8: Documentation

**Files:**
- Modify: `README.md`, `README.zh-TW.md`, `docs/configuration.md`, `docs/privacy.md`, `CHANGELOG.md`
- Test: `tests/unit/test_documentation.py`

**Interfaces:**
- Consumes: the shipped CLI surface from Task 6
- Produces: nothing

- [ ] **Step 1: Extend the documentation test**

In `tests/unit/test_documentation.py`, add:

```python
def test_readme_documents_the_harness_option() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "--harness" in readme
    assert "claude-code" in readme
    assert "Codex and Claude Code are not currently supported." not in readme


def test_privacy_doc_explains_the_claude_code_sanitize_gap() -> None:
    privacy = Path("docs/privacy.md").read_text(encoding="utf-8")

    assert "claude-code" in privacy or "Claude Code" in privacy
    assert "sanitize" in privacy


def test_configuration_doc_lists_the_claude_code_settings() -> None:
    configuration = Path("docs/configuration.md").read_text(encoding="utf-8")

    assert "AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY" in configuration
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_documentation.py -q`
Expected: FAIL on all three new tests.

- [ ] **Step 3: Update `README.md`**

Four edits:

1. In **Capabilities**, change the opening line from "Agent Worklog currently works with OpenCode and can:" to "Agent Worklog works with OpenCode and Claude Code and can:" and add a bullet: "Read Claude Code sessions straight from `~/.claude/projects`, including subagent transcripts."
2. In **Requirements**, note that OpenCode and Git are needed for `--harness opencode`, and that `--harness claude-code` needs only Git plus a readable `~/.claude/projects`.
3. In **Command reference**, add a row to the shared-options table: `` | `--harness NAME` | Harness to read sessions from: `opencode` (default) or `claude-code`. | ``
4. In **Current support and limits**, replace "Codex and Claude Code are not currently supported." with:
   - "Codex is not currently supported."
   - "Claude Code sessions have no exit codes, so verification results are inferred from stderr and marked `(inferred)` in the report."
   - "A Claude Code session that spans several working directories is grouped under the last one."

   In the same section, note that the usage window caveat applies to OpenCode only, because Claude Code usage comes from the sessions themselves.

- [ ] **Step 4: Mirror the changes in `README.zh-TW.md`**

Apply the same four edits in Traditional Chinese, matching the surrounding style. Read the existing file first — the section headings differ from the English version.

- [ ] **Step 5: Update `docs/configuration.md`**

Add the Claude Code settings alongside the OpenCode ones:

```bash
export AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__ENABLED="true"
export AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY="$HOME/.claude/projects"
```

Document that `projects_directory` defaults to `~/.claude/projects`.

- [ ] **Step 6: Update `docs/privacy.md`**

This is the substantive doc change. The current text is built on `opencode export --sanitize`. Add a section explaining that with `--harness claude-code`:

- There is no harness-side sanitize step; Claude Code provides no export command, so Agent Worklog reads the transcripts directly.
- The protection is instead that the adapter keeps only human prompts, assistant text, tool names, and one command or file path per tool call. Tool `stdout` and `stderr`, model thinking, hook output, and system reminders are dropped before anything reaches the report or an LLM request.
- The common secret-pattern checks in `security/redactor.py` still run on top of that.
- Reports may still contain prompts, commands, file paths, and full working-directory paths, exactly as with OpenCode.

- [ ] **Step 7: Update `CHANGELOG.md`**

Add an unreleased entry naming: the `--harness` option, Claude Code session support, the exact-period usage table, the MEDIUM stderr heuristic, and the `CommandRunner` module move.

- [ ] **Step 8: Run the tests and the full gate**

Run: `uv run pytest --cov=agent_worklog --cov-fail-under=80 -q && uv run ruff check . && uv run pyright && uv build`
Expected: all clean.

- [ ] **Step 9: Commit**

```bash
git add README.md README.zh-TW.md docs/configuration.md docs/privacy.md CHANGELOG.md tests/unit/test_documentation.py
git commit -m "docs: document Claude Code support and its privacy tradeoff

Claude Code has no export --sanitize, so privacy.md now explains that the
adapter's deliberate data loss is what replaces it."
```

---

## Final Verification

- [ ] `uv run pytest --cov=agent_worklog --cov-fail-under=80` passes
- [ ] `uv run ruff check .` clean
- [ ] `uv run pyright` clean
- [ ] `uv build` succeeds
- [ ] `agent-worklog doctor --harness claude-code` reports the real projects directory on this machine
- [ ] `agent-worklog report --harness claude-code --days 7 --no-llm --dry-run` produces a real report, and the output is read by a human before anything is shared
- [ ] `agent-worklog report --period last-week --no-llm --dry-run` (no `--harness`) still behaves exactly as before
