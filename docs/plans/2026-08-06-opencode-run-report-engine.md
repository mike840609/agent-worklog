# OpenCode `run` Report Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the external OpenAI-compatible summarizer with the locally installed `opencode run` engine so `report` produces a full narrative weekly review by default, with the existing structured per-repository report retained as an explicit and automatic fallback. Simplify usage by removing the per-invocation remote authorization flag and repurposing `--no-llm` as "skip the narrative, emit the structured report."

**Source of truth:** `docs/opencode-run-report-engine-design.md` (approved). This plan is the task decomposition.

**Architecture:** `ReportService.generate()` gains a narrative branch. When `narrative=True` it builds a grouped raw transcript (`build_grouped_transcript`) plus a prompt and invokes a local `opencode run` via a new `OpenCodeRunner`. On any `OpenCodeRunError` (non-zero exit, empty output, launch failure) it appends a warning and falls back to the existing structured path. The narrative body is wrapped by a minimal header. The CLI always defaults `narrative=True`; `--no-llm` forces the structured path without invoking opencode.

## Global Constraints

- Keep Python `>=3.11`. `httpx` is removed (its only consumer is the OpenAI-compatible summarizer).
- Default report command: `agent-worklog report --days N` invokes `opencode run` locally. No network round-trip trigger; `OPENAI_API_KEY` is no longer read.
- `--no-llm` (repurposed): skip `opencode run` and emit the structured per-repository report.
- `--allow-remote-llm` is removed.
- `opencode run` flags used: `--title`, `--file <transcript>`, `--print-logs`, optional `--model <M>`. The prompt is passed as the positional message (equivalent to the piped-stdin form in `scripts/opencode-weekly-review-git-grouped`, avoiding a third change to the `Runner` protocol and its test doubles).
- The raw transcript is a temporary file in a `tempfile.TemporaryDirectory`, deleted on scope exit; it passes through `redact_text`.
- Every activity and rendered line still passes `redact_text`.
- Release as `v0.7.0` and update `uv.lock` (drop `httpx`).
- All verification uses the repo's dev extras (`pytest`, `pyright`, `ruff`).

---

### Task 1: Grouped-raw-transcript builder

Pure, dependency-free function; nothing else in the suite must change for it to be green.

**Files:**
- Create: `src/agent_worklog/summarizers/transcript.py`
- Create: `tests/unit/summarizers/test_transcript.py`

**Interfaces:**
- Produces: `build_grouped_transcript(*, sessions_by_repository: dict[str, list[ResolvedSession]], period: DateRange, generated_at: datetime, include_all_sessions: bool, sanitized: bool) -> str`

- [ ] **Step 1: Add test**

Cover: header lines (`# Agent Worklog`, `Subagent sessions included`, `Sanitized exports`, counts), per-project `## Project: <display_name>` heading with working-directory/branch lines, per-session `### <title>` with session ID, `**user:**`/`**assistant:**` blocks from `ActivityType.USER_MESSAGE`/`ASSISTANT_MESSAGE`, commands/tools excirude, and secrets redacted via `redact_text`. Repositories sorted by `display_name.casefold()`; sessions sorted by most-recent activity timestamp.

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/unit/summarizers/test_transcript.py -v
```

Expect: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
def build_grouped_transcript(
    *,
    sessions_by_repository: dict[str, list[ResolvedSession]],
    period: DateRange,
    generated_at: datetime,
    include_subagents: bool,
    sanitized: bool,
) -> str:
```

Emit:
- `# Agent Worklog sessions grouped by repository`
- header bullet lines (period, generated, project count, session count, `Sub-project/child sessions included`, `Sanitized exports`),
- per repository (sorted by display name): `## Project: <display_name>`, a `- Repository identity: \`<id>\`` line, a `- Directory: \`<working_directory>\`` line if present, `- Branch: <branch>` if present,
- per session (most-recent-activity first): `### Session: <title or session_id>`, `Session ID: \`<id>\``, then for each `USER_MESSAGE`/`ASSISTANT_MESSAGE` activity `**user:**`/`**assistant:**` followed by `redact_text(content)`.

Invoke `redact_text` on each activity body and on the joined transcript.

- [ ] **Step 4: Verify pass**

```bash
uv run pytest tests/unit/summarizers/test_transcript.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/agent_worklog/summarizers/transcript.py tests/unit/summarizers/test_transcript.py
git commit -m "feat: build grouped raw transcript for the report engine"
```

---

### Task 2: OpenCode `run` runner and prompt

Also approachable in isolation; nothing else consumes it until Task 4.

**Files:**
- Create: `src/agent_worklog/summarizers/opencode_run.py`
- Create: `tests/unit/summarizers/test_opencode_run.py`

**Interfaces:**
- Produces: `class OpenCodeRunError(Exception)` (ad-hoc, not in `errors.py`)
- Produces: `class OpenCodeRunner` with `.run(*, transcript: str, prompt: str, title: str) -> str`
- Produces: `build_summary_prompt(days: int) -> str`

- [ ] **Step 1: Add failing tests**

Use an in-memory fake runner (a module-level dataclass, since `conftest.FakeCommandRunner` does not write `stdout_path`). Cover:
- Happy path returns the narrative read from the temp `stdout_path` file, records `["opencode", "run", "<prompt>", "--title", ..., "--file", ..., "--print-logs"]`.
- `--model` is appended when configured.
- Non-zero return code → `OpenCodeRunError`.
- File not written / empty → `OpenCodeRunError`.
- Transcript file is written to the temp dir (assert a `exists` marker via an openable temp dir injected through `tmp_path` instead of `TemporaryDirectory`), and contains the prompt body.

For testability, `OpenCodeRunner.run` should accept an optional `workdir: Path | None` defaulting to `tempfile.mkdtemp()` semantics — callers and tests pass `tmp_path`. Simplest: `runner = OpenCodeRunner(runner=..., executable="opencode", model="", timeout_seconds=30.0, workdir=...)`.

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/unit/summarizers/test_opencode_run.py -v
```

Expect `ModuleNotFoundError`.

- [ ] **Step 3: Implement `build_summary_prompt`**

Adapt the prompt from `/Users/chuntsai/Downloads/opencode-weekly-review-git-grouped (1)` (`SUMMARY_PROMPT`), replacing `__DAYS__`, and add one rule: "Base every claim only on the attached transcript; do not invent projects, work, or verification that is not present."

- [ ] **Step 4: Implement `OpenCodeRunner`**

```python
def run(self, *, transcript: str, prompt: str, title: str) -> str:
    workdir = Path(self._workdir or tempfile.mkdtemp())
    transcript_path = workdir / "transcript.md"
    transcript_path.write_text(transcript, encoding="utf-8")
    output_path = workdir / "summary.md"
    args = [
        self._command, "run", prompt,
        "--title", title,
        "--file", str(transcript_path),
        "--print-logs",
    ]
    if self._model:
        args += ["--model", self._model]
    result = self._runner.run(args, stdout_path=output_path)
    if result.returncode != 0:
        raise OpenCodeRunError(result.stderr.strip() or "opencode run failed")
    if not output_path.exists() or not output_path.read_text(encoding="utf-8").strip():
        raise OpenCodeRunError("opencode run produced no output")
    return output_path.read_text(encoding="utf-8").strip()
```

Keep the prompt as a single positional message element.

- [ ] **Step 5: Verify pass**

```bash
uv run pytest tests/unit/summarizers/test_opencode_run.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/agent_worklog/summarizers/opencode_run.py tests/unit/summarizers/test_opencode_run.py
git commit -m "feat: add local opencode run driver"
```

---

### Task 3: Narrative field, renderer wrapper, and config additions

**Files:**
- Modify: `src/agent_worklog/models/report.py`
- Modify: `src/agent_worklog/renderers/markdown.py`
- Modify: `src/agent_worklog/config.py`
- Modify: `tests/unit/renderers/test_markdown.py` (if present; else add)
- Modify: `tests/unit/test_config.py`
- Modify: `tests/unit/test_version.py`

**Interfaces:**
- Produces: `WorklogReport.narrative_text: str | None = None`
- Produces: `render_narrative(report: WorklogReport, *, timezone: str) -> str`
- Produces: `OpenCodeCliSettings.run_timeout_seconds: float = 600.0` and `.model: str = ""`

- [ ] **Step 1: Add failing renderer version**

Add tests asserting `render_narrative` wraps the text under  `# Engineering Worklog` header, includes period/generated/timezone, includes `## Usage` when `usage_text` present, includes `## Warnings` when warnings present, and that `narrative_text` is emitted verbatim; and that a `ReportOutputError`-style trailing newline is normalized to a single newline.

- [ ] **Step 2: Add failing config test**

```python
def test_opencode_run_timeout_and_model_defaults(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__RUN_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__MODEL", raising=False)
    s = AppSettings().harnesses.opencode.cli
    assert s.run_timeout_seconds == 600.0
    assert s.model == ""
```

- [ ] **Step 3: Verify failure**

```bash
uv run pytest tests/unit/renderers tests/unit/test_config.py -v
```

- [ ] **Step 4: Implement**

Add `narrative_text` to `WorklogReport` (default `None`). Add `render_narrative(report, *, timezone) -> str` to `markdown.py`. Copy the header rendering (generated/period/timezone) from the `worklog.md.j2` template by importing it into an HTML-free manual string; keep a single trailing newline. Add the two fields to `OpenCodeCliSettings`.

- [ ] **Step 5: Verify pass + fast

```bash
uv run pytest tests/unit/renderers tests/unit/test_config.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/agent_worklog/models/report.py src/agent_worklog/renderers/markdown.py src/agent_worklog/config.py tests/unit/renderers tests/unit/test_config.py tests/unit/test_version.py
git commit -m "feat: add report narrative field, renderer, and opencode run settings"
```

---

### Task 4: Narrative branch in `ReportService` with structured fallback

This is the core orchestration change. Default `narrative=False` keeps every existing `ReportService` consumer green; the CLI flips it in Task 5.

**Files:**
- Modify: `src/agent_worklog/services/report.py`
- Modify: `tests/integration/test_report_service.py`

**Interfaces:**
- Changes: `ReportService(..., narrative: bool = False, opencode_runner: OpenCodeRunner | None = None, include_subagents: bool = False, sanitized: bool = False)`
- Refactor: extract `_collect_usage` and `_structured_report` helpers; add `_narrative_report`.

- [ ] **Step 1: Add failing narrative tests**

In `tests/integration/test_report_service.py`:
- Default `narrative=False` still yields the structured report (existing tests already cover; keep passing).
- `narrative=True` with an `OpenCodeRunner` wrapping a fake that returns `"NARRATIVE BODY"` yields `result.report.narrative_text == "NARRATIVE BODY"`, `result.report.repositories == []`, and `result.content` contains `# Engineering Report` and `NARRATIVE BODY`.
- `narrative=True` with an `OpenCodeRunner` that raises `OpenCodeRunError` yields a structured report plus a warning containing `open` / `fallback`.
- `usage_provider` still emits `## Usage` inside the narrative content.

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/integration/test_report_service.py -v
```

- [ ] **Step 3: Refactor `generate`**

Split the current body into:

```python
def _collect_usage(self, scan, warnings) -> str | None: ...
def _structured_report(self, scan, warnings, usage_text) -> WorklogReport: ...
def _narrative_report(self, scan, warnings, usage_text) -> WorklogReport: ...
```

`generate()`:

```python
scan = self._scan_service.scan()
warnings = [*self._initial_warnings, *scan.warnings]
usage_text = self._collect_usage(scan, warnings)
if self._narrative:
    try:
        report = self._narrative_report(scan, warnings, usage_text)
    except OpenCodeRunError as exc:
        warnings.append(f"opencode run unavailable; used structured fallback ({exc})")
        report = self._structured_report(scan, warnings, usage_text)
    content = redact_text(render_narrative(report, timezone=_timezone(report)))
else:
    report = self._structured_report(scan, warnings, usage_text)
    content = redact_text(self._renderer.render(report, detail=self._detail))
# unchanged write + result
```

`_narrative_report` builds `transcript = build_grouped_transcript(...)` from `scan.sessions_by_repository` (passing `include_subagents=self._include_subagents`, `sanitized=self._sanitized`), computes `days` from `self._usage_days or (period.until - period.since).days`, calls `self._opencode_runner.run(transcript=..., prompt=build_summary_prompt(days), title=-period-...)`, and returns a `WorklogReport` with `repositories=[]`, `narrative_text=...`, `usage_text`, `usage_days`, `warnings=[redact_text(w) for w in warnings]`. If `self._opencode_runner is None` in narrative mode, raise `OpenCodeRunError("no local opencode run driver configured")`.

`_structured_report` carries the existing evidence/summarizer/`repositories` code and the `SUMMARIZING_REPOSITORIES` progress. Keep redaction identical.

- [ ] **Step 4: Verify pass**

```bash
uv run pytest tests/integration/test_report_service.py tests/unit -v
```

- [ ] **Step 5: Commit**

```bash
git add src/agent_worklog/services/report.py tests/integration/test_report_service.py
git commit -m "feat: narrative report with structured fallback"
```

---

### Task 5: CLI rewrite — narrative default, remove remote auth, add run settings

This is where behavior flips for the real CLI and the OpenAI-compatible summarizer + `llm` config are removed.

**Files:**
- Modify: `src/agent_worklog/cli.py`
- Modify: `src/agent_worklog/config.py`
- Modify: `tests/unit/test_cli.py`
- Modify: `tests/unit/test_opencode_privacy_defaults.py`
- Modify: `tests/integration/test_cli.py`
- Modify: `tests/integration/test_opencode_privacy_modes.py`

**Interfaces:**
- Changes / removals (all in `cli.py`):
  - Remove `--allow-remote-llm` option from `report`.
  - Repurpose `--no-llm` help to "Skip LLM narrative generation; emit the structured report."
  - Remove `_remote_llm_selection`, the `OpenAICompatibleSummarizer` import, and all `settings.llm` reads.
  - `_validate_privacy_options` no longer takes `allow_remote_llm` and drops the mutual-exclusion branch.
  - `_build_report_service` drops `allow_remote_llm`; always passes `summarizer=RuleBasedSummarizer()`; constructs an `OpenCodeRunner` from `settings.harnesses.opencode.cli`; passes `narrative=not no_llm`, `include_subagents=not root_only`, `sanitized=sanitize`.
  - `report` body collapses the four sanitize/remote branches into one `_build_report_service` call with `sanitize=effective_sanitize`.
  - `report` No-Sessions check: `if not result.report.repositories and not result.report.narrative_text:`.
- Changes in `config.py`: delete `LlmSettings` and the `llm` field (additions from Task 3 stay).
- Removals in `tests/unit/test_opencode_privacy_defaults.py`: `test_no_llm_conflicts_with_remote_authorization`, `test_remote_llm_requires_explicit_authorization`, `test_remote_llm_reports_unavailable_configuration`, and any `settings.llm` use.
- Removals in `tests/integration/test_cli.py`: `test_no_llm_never_constructs_http_summarizer` (replaced by `test_no_llm_builds_a_deterministic_service`).
- Rewrites in `tests/integration/test_opencode_privacy_modes.py`: drop `test_api_key_alone_does_not_enable_remote_llm`; keep `test_sanitized_mode_uses_flag_and_db_metadata` (already passes `--no-llm`); add a test asserting narrative by reading `OpenCodeRunner` command from `cli` and that `--no-llm` avoids any `opencode run` call.

- [ ] **Step 1: Add failing unit tests**

In `test_cli.py`:

```python
def test_no_llm_builds_a_deterministic_report_service(tmp_path) -> None:
    # the old http-summarizer guarantee, now expressed as "no opencode run driver in dry-run --no-llm"
```
Capture `narrative` passed to `ReportService`; assert `narrative is False` when `no_llm=True` and `narrative is True` by default.

- [ ] **Step 2: Add failing privacy-defaults unit test**

Replace the removed tests with a check that `_remote_llm_selection` no longer resolves remotely: assert `"openai" not in cli.__dict__` module and that `report --no-llm` returns the structured output (integration).

- [ ] **Step 3: Verify failure**

```bash
uv run pytest tests/unit/test_cli.py tests/unit/test_opencode_privacy_defaults.py -v
```

- [ ] **Step 4: Rewire `cli.py`**

Make the removals and additions above. Ensure `_build_report_service` signature still accepts `no_llm` positionally (so the dozens of monkeypatched stubs in `test_cli.py` with `(settings, period, output_path, no_llm, root_only, *, now, harness, progress, detail)` keep resolving).

- [ ] **Step 5: Update integration tests**

Rework `tests/integration/test_cli.py` and `tests/integration/test_opencode_privacy_modes.py` per the removals above, plus add a narrative-path integration test where `CommandRunner` is monkeypatched and `opencode run` writes `NARRATIVE` to `stdout_path`.

- [ ] **Step 6: Verify pass**

```bash
uv run pytest tests/unit/test_cli.py tests/unit/test_opencode_privacy_defaults.py tests/integration/test_cli.py tests/integration/test_opencode_privacy_modes.py -v
```

- [ ] **Step 7: Commit**

```bash
git add src/agent_worklog/cli.py src/agent_worklog/config.py tests/unit/test_cli.py tests/unit/test_opencode_privacy_defaults.py tests/integration/test_cli.py tests/integration/test_opencode_privacy_modes.py
git commit -m "feat: switch report to local opencode run, drop remote LLM"
```

---

### Task 6: Delete the OpenAI-compatible engine and its dependency

**Files:**
- Delete: `src/agent_worklog/summarizers/openai_compatible.py`
- Delete: `tests/unit/summarizers/test_openai_compatible.py`
- Modify: `pyproject.toml` (remove `httpx`), `uv.lock`
- Modify: `docs`, `README.md`, `README.zh-TW.md`, `CHANGELOG.md`, `tests/unit/test_documentation.py`, `pyproject.toml` version → `0.7.0`

**Interfaces:**
- Produces: package version `0.7.0`; `httpx` no longer a runtime dependency.

- [ ] **Step 1: Add failing documentation tests**

In `tests/unit/test_documentation.py` add a test that `README.md` and `README.zh-TW.md` document `--no-llm`, `opencode run` engine wording, and do not mention `--allow-remote-llm`.

- [ ] **Step 2: Delete module and tests**

`git rm src/agent_worklog/summarizers/openai_compatible.py tests/unit/summarizers/test_openai_compatible.py`.

- [ ] **Step 3: Update docs and release**

Remove `httpx` from `pyproject.toml`; run `uv lock`. Bump `version = "0.7.0"`. Add `CHANGELOG.md` entry:

```markdown
- Reports are now generated by the local `opencode run` engine by default.
- `--no-llm` emits the structured deterministic report without invoking LLMs.
- Removed `--allow-remote-llm` and the OpenAI-compatible remote summarizer.
```

Update READMEs, `docs/configuration.md` (document `AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__RUN_TIMEOUT_SECONDS` and `...__MODEL`), `docs/guides.md`, `docs/privacy.md`, `docs/limitations.md`, dropping all OpenAI/`--allow-remote-llm` references.

- [ ] **Step 4: Verify**

```bash
uv run pytest tests/unit/test_documentation.py tests/unit/test_version.py -v
uv run ruff check src tests
uv run pyright src
uv run pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock README.md README.zh-TW.md docs CHANGELOG.md tests/unit/test_documentation.py tests/unit/test_version.py
git commit -m "release: v0.7.0 local opencode report engine"
```

---

### Task 7: End-to-end verification of both modes

**Files:**
- Modify: `tests/integration/test_end_to_end.py` (or add a new `tests/integration/test_opencode_run_end_to_end.py`)
- Modify: `tests/conftest.py` (`AcceptanceCommandRunner` gains `opencode run` handling writing to `stdout_path`)

**Interfaces:**
- Consumes: `AcceptanceCommandRunner` extended to answer `opencode run` by writing a stub narrative to `stdout_path`.
- Produces: proof that default `report` invokes `opencode run` locally and `--no-llm` does not.

- [ ] **Step 1: Extend `AcceptanceCommandRunner.run`**

```python
if args[:2] == ["opencode", "run"]:
    return CommandResult(0, "", "")
```
plus write the narrative body to `stdout_path` (the fake is responsible for honoring `stdout_path`, mirroring real `opencode run`).

- [ ] **Step 2: Add narrative end-to-end test**

Invoke `report --days 7 --dry-run`; assert exit 0, no `[redacted:`, and that a narrative marker appears in `result.content`.

- [ ] **Step 3: Add `--no-llm` end-to-end test**

Invoke `report --days 10 --no-llm --dry-run`; assert the structured summary shows and that no `opencode run` call was made.

- [ ] **Step 4: Verify**

```bash
uv run pytest tests/integration -v
uv run ruff check src tests
uv run pyright src
uv run pytest
```

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/integration
git commit -m "test: prove narrative and --no-llm end to end"
```

---

## Final Review Checklist

- [ ] `report` default invokes local `opencode run` and returns a narrative.
- [ ] `--no-llm` returns the structured report and never calls `opencode run`.
- [ ] `--allow-remote-llm` and OpenAI remote summarizer are gone (no references in `src`/`tests`).
- [ ] Fallback: an `opencode run` failure produces the structured report plus an explicit warning.
- [ ] Every secret path still passes `redact_text` (transcript, usage, narrative, warnings).
- [ ] `WorklogReport.repositories` are empty in narrative mode; CLI No-sessions check handles empty repositories/narrative_text.
- [ ] `httpx` removed; version reads `0.7.0`.
- [ ] READMEs and docs match CLI behavior; no stale `--allow-remote-llm`/OpenAI text.
- [ ] Ruff, Pyright, and the complete pytest suite pass.