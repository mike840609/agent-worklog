# Narrative Report Parity for Codex and Claude Code Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove and document that `agent-worklog report --harness codex` and `--harness claude-code` produce the same local `opencode run` narrative — preserving full session context — that OpenCode already gets by default.

**Architecture:** The narrative engine is already harness-agnostic. `cli._build_report_service` sets `narrative=not no_llm` and passes an `OpenCodeRunner` for **every** harness (no harness branch), and all three mappers emit full-text `USER_MESSAGE`/`ASSISTANT_MESSAGE` activities that `build_grouped_transcript` consumes. So the runtime behavior is already identical; what is missing is a *guarantee*. The Codex and Claude end-to-end tests hardcode `--no-llm`, so only OpenCode has a test that exercises the narrative path. This plan adds narrative end-to-end coverage for Codex and Claude (locking the shared behavior in against future regressions) and fixes README copy that implies narrative is OpenCode-only.

**Tech Stack:** Python 3.11+, Typer CLI, pytest (via `uv`), `typer.testing.CliRunner`.

## Context: why this is test + docs only

Investigation of the v0.7.0 report engine found **no runtime gap**:

- `src/agent_worklog/cli.py:299-300` — `narrative=not no_llm` and `opencode_runner=...` are set for all harnesses; there is no `if harness is OPENCODE` gate.
- `src/agent_worklog/harnesses/codex/mapper.py:318-330` and `src/agent_worklog/harnesses/claude_code/mapper.py:219-226,299-310` — both emit `USER_MESSAGE`/`ASSISTANT_MESSAGE` activities with the **full** message text (`content=message` / `content=text`), no truncation.
- `src/agent_worklog/summarizers/transcript.py:81-91` — the transcript builder consumes exactly those two activity types for every harness.
- `src/agent_worklog/cli.py:236-239` — usage is supplied for Codex/Claude too (`render_activity_usage`), rendered in narrative mode.

The gaps are:

1. **Coverage.** `tests/integration/test_codex_end_to_end.py:32` and `tests/integration/test_claude_code_end_to_end.py:38` always pass `--no-llm`. Only `tests/integration/test_end_to_end.py:61` (`test_end_to_end_narrative_report_uses_local_opencode_run`) proves the narrative path, and only for OpenCode. A future change that gated narrative to OpenCode would pass CI.
2. **Root cause the tests can't reach it.** The `git_only_runner` fixture (`tests/conftest.py:208-229`) used by the Codex/Claude tests does not answer `opencode run`; only `mocked_opencode` (`tests/conftest.py:164-172`) does. Without a runner that serves `opencode run`, those tests cannot exercise the narrative path, which is why they use `--no-llm`.
3. **Docs.** `README.md:105-114` (and `README.zh-TW.md:100-108`) show Codex/Claude only with `--no-llm`, implying the narrative default is OpenCode-only.

## Global Constraints

- `requires-python = ">=3.11"`; ruff `target-version = "py311"`, `line-length = 100`, lint rules `E, F, I, UP, B, SIM` (from `pyproject.toml`).
- pyright `typeCheckingMode = "standard"`, `include = ["src"]` — test files are not type-checked, but keep them clean.
- Run tests with `uv run --extra dev python -m pytest` (pytest is a dev extra, not on `PATH`). Test config: `addopts = "-ra --import-mode=importlib"`, `testpaths = ["tests"]`.
- **No new dependencies** and **no `src/` changes** — this is test + documentation only. If a task appears to need a `src/` change, stop: it means a real behavior gap was found and the plan's premise must be revisited.
- The narrative marker string `NARRATIVE_ACCEPTANCE_MARKER` is already used by `AcceptanceCommandRunner`; reuse it verbatim for consistency.

## File Structure

- `tests/conftest.py` — extend `GitOnlyCommandRunner` so it answers `opencode run` (records the call, captures the transcript handed to it, writes a narrative marker to `stdout_path`). Shared by both harness tests.
- `tests/integration/test_codex_end_to_end.py` — add a `narrative` switch to `_invoke` and one narrative test.
- `tests/integration/test_claude_code_end_to_end.py` — same shape as the Codex test.
- `README.md`, `README.zh-TW.md` — clarify that the narrative default applies to every harness; `--no-llm` is what removes the OpenCode dependency.

---

### Task 1: Codex narrative end-to-end coverage (+ make `GitOnlyCommandRunner` serve `opencode run`)

**Files:**
- Modify: `tests/conftest.py:208-229` (`GitOnlyCommandRunner`)
- Modify: `tests/integration/test_codex_end_to_end.py:12-34` (`_invoke` helper)
- Test: `tests/integration/test_codex_end_to_end.py` (new test function)

**Interfaces:**
- Consumes: `OpenCodeRunner.run` invokes the injected runner as
  `runner.run([executable, "run", prompt, "--title", title, "--file", <transcript_path>, "--print-logs", ...], stdout_path=<output_path>)` and reads the narrative back from `stdout_path` (see `src/agent_worklog/summarizers/opencode_run.py:158-178`). The fake must therefore write **non-empty** text to `stdout_path` and return `returncode == 0`, or `OpenCodeRunError` triggers the structured fallback.
- Produces: `GitOnlyCommandRunner` gains `run_calls: list[list[str]]`, `run_transcripts: list[str]`, and `narrative_marker: str = "NARRATIVE_ACCEPTANCE_MARKER"`. Task 2 relies on these.

- [ ] **Step 1: Write the failing Codex narrative test**

Add a `narrative` switch to `_invoke` and a new test in `tests/integration/test_codex_end_to_end.py`. Change the helper signature/body:

```python
def _invoke(
    monkeypatch,
    codex_home: Path,
    git_only_runner,
    output: Path | None = None,
    *extra: str,
    subcommand: str = "report",
    narrative: bool = False,
):
    monkeypatch.setattr(
        cli,
        "_now_in_timezone",
        lambda timezone: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )
    monkeypatch.setattr(cli, "CommandRunner", lambda timeout_seconds: git_only_runner)
    monkeypatch.setenv(
        "AGENT_WORKLOG_HARNESSES__CODEX__HOME_DIRECTORY", str(codex_home)
    )
    args = [subcommand, "--harness", "codex", "--period", "last-week"]
    if subcommand == "report":
        assert output is not None
        if not narrative:
            args.append("--no-llm")
        args += ["--output", str(output)]
    args.extend(extra)
    return CliRunner().invoke(cli.app, args)
```

Add the test:

```python
def test_codex_report_narrative_uses_local_opencode_run(
    tmp_path: Path, monkeypatch, codex_home: Path, git_only_runner
) -> None:
    output = tmp_path / "worklog.md"

    result = _invoke(monkeypatch, codex_home, git_only_runner, output, narrative=True)

    assert result.exit_code == 0, result.stdout
    content = output.read_text(encoding="utf-8")
    # The narrative body came from opencode run, wrapped under the report header.
    assert "# Engineering Worklog" in content
    assert "NARRATIVE_ACCEPTANCE_MARKER" in content
    # opencode run was actually invoked (not the structured fallback).
    assert git_only_runner.run_calls, "opencode run was never invoked"
    # Full session context reached opencode run via the grouped transcript.
    transcript = git_only_runner.run_transcripts[0]
    assert "## Project:" in transcript
    assert "Add retry to the price fetcher" in transcript
    assert "I implemented the retry." in transcript
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run --extra dev python -m pytest tests/integration/test_codex_end_to_end.py::test_codex_report_narrative_uses_local_opencode_run -v`
Expected: FAIL — `git_only_runner` returns `CommandResult(1, ...)` for `opencode run`, so the narrative falls back to the structured report; `NARRATIVE_ACCEPTANCE_MARKER` is absent and `run_calls` does not exist yet (`AttributeError`).

- [ ] **Step 3: Teach `GitOnlyCommandRunner` to answer `opencode run`**

In `tests/conftest.py`, replace the `GitOnlyCommandRunner` dataclass with:

```python
@dataclass
class GitOnlyCommandRunner:
    """Answer git queries for the Claude Code and Codex acceptance runs, and fake
    `opencode run` so the narrative path can be exercised without OpenCode installed.
    """

    remotes: dict[str, str] = field(default_factory=dict)
    narrative_marker: str = "NARRATIVE_ACCEPTANCE_MARKER"
    run_calls: list[list[str]] = field(default_factory=list)
    run_transcripts: list[str] = field(default_factory=list)

    def run(self, args: list[str], *, stdout_path: Path | None = None) -> CommandResult:
        if args[:2] == ["opencode", "run"]:
            self.run_calls.append(args)
            transcript_path = Path(args[args.index("--file") + 1])
            self.run_transcripts.append(transcript_path.read_text(encoding="utf-8"))
            if stdout_path is not None:
                stdout_path.write_text(
                    f"# Weekly Engineering Review\n\n{self.narrative_marker}\n",
                    encoding="utf-8",
                )
            return CommandResult(0, "", "")
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
```

(`Path` and `CommandResult` are already imported at the top of `conftest.py`.)

- [ ] **Step 4: Run the Codex narrative test and confirm it passes**

Run: `uv run --extra dev python -m pytest tests/integration/test_codex_end_to_end.py -v`
Expected: PASS — the new narrative test and all existing `--no-llm` Codex tests are green (the existing tests never invoke `opencode run`, so the new branch does not affect them).

- [ ] **Step 5: Run the full suite to confirm nothing regressed**

Run: `uv run --extra dev python -m pytest -q`
Expected: PASS — 354 passed (353 baseline + 1 new).

- [ ] **Step 6: Lint the changed test files**

Run: `uv run --extra dev ruff check tests/conftest.py tests/integration/test_codex_end_to_end.py`
Expected: no findings.

- [ ] **Step 7: Commit**

```bash
git add tests/conftest.py tests/integration/test_codex_end_to_end.py
git commit -m "test: prove the Codex narrative uses local opencode run"
```

---

### Task 2: Claude Code narrative end-to-end coverage

**Files:**
- Modify: `tests/integration/test_claude_code_end_to_end.py:12-42` (`_invoke` helper)
- Test: `tests/integration/test_claude_code_end_to_end.py` (new test function)

**Interfaces:**
- Consumes: the `GitOnlyCommandRunner.run_calls` / `run_transcripts` / `opencode run` support added in Task 1.
- Produces: nothing new; this task only adds coverage.

- [ ] **Step 1: Write the failing Claude narrative test**

Add a `narrative` switch to `_invoke` and a new test in `tests/integration/test_claude_code_end_to_end.py`. Change the helper:

```python
def _invoke(
    monkeypatch,
    claude_code_projects: Path,
    git_only_runner,
    output: Path,
    *extra_args: str,
    narrative: bool = False,
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
    args = ["report", "--harness", "claude-code", "--period", "last-week"]
    if not narrative:
        args.append("--no-llm")
    args += ["--output", str(output), *extra_args]
    return CliRunner().invoke(cli.app, args)
```

Add the test:

```python
def test_claude_code_report_narrative_uses_local_opencode_run(
    tmp_path: Path,
    monkeypatch,
    claude_code_projects: Path,
    git_only_runner,
) -> None:
    output = tmp_path / "worklog.md"

    result = _invoke(
        monkeypatch, claude_code_projects, git_only_runner, output, narrative=True
    )

    assert result.exit_code == 0, result.stdout
    content = output.read_text(encoding="utf-8")
    assert "# Engineering Worklog" in content
    assert "NARRATIVE_ACCEPTANCE_MARKER" in content
    assert git_only_runner.run_calls, "opencode run was never invoked"
    transcript = git_only_runner.run_transcripts[0]
    assert "## Project:" in transcript
    assert "Add retry to the price fetcher" in transcript
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run --extra dev python -m pytest tests/integration/test_claude_code_end_to_end.py::test_claude_code_report_narrative_uses_local_opencode_run -v`
Expected: FAIL — before the helper edit lands, `_invoke(...)` rejects `narrative=True` (`TypeError: unexpected keyword argument`); once the helper accepts it, the test passes because Task 1 already taught the runner `opencode run`. If you write the helper change and the test together, run this step after and confirm PASS instead (there is no `src/` change to make here).

- [ ] **Step 3: Run the Claude suite and confirm it passes**

Run: `uv run --extra dev python -m pytest tests/integration/test_claude_code_end_to_end.py -v`
Expected: PASS — the new narrative test plus the existing `--no-llm` Claude tests.

- [ ] **Step 4: Run the full suite**

Run: `uv run --extra dev python -m pytest -q`
Expected: PASS — 355 passed (354 + 1 new).

- [ ] **Step 5: Lint the changed file**

Run: `uv run --extra dev ruff check tests/integration/test_claude_code_end_to_end.py`
Expected: no findings.

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_claude_code_end_to_end.py
git commit -m "test: prove the Claude Code narrative uses local opencode run"
```

---

### Task 3: Document that the narrative default applies to every harness

**Files:**
- Modify: `README.md:105-114`
- Modify: `README.zh-TW.md:100-108`
- Test: `tests/unit/test_documentation.py` (existing assertions must stay green — no new test needed; `test_readmes_document_privacy_controls` requires `--no-llm` to remain present in both READMEs, and it does)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing — documentation only.

- [ ] **Step 1: Clarify the English README**

In `README.md`, replace lines 105-114:

```markdown
Those three commands default to `--harness opencode`. For Claude Code or Codex, add
`--harness claude-code` or `--harness codex` to each — no OpenCode installation is
needed (the structured `--no-llm` report works for every harness):

```bash
agent-worklog doctor --harness claude-code
agent-worklog report --harness claude-code --period last-week --no-llm
agent-worklog doctor --harness codex
agent-worklog report --harness codex --period last-week --no-llm
```
```

with:

```markdown
Those three commands default to `--harness opencode`. For Claude Code or Codex, add
`--harness claude-code` or `--harness codex` to each. The narrative default behaves
the same for every harness: it reads that harness's sessions and still calls your
local `opencode run` to write the review. Add `--no-llm` when OpenCode is not
installed — the deterministic structured report works for every harness without it:

```bash
agent-worklog doctor --harness claude-code
agent-worklog report --harness claude-code --period last-week
agent-worklog report --harness claude-code --period last-week --no-llm
agent-worklog doctor --harness codex
agent-worklog report --harness codex --period last-week
agent-worklog report --harness codex --period last-week --no-llm
```
```

- [ ] **Step 2: Mirror the change in the Traditional Chinese README**

In `README.zh-TW.md`, replace lines 100-108:

```markdown
上面三個指令預設都是 `--harness opencode`。要用 Claude Code 或 Codex 的話，各自加上
`--harness claude-code` 或 `--harness codex` 即可，不需要安裝 OpenCode
（結構化的 `--no-llm` 報告對所有 harness 都可用）：

```bash
agent-worklog doctor --harness claude-code
agent-worklog report --harness claude-code --period last-week --no-llm
agent-worklog doctor --harness codex
agent-worklog report --harness codex --period last-week --no-llm
```
```

with:

```markdown
上面三個指令預設都是 `--harness opencode`。要用 Claude Code 或 Codex 的話，各自加上
`--harness claude-code` 或 `--harness codex` 即可。敘事式預設對所有 harness 一致：
它會讀取該 harness 的工作階段，並同樣呼叫本機的 `opencode run` 來撰寫週報。若未安裝
OpenCode，加上 `--no-llm`；決定性的結構化報告對所有 harness 都可用，且不需要 OpenCode：

```bash
agent-worklog doctor --harness claude-code
agent-worklog report --harness claude-code --period last-week
agent-worklog report --harness claude-code --period last-week --no-llm
agent-worklog doctor --harness codex
agent-worklog report --harness codex --period last-week
agent-worklog report --harness codex --period last-week --no-llm
```
```

- [ ] **Step 3: Run the documentation tests**

Run: `uv run --extra dev python -m pytest tests/unit/test_documentation.py -v`
Expected: PASS — `--no-llm`, `--harness`, `claude-code`, and `opencode run` all remain present in both READMEs.

- [ ] **Step 4: Commit**

```bash
git add README.md README.zh-TW.md
git commit -m "docs: note the narrative default works for every harness"
```

---

## Self-Review

**1. Spec coverage.** The request was "ensure Codex and Claude have the same behavior as the updated OpenCode narrative worklog; if not, plan the fix." Finding: runtime is already identical, so the "fix" is to *lock in and document* the parity. Task 1 proves the Codex narrative path end to end; Task 2 proves the Claude path; Task 3 removes the doc claim that implies narrative is OpenCode-only. "Preserve full context" (保留完整 context) is asserted directly: both narrative tests check the session's user prompt and assistant reply reached the transcript handed to `opencode run`.

**2. Placeholder scan.** No `TBD`/`later`/"add error handling"/"write tests for the above". Every code block is complete and runnable. The one conditional instruction (Task 2 Step 2 red vs. green depending on edit order) is spelled out, not hand-waved.

**3. Type/name consistency.** `run_calls`, `run_transcripts`, and `narrative_marker` are introduced in Task 1 and consumed by name in both tests. `NARRATIVE_ACCEPTANCE_MARKER` matches the string `AcceptanceCommandRunner` already writes. The `OpenCodeRunner` invocation shape (`--file`, `stdout_path=`) matches `src/agent_worklog/summarizers/opencode_run.py`. `# Engineering Worklog` matches the header `render_narrative` emits (asserted the same way in `tests/integration/test_report_service.py:396`). Expected test counts (354, 355) follow from the 353 green baseline.
