# Interactive Menu Design

**Date:** 2026-08-07

## Summary

Make a bare `agent-worklog` invocation open a menu that dispatches to the work
the CLI already does: generate a report, edit settings, check the setup, or
scan sessions. The menu asks which action to take, asks only the questions that
action cannot default, and then calls the existing command function.

No new wizard logic comes with this change. `run` already asks its way through a
report and `config init` already walks every setting; the menu is the umbrella
over both. `doctor` and `scan` are not wizards, so the menu asks them the single
question that varies — which harness — and passes defaults for the rest.

The report path also gains a dry run. `ReportService.generate` already accepts
`dry_run`, so `run` grows a `--dry-run` option that prints the report instead of
writing it, and the menu offers that as a question.

This work stacks on `feat/run-interactive`, which supplies the `run` wizard and
the prompt helpers, and which in turn stacks on the interactive `config init`.

## Goals

- Give a bare `agent-worklog` a menu instead of a help dump.
- Reach report, settings, doctor, and scan from that menu.
- Reuse `run` and `config_init` rather than restating their questions.
- Let the report path print instead of write, from both the menu and the CLI.
- Refuse to prompt when nobody can answer, with the existing exit code 3.
- Leave every existing subcommand invocation behaving exactly as it does today.

## Non-goals

- A curses or full-screen TUI. The menu is a numbered prompt.
- A config sub-menu offering `init` vs `set` vs `unset`. The menu means "walk
  the settings", which `config init` already is.
- A custom period prompt for the menu's `scan`. `scan` has no default period —
  `_resolve_period` demands exactly one of `--days`, `--period`, or `--since` —
  so the menu passes `period="last-week"` explicitly, matching the window `run`
  chooses when its period question is answered with Enter. `run` or
  `scan --since/--until` cover the rest.
- A menu-wide dry-run switch. Three of the four actions either write nothing or
  already have an escape.
- Looping back to the menu after an action completes.

## Approaches Considered

### 1. Callback dispatching to existing command functions

Replace `no_args_is_help=True` with an `@app.callback(invoke_without_command=True)`
that opens the menu when no subcommand was given. Each menu entry calls the
existing command function.

This is the selected approach. It adds no second implementation of any prompt,
and the commands keep their own terminal guards and exit codes.

### 2. A separate `interactive` subcommand

Add `agent-worklog interactive` and leave bare invocation printing help.

Rejected: it is strictly less discoverable, and discoverability is the point of
the change. The behavior compatibility it protects is narrow — see Compatibility.

### 3. Menu re-implementing each command's questions inline

Have the menu ask harness, period, detail, and output itself, then call the
services directly.

Rejected: it duplicates the `run` wizard, and the copy would drift from it.

## Architecture

### Entry point

`app` drops `no_args_is_help=True` and gains a callback:

```python
@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        _interactive_menu()
```

When a subcommand was named, the callback returns and Typer dispatches it as it
does today. `--help` is unaffected.

### Menu

`_interactive_menu()` guards the terminal, prints the choices, and re-asks until
an answer is understood:

```
What do you want to do?
  1  Generate a report
  2  Scan sessions
  3  Check setup (doctor)
  4  Edit settings
  q  Quit
```

- `1` calls `run(verbose=False, dry_run=_ask_yes(...))`
- `2` asks the harness, then calls `scan(...)`
- `3` asks the harness, then calls `doctor(...)`
- `4` calls `config_init()`
- `q` or an empty answer returns, exit 0
- anything else reprints the choices and asks again

Re-asking rather than aborting matches how `config init` treats a rejected
value, for the same reason: a typo should not throw away the session.

### Dispatching to doctor and scan

`doctor` and `scan` declare `harness: Harness = _HARNESS_OPTION`. That default is
a Typer `OptionInfo`, not a `Harness`, so it only becomes a real value when Typer
invokes the command. Calling `doctor()` bare would pass the `OptionInfo` through.
The menu therefore resolves the harness itself with the existing
`_ask_harness(settings)` helper, which echoes the enabled harnesses, prompts for
one, and returns a `Harness`. Every other parameter is passed explicitly:

```python
harness = _ask_harness(settings)
doctor(harness=harness, verbose=False, quiet=False)
scan(
    days=None, period="last-week", since=None, until=None,
    root_only=False, sanitize=None,
    harness=harness, verbose=False, quiet=False,
)
```

The period is named rather than left unset because `scan` has no default period:
`_resolve_period` raises `typer.BadParameter` unless exactly one of `days`,
`period`, or `since` is given, so `days=period=since=None` is a usage error, not
a default. `last-week` is the window `run` picks when its period question is
answered with Enter. The remaining parameters do default to `None` or `False` as
plain Python values, so passing those literally reproduces the CLI default.

### Dry run on the report path

`ReportService.generate` already takes `dry_run` and skips both the
already-exists check and the file write. The `report` command already prints
`result.content` when dry running. `run` gains the same:

```python
@app.command()
def run(
    verbose: bool = typer.Option(False, "--verbose"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
```

`dry_run` threads into `generate(force=force, dry_run=dry_run, scan=scan)`. On a
dry run the command prints the report content instead of
`Report written to {path}`. This makes `agent-worklog run --dry-run` work from
the command line too, matching `report --dry-run`.

A dry run also skips `_ask_output_path` and takes `_default_output_path` with
`force=False`. Nothing is written, so asking where to write it — and whether to
overwrite a file that will never be touched — is a question whose answer cannot
matter.

The menu asks `Dry run - print the report instead of writing a file? [y/N]`
before calling `run`.

Dry run is not added to the other three actions. `doctor` and `scan` write
nothing. `config init` already writes nothing when every prompt is answered with
Enter, which is the documented behavior of that command.

## Data Flow

```
agent-worklog (no args)
  -> main() callback, invoked_subcommand is None
  -> _interactive_menu()
     -> _require_a_terminal(...)          exit 3 if piped
     -> prompt for an action
        1 -> _ask_yes(dry run) -> run(verbose=False, dry_run=...)
        2 -> config_init()
        3 -> _ask_harness() -> doctor(harness=..., verbose=False, quiet=False)
        4 -> _ask_harness() -> scan(harness=..., period="last-week", ...)
        q -> return
```

`agent-worklog <subcommand> ...` skips the menu entirely: the callback sees a
subcommand name and returns.

## Error Handling

The menu guards its own prompt with the existing `_require_a_terminal`, raising
`ConfigurationError` handled as exit code 3. The message names the way out:

```
Error: agent-worklog needs a terminal to show the menu; run a subcommand directly
```

The dispatched commands keep their own guards and their own exit codes. `run`
already refuses a non-terminal, and `config_init` already refuses one. Their
`_handle_expected_error` calls raise `typer.Exit`, which propagates out through
the menu and the callback untouched — the menu catches nothing and translates
nothing. Exit codes therefore stay identical whether a command was reached from
the menu or from the command line.

The menu does raise `ConfigurationError` on its own account, in two places: the
terminal guard, and the harness question for `doctor` and `scan`. Loading the
settings can fail, and `_enabled_harnesses` raises when every harness is
switched off. The menu therefore wraps its own body in the same
`except ConfigurationError` / `_handle_expected_error(exc, code=3)` pair the
commands use. Without it, a machine with every harness disabled would answer the
menu with a traceback rather than the message and exit code the same
configuration produces from `run`.

The handler wraps only the menu's own prompting. The dispatched commands handle
their errors internally and raise `typer.Exit`, which is not a
`ConfigurationError` and so passes straight through.

## Compatibility

Dropping `no_args_is_help=True` changes what a bare `agent-worklog` does: it
prompts instead of printing help. A script invoking it bare to capture help gets
the terminal guard and exit 3 instead of exit 0 and the help text. This is
accepted, and the guard means such a script fails loudly rather than hanging on
a prompt. `agent-worklog --help` remains the way to get help and is unchanged.

`config_app` keeps `no_args_is_help=True`; a bare `agent-worklog config` still
prints the config group's help.

## Component Changes

- `src/agent_worklog/cli.py`
  - `app` loses `no_args_is_help=True`.
  - New `main` callback with `invoke_without_command=True`.
  - New `_interactive_menu`, plus a small helper per dispatched action.
  - `run` gains `--dry-run` and the print-instead-of-write branch.
- `README.md`, `README.zh-TW.md` document the menu and `run --dry-run`.
- `CHANGELOG.md` gets the entry.
- `tests/integration/test_cli.py` gets the menu tests.
- `tests/unit/test_documentation.py` gets assertions for the new docs.

No service, adapter, or settings module changes.

## Testing

Integration tests patch the `_stdin_is_a_terminal` seam, as the `config init`
tests do — `CliRunner` pipes stdin, so `isatty()` is always false under the
runner and the guard would otherwise be untestable.

- Menu `1` runs the report wizard.
- Menu `1` with a yes to dry run prints the report and writes no file.
- Menu `2` runs the settings walk.
- Menu `3` runs doctor against the answered harness.
- Menu `4` runs scan against the answered harness, over the last full week. One
  such test drives the real `scan` command with only `_build_scan_service`
  stubbed, so a menu argument list `scan` would reject cannot pass.
- The menu's argument lists name every parameter of the commands they call, so
  a new option on `scan`, `doctor`, or `run` cannot silently reach the menu as a
  `typer.OptionInfo`.
- An unrecognized answer reprints the choices and asks again.
- `q` exits 0 without doing anything.
- An empty answer exits 0 without doing anything.
- A non-terminal stdin exits 3 and names the way out.
- Choosing doctor or scan with every harness disabled exits 3 with the
  configuration message, not a traceback.
- `agent-worklog <subcommand>` still dispatches normally and shows no menu.
- `agent-worklog --help` still prints help.
- `run --dry-run` from the command line writes no file and prints the report.
- `run --dry-run` never reaches the output-path question, and takes the default
  path unforced.

Each new documentation assertion is checked against the pre-change docs to
confirm it fails without the content it guards.
