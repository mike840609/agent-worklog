# Interactive Menu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a bare `agent-worklog` open a menu that dispatches to the report wizard, the settings walk, doctor, or scan, and give the report path a dry run.

**Architecture:** Replace the app's `no_args_is_help=True` with a Typer callback that runs when no subcommand was named. The callback opens a numbered menu that calls the existing `run` and `config_init` functions unchanged, and calls `doctor` and `scan` after asking the one question they cannot default — the harness. `run` gains `--dry-run`, threaded into the report service's existing `dry_run` support.

**Tech Stack:** Python, Typer, pytest, `CliRunner`, ruff, pyright.

**Design doc:** `docs/interactive-menu-design.md`

## Global Constraints

- Branch: `feat/interactive-menu`, based on `feat/run-interactive`. Do not rebase onto `main`.
- Tests: `uv run pytest --cov=agent_worklog --cov-fail-under=80`
- Lint: `uv run ruff check .`
- Types: `uv run pyright`
- All three must be clean before each commit.
- No new dependencies.
- No service, adapter, or settings module changes. `src/agent_worklog/cli.py` is the only source file modified.
- Prompting must refuse a non-terminal stdin with exit code 3, and the message must name a non-interactive way to do the same thing.
- Every documentation assertion added must be verified to fail against the pre-change docs.

## File Structure

- `src/agent_worklog/cli.py` — modified. Gains the callback, `_interactive_menu`, the per-action dispatch helpers, and `--dry-run` on `run`. All other files are tests or docs.
- `tests/integration/test_cli.py` — modified. Menu behavior tests.
- `tests/unit/test_documentation.py` — modified. Assertions guarding the new docs.
- `README.md`, `README.zh-TW.md`, `CHANGELOG.md` — modified. User-facing documentation.

Existing seams reused, all already in `cli.py` on `feat/run-interactive`:

- `_stdin_is_a_terminal() -> bool` — the patch point every prompting test uses.
- `_require_a_terminal(message: str) -> None` — raises `ConfigurationError`.
- `_prompt(prompt: str) -> str` — prompts, returns a stripped string.
- `_ask_yes(prompt: str, *, default: bool) -> bool`
- `_ask_harness(settings: AppSettings) -> Harness` — prompts only among enabled harnesses; raises `ConfigurationError` via `_enabled_harnesses` when all are disabled.
- `_load_settings() -> AppSettings`
- `_handle_expected_error(exc: Exception, *, code: int) -> None` — echoes and raises `typer.Exit`.

---

### Task 1: `run --dry-run`

Independent of the menu and useful on its own: `agent-worklog run --dry-run` previews a report without writing it. The menu consumes this in Task 2.

**Files:**
- Modify: `src/agent_worklog/cli.py` — the `run` command
- Modify: `README.md`, `README.zh-TW.md`, `CHANGELOG.md`
- Test: `tests/integration/test_cli.py`

**Interfaces:**
- Consumes: `ReportService.generate(*, force: bool = False, dry_run: bool = False, scan: ScanResult | None = None)` — already supports `dry_run`; it skips both the already-exists check and the file write.
- Produces: `run(verbose: bool = False, dry_run: bool = False) -> None`. Task 2 calls this with both arguments as keywords.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_cli.py`. This mirrors `test_run_scans_once_then_generates`, but the stub's `generate` honors `dry_run` by not writing, the way the real service does.

```python
def test_run_dry_run_prints_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ), until=datetime(2026, 7, 27, tzinfo=TZ)
    )
    output_path = tmp_path / "worklog.md"
    scan = SimpleNamespace(
        loaded_session_count=2,
        sessions_by_repository={
            "git:github.com/mike/agent-worklog": [
                SimpleNamespace(repository=SimpleNamespace(display_name="Agent Worklog"))
            ]
        },
        warnings=[],
    )
    seen: dict[str, object] = {}

    class StubScanService:
        def scan(self):
            return scan

    class StubReportService:
        def __init__(self, output_path, period) -> None:
            self.output_path = output_path
            self.period = period

        def generate(self, *, force: bool = False, dry_run: bool = False, scan=None):
            seen["dry_run"] = dry_run
            if not dry_run:
                self.output_path.write_text("# Engineering Worklog\n")
            report = WorklogReport(
                generated_at=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
                period=self.period,
                repositories=[
                    RepositorySummary(
                        repository_id="git:github.com/mike/agent-worklog",
                        display_name="Agent Worklog",
                    )
                ],
            )
            return SimpleNamespace(
                output_path=self.output_path,
                content="# Engineering Worklog\n",
                report=report,
            )

    def build_scan(settings, period, root_only=False, *, harness, sanitize, progress):
        return StubScanService()

    def build_report(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        harness,
        sanitize,
        allow_remote_llm,
        detail,
        progress,
    ):
        return StubReportService(output_path, period)

    _answer_for_run(
        monkeypatch,
        output_path=output_path,
        period=period,
        final_accept=True,
    )
    monkeypatch.setattr(cli, "_build_scan_service", build_scan)
    monkeypatch.setattr(cli, "_build_report_service", build_report)

    result = runner.invoke(cli.app, ["run", "--dry-run"])

    assert result.exit_code == 0, result.stdout
    assert seen["dry_run"] is True
    # A dry run prints the report instead of writing it.
    assert not output_path.exists()
    assert "# Engineering Worklog" in result.stdout
    assert "Report written to" not in result.stdout
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/integration/test_cli.py::test_run_dry_run_prints_without_writing -v`

Expected: FAIL. Typer rejects the unknown `--dry-run` option with exit code 2, so the `exit_code == 0` assertion fails.

- [ ] **Step 3: Add the option to `run`**

In `src/agent_worklog/cli.py`, change the `run` signature from:

```python
@app.command()
def run(
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
```

to:

```python
@app.command()
def run(
    verbose: bool = typer.Option(False, "--verbose"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
```

Update the docstring's second paragraph to end with a sentence about the new option:

```
    Useful when a manager wants a report from a machine you are
    already facing instead of you re-typing a long command line.
    `--dry-run` prints the report instead of writing a file.
```

- [ ] **Step 4: Thread `dry_run` into generation and print instead of writing**

In the same function, change the `generate` call from:

```python
            result = service.generate(force=force, scan=scan)
```

to:

```python
            result = service.generate(force=force, dry_run=dry_run, scan=scan)
```

Then change the final line of the function from:

```python
    reporter.message(f"Report written to {result.output_path}")
```

to:

```python
    if dry_run:
        typer.echo(result.content, nl=False)
    else:
        reporter.message(f"Report written to {result.output_path}")
```

`nl=False` matches how the `report` command prints its dry run, so the two commands produce byte-identical output.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/integration/test_cli.py::test_run_dry_run_prints_without_writing -v`

Expected: PASS

- [ ] **Step 6: Run the full suite, lint, and types**

```bash
uv run pytest --cov=agent_worklog --cov-fail-under=80
uv run ruff check .
uv run pyright
```

Expected: all clean. The existing `run` tests still pass because `dry_run` defaults to `False`.

- [ ] **Step 7: Document the option**

In `README.md`, find the section documenting `agent-worklog run` and add this line to it:

```markdown
Pass `--dry-run` to print the report to the terminal instead of writing a file.
```

In `README.zh-TW.md`, find the matching section and add:

```markdown
加上 `--dry-run` 會把報告印到終端機，而不寫入檔案。
```

In `CHANGELOG.md`, under `## Unreleased`, add:

```markdown
- `agent-worklog run` accepts `--dry-run`, printing the report instead of writing a file,
  matching what `report --dry-run` already did.
```

- [ ] **Step 8: Commit**

```bash
git add src/agent_worklog/cli.py tests/integration/test_cli.py README.md README.zh-TW.md CHANGELOG.md
git commit -m "feat(run): print the report instead of writing it with --dry-run"
```

---

### Task 2: The menu, with the report and settings entries

Turns a bare `agent-worklog` into a menu. Only entries `1`, `2`, and `q` exist after this task; `3` and `4` arrive in Task 3.

**Files:**
- Modify: `src/agent_worklog/cli.py` — the `app` construction, plus new functions
- Test: `tests/integration/test_cli.py`

**Interfaces:**
- Consumes: `run(verbose: bool = False, dry_run: bool = False)` from Task 1; `config_init() -> None`; `_require_a_terminal`, `_prompt`, `_ask_yes`, `_handle_expected_error`.
- Produces: `_interactive_menu() -> None` and `main(ctx: typer.Context) -> None`. Task 3 adds branches inside `_interactive_menu`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/integration/test_cli.py`. The menu's job is choosing and dispatching, so these patch the dispatched commands and assert on the call — they do not re-answer each wizard's questions.

```python
def test_bare_invocation_runs_the_report_wizard(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def stub_run(*, verbose: bool, dry_run: bool) -> None:
        seen["verbose"] = verbose
        seen["dry_run"] = dry_run

    monkeypatch.setattr(cli, "run", stub_run)
    _as_a_terminal(monkeypatch)

    # "1" chooses the report, "n" declines the dry run.
    result = runner.invoke(cli.app, [], input="1\nn\n")

    assert result.exit_code == 0, result.stdout
    assert seen == {"verbose": False, "dry_run": False}


def test_bare_invocation_can_ask_the_report_wizard_for_a_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def stub_run(*, verbose: bool, dry_run: bool) -> None:
        seen["dry_run"] = dry_run

    monkeypatch.setattr(cli, "run", stub_run)
    _as_a_terminal(monkeypatch)

    result = runner.invoke(cli.app, [], input="1\ny\n")

    assert result.exit_code == 0, result.stdout
    assert seen["dry_run"] is True


def test_bare_invocation_runs_the_settings_walk(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []
    monkeypatch.setattr(cli, "config_init", lambda: called.append(True))
    _as_a_terminal(monkeypatch)

    result = runner.invoke(cli.app, [], input="2\n")

    assert result.exit_code == 0, result.stdout
    assert called == [True]


def test_the_menu_asks_again_after_an_answer_it_does_not_know(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo must not end the session; the choices are shown again."""

    called: list[bool] = []
    monkeypatch.setattr(cli, "config_init", lambda: called.append(True))
    _as_a_terminal(monkeypatch)

    result = runner.invoke(cli.app, [], input="banana\n2\n")

    assert result.exit_code == 0, result.stdout
    assert called == [True]
    assert "choose one of the listed options" in result.stdout
    # The choices are printed again, so the second answer is an informed one.
    assert result.stdout.count("Generate a report") >= 2


def test_the_menu_quits_without_doing_anything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "config_init", lambda: pytest.fail("nothing should run"))
    _as_a_terminal(monkeypatch)

    result = runner.invoke(cli.app, [], input="q\n")

    assert result.exit_code == 0, result.stdout


def test_an_empty_answer_quits_the_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "config_init", lambda: pytest.fail("nothing should run"))
    _as_a_terminal(monkeypatch)

    result = runner.invoke(cli.app, [], input="\n")

    assert result.exit_code == 0, result.stdout


def test_the_menu_needs_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: False)

    result = runner.invoke(cli.app, [], input="1\n")

    assert result.exit_code == 3
    assert "needs a terminal" in result.stdout
    # The way out is naming a subcommand, not a different interactive command.
    assert "subcommand" in result.stdout


def test_naming_a_subcommand_does_not_open_the_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The callback must stand aside whenever Typer has a command to run."""

    monkeypatch.setattr(
        cli, "_interactive_menu", lambda: pytest.fail("the menu must not open")
    )

    result = runner.invoke(cli.app, ["config", "path"])

    assert result.exit_code == 0, result.stdout


def test_help_still_works_without_the_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli, "_interactive_menu", lambda: pytest.fail("the menu must not open")
    )

    result = runner.invoke(cli.app, ["--help"])

    assert result.exit_code == 0, result.stdout
    assert "Usage" in result.stdout
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/integration/test_cli.py -k "menu or bare_invocation or empty_answer_quits or help_still_works or naming_a_subcommand" -v`

Expected: FAIL. With `no_args_is_help=True` a bare invocation prints help and exits 0 without prompting, so the dispatch assertions fail and `_interactive_menu` does not exist.

- [ ] **Step 3: Let the app be invoked without a subcommand**

In `src/agent_worklog/cli.py`, change the `app` construction from:

```python
app = typer.Typer(
    no_args_is_help=True,
    help="Turn coding-agent sessions into repository-based engineering reports.",
)
```

to:

```python
app = typer.Typer(
    help="Turn coding-agent sessions into repository-based engineering reports.",
)
```

Leave `config_app`'s `no_args_is_help=True` alone: a bare `agent-worklog config` should keep printing that group's help.

- [ ] **Step 4: Add the menu and the callback**

Add this at the end of `src/agent_worklog/cli.py`, after the `config` commands. It must come after `run` and `config_init` are defined so the names resolve.

```python
_MENU_CHOICES = """What do you want to do?
  1  Generate a report
  2  Edit settings
  q  Quit"""


def _interactive_menu() -> None:
    """Offer the commands as a numbered list and run the one that is chosen.

    Every entry hands off to the command that already does the work, so the
    questions each one asks live in one place rather than being restated here.
    """

    try:
        _require_a_terminal(
            "agent-worklog needs a terminal to show the menu; "
            "run a subcommand directly instead"
        )
        while True:
            typer.echo(_MENU_CHOICES)
            # `_prompt` appends ": ", so a word reads better here than ">".
            answer = _prompt("Choice").casefold()
            if not answer or answer == "q":
                return
            if answer == "1":
                dry_run = _ask_yes(
                    "Dry run - print the report instead of writing a file?",
                    default=False,
                )
                run(verbose=False, dry_run=dry_run)
                return
            if answer == "2":
                config_init()
                return
            typer.echo("  choose one of the listed options")
    except ConfigurationError as exc:
        _handle_expected_error(exc, code=3)
        return


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Open the menu when no subcommand was named."""

    if ctx.invoked_subcommand is None:
        _interactive_menu()
```

The menu catches `ConfigurationError` because it raises one itself, from the terminal guard here and from the harness question in Task 3. The dispatched commands handle their own errors and raise `typer.Exit`, which is not a `ConfigurationError` and passes straight through, so exit codes stay the same whether a command is reached from the menu or the command line.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/integration/test_cli.py -k "menu or bare_invocation or empty_answer_quits or help_still_works or naming_a_subcommand" -v`

Expected: PASS

- [ ] **Step 6: Run the full suite, lint, and types**

```bash
uv run pytest --cov=agent_worklog --cov-fail-under=80
uv run ruff check .
uv run pyright
```

Expected: all clean. If a pre-existing test invoked the app with no arguments expecting the help text, it must be updated to call `--help` instead — that behavior change is intended and documented in the design's Compatibility section.

- [ ] **Step 7: Commit**

```bash
git add src/agent_worklog/cli.py tests/integration/test_cli.py
git commit -m "feat(cli): open a menu when no subcommand is named"
```

---

### Task 3: The doctor and scan entries

`doctor` and `scan` are not wizards, so the menu asks the one thing that varies — the harness — and passes every other parameter explicitly.

**Files:**
- Modify: `src/agent_worklog/cli.py` — `_MENU_CHOICES` and `_interactive_menu`
- Test: `tests/integration/test_cli.py`

**Interfaces:**
- Consumes: `_ask_harness(settings: AppSettings) -> Harness`, `_load_settings() -> AppSettings`, `doctor(harness, verbose, quiet)`, `scan(days, period, since, until, root_only, sanitize, harness, verbose, quiet)`.
- Produces: nothing new. This task only adds branches to `_interactive_menu`.

Both commands declare `harness: Harness = _HARNESS_OPTION`, and `_HARNESS_OPTION` is a `typer.Option(...)` object, not a `Harness`. It only becomes a real value when Typer invokes the command, so calling `doctor()` bare would pass the option object through. Every parameter must therefore be passed explicitly.

The period cannot be left unset either. `scan` has no default period: `_resolve_period` raises `typer.BadParameter` unless exactly one of `days`, `period`, or `since` is given, so `days=period=since=None` is a usage error, not a default. The menu passes `period="last-week"` — the window `run` picks when its period question is answered with Enter. The remaining parameters do default to plain `None` or `False`, so passing those values literally reproduces the command-line defaults.

- [ ] **Step 1: Write the failing tests**

Add to `tests/integration/test_cli.py`:

```python
def test_bare_invocation_runs_doctor_against_the_chosen_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def stub_doctor(*, harness, verbose: bool, quiet: bool) -> None:
        seen["harness"] = harness
        seen["verbose"] = verbose
        seen["quiet"] = quiet

    monkeypatch.setattr(cli, "doctor", stub_doctor)
    monkeypatch.setattr(cli, "_ask_harness", lambda settings: cli.Harness.OPENCODE)
    _as_a_terminal(monkeypatch)

    result = runner.invoke(cli.app, [], input="3\n")

    assert result.exit_code == 0, result.stdout
    assert seen == {
        "harness": cli.Harness.OPENCODE,
        "verbose": False,
        "quiet": False,
    }


def test_bare_invocation_runs_scan_against_the_chosen_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def stub_scan(
        *, days, period, since, until, root_only, sanitize, harness, verbose, quiet
    ) -> None:
        seen["harness"] = harness
        seen["days"] = days
        seen["period"] = period
        seen["since"] = since
        seen["until"] = until
        seen["root_only"] = root_only
        seen["sanitize"] = sanitize

    monkeypatch.setattr(cli, "scan", stub_scan)
    monkeypatch.setattr(cli, "_ask_harness", lambda settings: cli.Harness.CLAUDE_CODE)
    _as_a_terminal(monkeypatch)

    result = runner.invoke(cli.app, [], input="4\n")

    assert result.exit_code == 0, result.stdout
    assert seen["harness"] is cli.Harness.CLAUDE_CODE
    # `scan` rejects a call with no period at all, so the menu names the last
    # full week; every other option keeps its command-line default.
    assert seen["period"] == "last-week"
    assert seen["days"] is None
    assert seen["since"] is None
    assert seen["until"] is None
    assert seen["root_only"] is False
    assert seen["sanitize"] is None


def test_the_menu_reports_a_configuration_error_from_the_harness_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every harness disabled must exit 3, not raise through the callback."""

    def refuse(settings):
        raise ConfigurationError("every harness is disabled by configuration")

    monkeypatch.setattr(cli, "_ask_harness", refuse)
    monkeypatch.setattr(cli, "doctor", lambda **kwargs: pytest.fail("must not run"))
    _as_a_terminal(monkeypatch)

    result = runner.invoke(cli.app, [], input="3\n")

    assert result.exit_code == 3
    assert "every harness is disabled by configuration" in result.stdout
```

If `ConfigurationError` is not already imported in this test module, add it to the existing import from `agent_worklog.errors`. Confirm the exact module path with `grep -n "ConfigurationError" tests/integration/test_cli.py src/agent_worklog/cli.py`. Likewise confirm the enum member name for Claude Code with `grep -n "class Harness" -A6 src/agent_worklog/domain/*.py` and use whatever that file defines.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/integration/test_cli.py -k "doctor_against or scan_against or configuration_error_from_the_harness" -v`

Expected: FAIL. The menu does not recognize `3` or `4`, so it reprints the choices and then quits on end-of-input; the dispatch assertions fail.

- [ ] **Step 3: Add the two entries to the menu text**

In `src/agent_worklog/cli.py`, change `_MENU_CHOICES` from:

```python
_MENU_CHOICES = """What do you want to do?
  1  Generate a report
  2  Edit settings
  q  Quit"""
```

to:

```python
_MENU_CHOICES = """What do you want to do?
  1  Generate a report
  2  Edit settings
  3  Check setup (doctor)
  4  Scan sessions
  q  Quit"""
```

- [ ] **Step 4: Add the two branches**

In `_interactive_menu`, insert these two branches after the `answer == "2"` branch and before the final `typer.echo("  choose one of the listed options")`:

```python
            if answer in {"3", "4"}:
                settings = _load_settings()
                harness = _ask_harness(settings)
                if answer == "3":
                    doctor(harness=harness, verbose=False, quiet=False)
                else:
                    # `scan` has no default period: `_resolve_period` demands
                    # exactly one of days/period/since, so the menu names the
                    # last full week — the window pressing Enter at `run`'s
                    # period question chooses. `run` remains the way to any
                    # other period. Every other option keeps its default.
                    scan(
                        days=None,
                        period="last-week",
                        since=None,
                        until=None,
                        root_only=False,
                        sanitize=None,
                        harness=harness,
                        verbose=False,
                        quiet=False,
                    )
                return
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/integration/test_cli.py -k "doctor_against or scan_against or configuration_error_from_the_harness" -v`

Expected: PASS

- [ ] **Step 6: Run the full suite, lint, and types**

```bash
uv run pytest --cov=agent_worklog --cov-fail-under=80
uv run ruff check .
uv run pyright
```

Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add src/agent_worklog/cli.py tests/integration/test_cli.py
git commit -m "feat(cli): reach doctor and scan from the menu"
```

---

### Task 4: Documentation

**Files:**
- Modify: `README.md`, `README.zh-TW.md`, `CHANGELOG.md`
- Test: `tests/unit/test_documentation.py`

**Interfaces:**
- Consumes: the menu from Tasks 2 and 3.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the failing documentation test**

Add to `tests/unit/test_documentation.py`, following the file's existing style:

```python
def test_readmes_document_the_interactive_menu() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh_tw = Path("README.zh-TW.md").read_text(encoding="utf-8")

    for text in (readme, readme_zh_tw):
        # Running the command bare now prompts rather than printing help, so
        # both the menu and the way to still get help must be documented.
        assert "agent-worklog --help" in text
        assert "Generate a report" in text or "產生報告" in text


def test_readmes_document_the_run_dry_run_option() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh_tw = Path("README.zh-TW.md").read_text(encoding="utf-8")

    for text in (readme, readme_zh_tw):
        assert "--dry-run" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_documentation.py -k "interactive_menu or run_dry_run" -v`

Expected: `test_readmes_document_the_interactive_menu` FAILS.

`test_readmes_document_the_run_dry_run_option` may already PASS, because Task 1 documented `--dry-run` and `report --dry-run` may predate this work. A documentation assertion that passes without the content it guards is worthless. Verify it by checking whether `--dry-run` appears in both READMEs for a reason unrelated to `run`:

```bash
grep -n -- "--dry-run" README.md README.zh-TW.md
```

If the only occurrences are the lines Task 1 added, the assertion is meaningful and can stay as written. If `--dry-run` already appeared for the `report` command, tighten the assertion so it can only pass with the `run` content, for example by asserting on a phrase from the line Task 1 added, and re-run to confirm it fails with that line temporarily removed.

- [ ] **Step 3: Document the menu in `README.md`**

Find the section that introduces the commands and add:

````markdown
### Interactive menu

Run the command with no arguments to pick what to do from a menu:

```
$ agent-worklog
What do you want to do?
  1  Generate a report
  2  Edit settings
  3  Check setup (doctor)
  4  Scan sessions
  q  Quit
Choice:
```

Each entry runs the matching command, asking only the questions that command
cannot answer for itself. Use `agent-worklog --help` for the command list, and
run a subcommand directly in scripts — with no terminal to prompt at, the menu
exits with status 3 rather than reading from stdin.
````

- [ ] **Step 4: Document the menu in `README.zh-TW.md`**

Add the matching section, keeping the untranslated command output identical to the English README:

````markdown
### 互動式選單

不帶任何參數執行指令，就會出現選單：

```
$ agent-worklog
What do you want to do?
  1  Generate a report
  2  Edit settings
  3  Check setup (doctor)
  4  Scan sessions
  q  Quit
Choice:
```

每個選項都會執行對應的指令，只詢問該指令無法自行決定的問題。用
`agent-worklog --help` 查看指令清單；在腳本中請直接呼叫子指令，因為沒有終端機
可以作答時，選單會以狀態碼 3 結束，而不會去讀取 stdin。
````

- [ ] **Step 5: Add the changelog entry**

In `CHANGELOG.md`, under `## Unreleased`, add:

```markdown
- Running `agent-worklog` with no arguments opens a menu for generating a report, editing
  settings, checking the setup, or scanning sessions, instead of printing help. Each entry
  hands off to the existing command, so the menu restates none of their questions.
  `agent-worklog --help` still prints the command list.
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_documentation.py -v`

Expected: PASS

- [ ] **Step 7: Run the full suite, lint, and types**

```bash
uv run pytest --cov=agent_worklog --cov-fail-under=80
uv run ruff check .
uv run pyright
```

Expected: all clean.

- [ ] **Step 8: Commit**

```bash
git add README.md README.zh-TW.md CHANGELOG.md tests/unit/test_documentation.py
git commit -m "docs: document the interactive menu"
```

---

## Verification

After Task 4, confirm the whole feature by hand in a real terminal, because
`CliRunner` always pipes stdin and so can never exercise the real
`_stdin_is_a_terminal`:

```bash
uv run agent-worklog          # the menu appears; q quits
uv run agent-worklog --help   # the command list, no prompt
echo "" | uv run agent-worklog; echo "EXIT=$?"   # EXIT=3, names the way out
```

The design's Compatibility section accepts that the third command used to print
help and exit 0. The guard makes that change fail loudly instead of hanging.
