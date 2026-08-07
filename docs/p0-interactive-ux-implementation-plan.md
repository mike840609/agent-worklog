# P0 Interactive UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bare-command numbered questionnaire with a lightweight key-driven terminal interaction that supports report setup, repository/session selection, recoverable results, and returning to the main menu without changing direct CLI behavior.

**Architecture:** Keep Typer as the command dispatcher and existing `ScanService`/`ReportService` as the business-logic boundary. Add a focused `agent_worklog.interactive` package for terminal input, short-lived draft state, selection/filtering, Rich rendering, and controller transitions; `cli.py` supplies reusable service-builder callbacks and invokes the controller only for bare `agent-worklog`.

**Tech Stack:** Python 3.11+, Typer 0.16+, Rich 14+, stdlib terminal APIs (`termios`/`tty` on POSIX, `msvcrt` on Windows), pytest, Ruff, Pyright.

## Global Constraints

- No Textual, curses, or new runtime dependency.
- Direct `scan`, `report`, `doctor`, `config`, `run`, and `--help` behavior must remain backward-compatible.
- Bare `agent-worklog` still requires a TTY and must fail clearly in pipelines/non-TTY environments.
- Interactive session selection is ephemeral and applies only to the current report run.
- Scan cache identity is exactly `(harness, period, include_subagents, sanitize)`.
- Changing `detail`, `narrative`, or `dry_run` must not invalidate a compatible cached scan.
- Repository checkbox state is derived from child-session selection; never store an independent repository selection boolean.
- Expected interactive errors are recoverable UI states; direct CLI exit-code contracts remain unchanged.
- Terminal input/cursor state must be restored after normal exit, exceptions, and Ctrl-C.
- `Browse Sessions` remains read-only in P0.
- Interactive reports use the normal default output path; if it already exists, generation must require an explicit one-time overwrite action.
- Do not add `/` filter, session inspection, report history, mouse support, persisted UI preferences, JSON changes, platform-specific report opening, update shortcuts, or animation.
- Do not add or commit a `docs/superpowers/` directory; project planning/design documents live directly under `docs/`.

---

## File Structure

Create:

- `src/agent_worklog/interactive/__init__.py` — public interactive entrypoint exports only.
- `src/agent_worklog/interactive/input.py` — normalized key model and safe platform terminal reader.
- `src/agent_worklog/interactive/models.py` — screen enum, menu cursor state, and `ReportDraft` cache invalidation rules.
- `src/agent_worklog/interactive/selection.py` — repository/session selection and filtered `ScanResult` construction.
- `src/agent_worklog/interactive/render.py` — Rich renderers for main menu, setup, session browser/review, result, and recoverable error views.
- `src/agent_worklog/interactive/controller.py` — interaction state machine and service callbacks.
- `tests/unit/interactive/test_input.py` — key normalization and terminal restoration tests.
- `tests/unit/interactive/test_models.py` — report draft invalidation tests.
- `tests/unit/interactive/test_selection.py` — group/individual selection and filtering tests.
- `tests/unit/interactive/test_render.py` — semantic renderer tests.
- `tests/unit/interactive/test_controller.py` — state transitions, recovery, and generation orchestration.

Modify:

- `src/agent_worklog/cli.py` — expose thin interactive callbacks and replace `_interactive_menu()` with the new controller entrypoint; keep `run` and direct commands intact.
- `tests/integration/test_cli.py` — replace numbered-menu tests with bare-command controller seam tests and preserve non-TTY/direct-command regressions.
- `README.md` — new bare-command interaction example.
- `README.zh-TW.md` — mirrored interaction example.
- `docs/cli-reference.md` — key-driven menu/report review behavior.
- `CHANGELOG.md` — unreleased P0 interaction upgrade entry.
- `tests/unit/test_documentation.py` — pin new documented interaction copy.

---

### Task 1: Terminal Input and Report Draft State

**Files:**
- Create: `src/agent_worklog/interactive/__init__.py`
- Create: `src/agent_worklog/interactive/input.py`
- Create: `src/agent_worklog/interactive/models.py`
- Create: `tests/unit/interactive/test_input.py`
- Create: `tests/unit/interactive/test_models.py`

**Interfaces:**
- Produces `Key` enum with `UP`, `DOWN`, `ENTER`, `SPACE`, `ESCAPE`, `CTRL_C`, plus character values through `KeyPress.char`.
- Produces `KeyPress(key: Key | None, char: str | None)`.
- Produces `TerminalInput.read_key() -> KeyPress` and context-managed terminal setup/restore.
- Produces `Screen` enum and `ReportDraft` with `replace_scan_identity(...)`, `set_scan(...)`, and `clear_scan()` behavior.

- [ ] **Step 1: Write failing key-normalization and restoration tests**

```python
from agent_worklog.interactive.input import Key, KeyPress, normalize_posix_sequence


def test_arrow_and_vim_keys_normalize_to_navigation() -> None:
    assert normalize_posix_sequence("\x1b[A") == KeyPress(Key.UP)
    assert normalize_posix_sequence("\x1b[B") == KeyPress(Key.DOWN)
    assert normalize_posix_sequence("j") == KeyPress(char="j")
    assert normalize_posix_sequence("k") == KeyPress(char="k")


def test_enter_space_and_escape_are_distinct() -> None:
    assert normalize_posix_sequence("\r") == KeyPress(Key.ENTER)
    assert normalize_posix_sequence(" ") == KeyPress(Key.SPACE)
    assert normalize_posix_sequence("\x1b") == KeyPress(Key.ESCAPE)
```

Add a fake terminal adapter test that raises inside the input context and asserts its restore callback executes exactly once.

- [ ] **Step 2: Run the input tests and confirm RED**

Run:

```bash
uv run pytest tests/unit/interactive/test_input.py -v
```

Expected: import failure because `agent_worklog.interactive.input` does not exist.

- [ ] **Step 3: Implement minimal cross-platform input abstraction**

`input.py` must keep platform imports guarded:

```python
class Key(StrEnum):
    UP = "up"
    DOWN = "down"
    ENTER = "enter"
    SPACE = "space"
    ESCAPE = "escape"
    CTRL_C = "ctrl_c"


@dataclass(frozen=True)
class KeyPress:
    key: Key | None = None
    char: str | None = None
```

Normalize `\x1b[A`, `\x1b[B`, CR/LF, space, escape, and Ctrl-C. Use `termios`/`tty` only on POSIX and `msvcrt.getwch()` on Windows. All mode changes must be restored in `finally`.

- [ ] **Step 4: Run input tests and confirm GREEN**

```bash
uv run pytest tests/unit/interactive/test_input.py -v
```

Expected: PASS.

- [ ] **Step 5: Write failing ReportDraft invalidation tests**

```python

def test_detail_change_keeps_cached_scan(draft_with_scan) -> None:
    before = draft_with_scan.scan
    draft_with_scan.detail = DetailLevel.BRIEF
    assert draft_with_scan.scan is before


def test_period_change_invalidates_scan_and_selection(draft_with_scan, other_period) -> None:
    draft_with_scan.set_period(other_period)
    assert draft_with_scan.scan is None
    assert draft_with_scan.selected_session_ids == set()
```

Cover harness, period, include-subagents, and sanitize invalidation; cover detail, narrative, and dry-run preservation.

- [ ] **Step 6: Run draft tests and confirm RED**

```bash
uv run pytest tests/unit/interactive/test_models.py -v
```

Expected: missing `ReportDraft` methods/types.

- [ ] **Step 7: Implement `Screen` and `ReportDraft`**

Use explicit mutators so invalidation cannot be skipped accidentally:

```python
@dataclass
class ReportDraft:
    harness: str
    period: DateRange
    include_subagents: bool = True
    sanitize: bool = False
    detail: DetailLevel = DetailLevel.FULL
    narrative: bool = True
    dry_run: bool = False
    scan: ScanResult | None = None
    selected_session_ids: set[str] = field(default_factory=set)

    def set_period(self, period: DateRange) -> None:
        if period != self.period:
            self.period = period
            self.clear_scan()

    def clear_scan(self) -> None:
        self.scan = None
        self.selected_session_ids.clear()
```

Provide equivalent mutators for the other identity fields; non-identity fields assign without clearing.

- [ ] **Step 8: Run task tests and commit**

```bash
uv run pytest tests/unit/interactive/test_input.py tests/unit/interactive/test_models.py -v
uv run ruff check src/agent_worklog/interactive tests/unit/interactive
uv run pyright src/agent_worklog/interactive

git add src/agent_worklog/interactive tests/unit/interactive/test_input.py tests/unit/interactive/test_models.py
git commit -m "feat(interactive): add terminal input and report draft state"
```

---

### Task 2: Repository and Session Selection

**Files:**
- Create: `src/agent_worklog/interactive/selection.py`
- Create: `tests/unit/interactive/test_selection.py`

**Interfaces:**
- Consumes `ScanResult`, `ResolvedSession`, and `ReportDraft.selected_session_ids`.
- Produces `SelectionState.from_scan(scan)`, `toggle_session(session_id)`, `toggle_repository(repository_id)`, `select_all()`, `select_none()`, `repository_mark(repository_id)`, and `filtered_scan()`.

- [ ] **Step 1: Write failing selection tests with two repositories**

Create real `ScanResult` fixtures with `ResolvedSession` objects. Required assertions:

```python
state = SelectionState.from_scan(scan)
assert state.selected_count == scan.loaded_session_count
assert state.repository_mark("repo-a") == SelectionMark.ALL

state.toggle_session("ses-a1")
assert state.repository_mark("repo-a") == SelectionMark.PARTIAL

state.toggle_repository("repo-a")
assert all(sid in state.selected_session_ids for sid in {"ses-a1", "ses-a2"})
```

Also test a second toggle deselects the full repository and `select_none` / `select_all`.

- [ ] **Step 2: Run selection tests and confirm RED**

```bash
uv run pytest tests/unit/interactive/test_selection.py -v
```

Expected: missing selection module.

- [ ] **Step 3: Implement derived repository marks**

```python
class SelectionMark(StrEnum):
    ALL = "all"
    NONE = "none"
    PARTIAL = "partial"
```

Never persist a repository boolean. Derive the mark from child IDs every time.

- [ ] **Step 4: Implement filtered `ScanResult`**

The filtered object must preserve original period/candidate/failed counts and warnings, but `loaded_session_count`, `resolved_sessions`, and `sessions_by_repository` must reflect the selection:

```python
return ScanResult(
    period=self.scan.period,
    candidate_session_count=self.scan.candidate_session_count,
    loaded_session_count=len(selected),
    failed_session_count=self.scan.failed_session_count,
    resolved_sessions=selected,
    sessions_by_repository=group_resolved_sessions(selected),
    warnings=list(self.scan.warnings),
)
```

- [ ] **Step 5: Add zero-selection and unknown-ID safety tests**

Unknown session/repository IDs must not mutate state silently; raise `KeyError` or a small explicit `SelectionError`. `filtered_scan()` with none selected must return a structurally valid zero-loaded result so the controller can block generation before invoking `ReportService`.

- [ ] **Step 6: Run tests and commit**

```bash
uv run pytest tests/unit/interactive/test_selection.py -v
uv run ruff check src/agent_worklog/interactive/selection.py tests/unit/interactive/test_selection.py
uv run pyright src/agent_worklog/interactive/selection.py

git add src/agent_worklog/interactive/selection.py tests/unit/interactive/test_selection.py
git commit -m "feat(interactive): add repository and session selection"
```

---

### Task 3: Rich Screen Rendering

**Files:**
- Create: `src/agent_worklog/interactive/render.py`
- Create: `tests/unit/interactive/test_render.py`

**Interfaces:**
- Produces pure render functions that accept a `rich.console.Console` and state; they do not read keys or call services.
- Required functions: `render_main_menu`, `render_report_setup`, `render_session_review`, `render_session_browser`, `render_report_result`, `render_recoverable_error`.

- [ ] **Step 1: Write failing semantic renderer tests**

Use `StringIO` + `Console(color_system=None, force_terminal=False, width=100)`. Assert content rather than ANSI layout:

```python
render_main_menu(console, selected=0)
text = stream.getvalue()
assert "Agent Worklog" in text
assert "Generate Report" in text
assert "↑↓ / jk" in text
assert "Enter" in text
assert "q Quit" in text
```

For session review assert selected/total counts, `●`, `○`, `◐`, repository names, expanded session titles, `Space Toggle`, `g Generate`, and `b Back`.

- [ ] **Step 2: Run renderer tests and confirm RED**

```bash
uv run pytest tests/unit/interactive/test_render.py -v
```

- [ ] **Step 3: Implement one shared selectable-list/footer primitive**

Keep screen-specific wording but centralize cursor rendering (`❯`) and footer layout. Do not clear the screen in the renderer; screen clearing/redraw belongs to the controller/terminal wrapper.

- [ ] **Step 4: Implement all six screen renderers**

Setup must show Harness, Period, Detail, Subagents, Narrative, Sanitize, Dry run plus `Review sessions`. Result must show period, repository count, selected session count, and output path (or `Dry run` label when no file was written).

- [ ] **Step 5: Run renderer tests and commit**

```bash
uv run pytest tests/unit/interactive/test_render.py -v
uv run ruff check src/agent_worklog/interactive/render.py tests/unit/interactive/test_render.py
uv run pyright src/agent_worklog/interactive/render.py

git add src/agent_worklog/interactive/render.py tests/unit/interactive/test_render.py
git commit -m "feat(interactive): render terminal-native worklog screens"
```

---

### Task 4: Controller Navigation and Report Setup

**Files:**
- Create: `src/agent_worklog/interactive/controller.py`
- Create: `tests/unit/interactive/test_controller.py`
- Modify: `src/agent_worklog/interactive/__init__.py`

**Interfaces:**
- Controller depends on injected callbacks instead of importing `cli.py`, avoiding a cycle.
- Define an `InteractiveActions` dataclass/protocol with callbacks for settings/default draft creation, scan, doctor, settings walk, report generation, and overwrite confirmation.
- `run_interactive(actions, input, console) -> None` owns navigation until quit.

- [ ] **Step 1: Write failing main-menu transition tests using a scripted key source**

```python
keys = ScriptedInput([char("2"), KeyPress(Key.ESCAPE), char("q")])
run_interactive(actions, keys, console)
assert actions.scan_calls == 1
```

Also test `DOWN`/`j`, `UP`/`k`, `ENTER`, numeric shortcuts, and main-menu `Esc/q` quit.

- [ ] **Step 2: Run controller tests and confirm RED**

```bash
uv run pytest tests/unit/interactive/test_controller.py -v
```

- [ ] **Step 3: Implement the main loop and screen transitions**

Use an explicit state loop, not nested unbounded prompt functions:

```python
while screen is not Screen.EXIT:
    render(screen, state)
    key = input.read_key()
    screen = handle_key(screen, key, state, actions)
```

`KeyboardInterrupt` exits cleanly after the input context restores terminal state.

- [ ] **Step 4: Write failing Report Setup edit/invalidation tests**

Drive these flows:

- Generate Report -> setup defaults without prompts.
- Toggle Detail -> cached scan retained.
- Toggle Narrative -> cached scan retained.
- Toggle Dry run -> cached scan retained.
- Change Harness/Period/Subagents/Sanitize -> cached scan + selected IDs cleared.
- `r` or `Review sessions` triggers scan only when no compatible scan exists.
- `b/Esc` returns Main.

- [ ] **Step 5: Implement setup editing with existing semantics**

Period editor supports exactly the existing modes: previous calendar week, last N days, custom range. Harness choices must be restricted to enabled harnesses. Sanitize appears/editable only for OpenCode; switching away forces it to false as direct CLI already does.

- [ ] **Step 6: Add Browse Sessions read-only tests and implementation**

Browse chooses harness + period, scans, then renders grouped repositories. It supports navigation + expand/collapse + Back/Main only. Space must not toggle selection and no `/` filter exists.

- [ ] **Step 7: Add recoverable scan/zero-session tests**

Have the scan callback raise `HarnessSourceError` and return zero sessions in separate tests. Assert controller remains alive and offers/change routes instead of propagating `typer.Exit`.

- [ ] **Step 8: Run tests and commit**

```bash
uv run pytest tests/unit/interactive/test_controller.py -v
uv run ruff check src/agent_worklog/interactive tests/unit/interactive/test_controller.py
uv run pyright src/agent_worklog/interactive

git add src/agent_worklog/interactive tests/unit/interactive/test_controller.py
git commit -m "feat(interactive): add navigation and report setup controller"
```

---

### Task 5: Session Review, Report Generation, Result, and Overwrite Recovery

**Files:**
- Modify: `src/agent_worklog/interactive/controller.py`
- Modify: `src/agent_worklog/interactive/render.py`
- Modify: `tests/unit/interactive/test_controller.py`
- Modify: `tests/unit/interactive/test_render.py`

**Interfaces:**
- Consumes `SelectionState.filtered_scan()` and injected report generation callback.
- Result action returns an object containing `output_path`, `content`, report metadata, and the scan used.

- [ ] **Step 1: Write failing session-review interaction tests**

Drive repository expand/collapse, repository Space toggle, session Space toggle, `a`, `n`, `b/Esc`, and `q`. Assert `g` with zero selected does not invoke generation.

- [ ] **Step 2: Implement visible-row cursor model**

Visible rows are derived from repository order + expansion set. Cursor indexes only visible rows; collapsing a group must clamp/reset the cursor if its selected child disappears.

- [ ] **Step 3: Write failing generation tests**

Capture the `ScanResult` passed to generation and assert excluded sessions are absent. Verify no second scan callback occurs between review and generation.

- [ ] **Step 4: Implement generation with filtered scan**

On `g`:

1. block zero selection;
2. call `selection.filtered_scan()`;
3. call injected report generation with that exact scan;
4. transition to result on success.

- [ ] **Step 5: Write failing overwrite-recovery test**

Have generation raise `ReportOutputError("report already exists: ...")`. Assert the result/recovery screen offers `Overwrite once`, Back, and Main. Selecting overwrite retries exactly once with `force=True`; ordinary generation uses `force=False`.

- [ ] **Step 6: Implement result actions**

`Back to main menu` clears report-flow navigation state. `Generate another report` preserves harness/period/detail/subagents/narrative/sanitize/dry-run but clears scan + selection and returns setup. `Print report path` emits only the path through the console and remains on the result screen.

- [ ] **Step 7: Add report generation error recovery tests**

Cover `HarnessSourceError`, `ReportOutputError`, and unexpected safe failures exposed by existing report callback contract. Expected errors must be recoverable and must not terminate the interactive application.

- [ ] **Step 8: Run tests and commit**

```bash
uv run pytest tests/unit/interactive/test_controller.py tests/unit/interactive/test_render.py -v
uv run ruff check src/agent_worklog/interactive tests/unit/interactive
uv run pyright src/agent_worklog/interactive

git add src/agent_worklog/interactive tests/unit/interactive
git commit -m "feat(interactive): review selected sessions and generate reports"
```

---

### Task 6: CLI Wiring, Backward Compatibility, Documentation, and Full Verification

**Files:**
- Modify: `src/agent_worklog/cli.py`
- Modify: `tests/integration/test_cli.py`
- Modify: `README.md`
- Modify: `README.zh-TW.md`
- Modify: `docs/cli-reference.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/unit/test_documentation.py`

**Interfaces:**
- `cli.py` builds `InteractiveActions` using existing `_load_settings`, `_build_scan_service`, `_build_report_service`, `_default_output_path`, `run_doctor`, and config helpers.
- Bare callback calls `run_interactive(...)`; named Typer commands remain unchanged.

- [ ] **Step 1: Write failing CLI seam tests before changing `_interactive_menu`**

Replace legacy assertions that feed `"1\n"` into `_prompt` with tests that monkeypatch `run_interactive`:

```python

def test_bare_invocation_enters_interactive_controller(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: True)
    monkeypatch.setattr(cli, "run_interactive", lambda **kwargs: called.append(True))
    result = runner.invoke(cli.app, [])
    assert result.exit_code == 0
    assert called == [True]
```

Keep and adapt tests proving non-TTY bare invocation exits 3 and `--help` / named subcommands never invoke the interactive controller.

- [ ] **Step 2: Run focused integration tests and confirm RED**

```bash
uv run pytest tests/integration/test_cli.py -k "bare_invocation or menu or naming_a_subcommand or help_still" -v
```

- [ ] **Step 3: Add thin callback adapters in `cli.py`**

Do not duplicate direct command implementations. Interactive scan callback constructs `_build_scan_service(...).scan()`. Interactive report callback constructs `_build_report_service(...)` and calls `generate(force=..., dry_run=..., scan=filtered_scan)`. Doctor callback should call the underlying doctor service rather than invoking the Typer command and catching `typer.Exit`.

- [ ] **Step 4: Replace `_interactive_menu()` implementation**

Bare callback behavior:

```python
if ctx.invoked_subcommand is None:
    try:
        _require_a_terminal(...)
        run_interactive(actions=_interactive_actions(), input=TerminalInput(), console=Console())
    except ConfigurationError as exc:
        _handle_expected_error(exc, code=3)
```

Keep `agent-worklog run` as the existing linear wizard for users/scripts that explicitly invoke it.

- [ ] **Step 5: Add end-to-end scripted interaction integration test**

Use injected scripted input/actions to drive:

```text
Main -> Generate Report -> Review -> deselect one session -> Generate -> Result -> Main -> Quit
```

Assert one scan, one report generation, and filtered session count.

- [ ] **Step 6: Add terminal-safety integration regression**

Inject an input provider whose `read_key()` raises `KeyboardInterrupt`; assert invocation exits cleanly and the fake terminal restore marker is set.

- [ ] **Step 7: Write failing documentation tests**

Pin that both READMEs contain the key-driven quick-start wording and that CLI reference mentions `Space` for selection and repository/session review. Remove tests that require the old numbered menu copy if present.

- [ ] **Step 8: Update docs and changelog**

README example should show:

```text
Agent Worklog
❯ Generate Report
  Browse Sessions
  Check Setup
  Settings

↑↓ / jk Navigate   Enter Select   q Quit
```

Document that Generate Report opens a summary, Review Sessions supports repository and individual toggles, and direct subcommands remain unchanged.

- [ ] **Step 9: Run documentation + integration tests**

```bash
uv run pytest tests/integration/test_cli.py tests/unit/test_documentation.py -v
```

Expected: PASS.

- [ ] **Step 10: Run the complete release gate**

```bash
uv sync --locked --extra dev
uv run pytest --cov=agent_worklog --cov-fail-under=80
uv run ruff check .
uv run pyright
```

Expected: all commands exit 0 and coverage remains >= 80%.

- [ ] **Step 11: Manually smoke-test on a real TTY**

Run:

```bash
uv run agent-worklog
```

Verify arrow keys, `j/k`, Enter, Space, Esc/b, q, repository expand/toggle, result->main navigation, and Ctrl-C terminal restoration. Then verify direct commands:

```bash
uv run agent-worklog --help
uv run agent-worklog doctor
uv run agent-worklog scan --period last-week
```

- [ ] **Step 12: Commit final wiring/docs**

```bash
git add src/agent_worklog/cli.py tests/integration/test_cli.py README.md README.zh-TW.md docs/cli-reference.md CHANGELOG.md tests/unit/test_documentation.py
git commit -m "feat(cli): upgrade bare command to terminal-native interaction"
```

---

## Plan Self-Review

- Spec coverage: all five P0 capabilities are assigned to Tasks 1-6; direct CLI compatibility, error recovery, terminal restoration, read-only Browse Sessions, overwrite handling, and excluded P1/P2 features are explicit.
- Placeholder scan: no TBD/TODO/fill-later steps remain; every implementation task names exact files, tests, commands, and required behavior.
- Type consistency: `ReportDraft` owns scan invalidation; `SelectionState` owns session IDs and filtered `ScanResult`; controller consumes both and passes the filtered result into the existing `ReportService.generate(scan=...)` seam.
- Dependency check: implementation uses only Python stdlib, Rich, and Typer already declared in `pyproject.toml`.
