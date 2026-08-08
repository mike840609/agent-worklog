# P0 Interactive UX Design

**Date:** 2026-08-07

## Summary

Upgrade Agent Worklog's bare `agent-worklog` experience from a one-shot numbered prompt into a lightweight terminal-native interaction layer while preserving every existing direct CLI command and service contract.

The P0 scope adds five capabilities:

1. A key-driven main menu with arrow/Vim navigation and consistent footer hints.
2. A persistent interactive flow that can return to previous screens and the main menu instead of exiting after each action.
3. A report setup summary screen that uses defaults first and lets the user edit only what they need.
4. A repository-aware session review screen where a repository can be toggled as a group and individual sessions can be toggled after expansion.
5. Result screens with explicit next actions such as returning to the main menu or generating another report.

This remains a Typer + Rich CLI. It does not introduce Textual, curses, a full-screen alternate buffer, mouse support, animation, or a persistent TUI framework.

## Goals

- Make the bare `agent-worklog` invocation feel like a terminal application rather than a questionnaire.
- Support `↑/↓`, `j/k`, `Enter`, `Space`, `Esc/b`, and `q` where appropriate.
- Keep direct subcommands backward-compatible for scripting, CI, and piped use.
- Let users review and adjust report settings from a summary screen before scanning.
- Let users include or exclude entire repositories and individual sessions for one report run.
- Reuse `ScanService`, `ReportService`, harness sources, renderers, and current configuration behavior rather than duplicating business logic in the UI.
- Recover from expected interactive errors without terminating the whole interactive session.
- Restore terminal state reliably after normal exit, errors, and Ctrl-C.

## Non-goals

The following are explicitly outside P0:

- Textual/curses or any full-screen TUI framework.
- Mouse support.
- Search or `/` filtering.
- Session inspection/detail views.
- Recent report history.
- Persisted UI-only preferences or persisted session selections.
- Opening report files with platform-specific launchers.
- JSON output changes.
- Update/version shortcuts in the interactive footer.
- Animation or dashboard-style live views.
- Custom session sorting controls.
- Transferring a Browse Sessions result directly into report generation; that cross-flow can be added later without changing the P0 selection model.

## Existing Behavior to Preserve

The current direct commands remain the authoritative non-interactive surface:

```bash
agent-worklog scan --period last-week
agent-worklog report --period last-week
agent-worklog doctor
agent-worklog config list
agent-worklog --help
```

Their options, exit-code behavior, and service wiring remain unchanged unless a change is required solely to expose a reusable internal seam to the interactive controller.

Only a bare invocation enters the new interactive controller:

```bash
agent-worklog
```

If stdin is not a TTY, the bare invocation still refuses to prompt and exits with configuration error semantics, directing the caller to use a subcommand directly.

## Chosen Approach

### Typer + Rich + lightweight key-driven controller

The selected design keeps Typer as the CLI dispatcher and Rich as the renderer, then adds a small interactive layer for navigation and state.

Conceptually:

```text
                    ┌─ direct CLI commands ───────────┐
                    │ scan / report / doctor / config │
                    │ existing behavior unchanged     │
                    └───────────────┬─────────────────┘
                                    │
Services ◄──────────────────────────┘

agent-worklog (no args)
        │
        ▼
InteractiveController
        │
        ├── MainMenu
        ├── ReportSetupScreen
        ├── SessionReviewScreen
        └── ResultScreen
                │
                ▼
        existing Services
```

The interactive layer owns navigation and short-lived draft state only. It does not reimplement scanning, repository resolution, summarization, rendering, privacy redaction, output writing, or harness access.

## Component Boundaries

Add a focused package rather than growing `cli.py` further:

```text
src/agent_worklog/
├── cli.py
├── interactive/
│   ├── __init__.py
│   ├── controller.py
│   ├── input.py
│   ├── models.py
│   ├── render.py
│   └── selection.py
```

### `interactive/controller.py`

Responsibilities:

- Own the current screen and navigation loop.
- Handle screen transitions.
- Invoke existing services through small reusable seams.
- Convert expected service failures into interactive recovery states.
- Return to the main menu after completed actions instead of terminating the process.

It must not contain terminal escape parsing or repository/session selection algorithms.

### `interactive/input.py`

Responsibilities:

- Read one key at a time from a TTY.
- Normalize platform key sequences into logical keys such as `UP`, `DOWN`, `ENTER`, `SPACE`, `ESCAPE`, and `CHAR:<x>`.
- Support POSIX terminals through the Python standard library and Windows consoles through the Python standard library; no new TUI/input dependency is introduced.
- Enter and restore terminal input mode safely.
- Restore cursor/input state in `finally` paths and after Ctrl-C.

The rest of the interactive code consumes normalized logical keys rather than terminal escape sequences.

### `interactive/models.py`

Defines short-lived UI state, including:

```python
class Screen(Enum):
    MAIN = ...
    REPORT_SETUP = ...
    SESSION_REVIEW = ...
    REPORT_RESULT = ...
```

and a report draft conceptually equivalent to:

```python
@dataclass
class ReportDraft:
    harness: Harness
    period: DateRange
    include_subagents: bool
    sanitize: bool
    detail: DetailLevel
    narrative: bool
    dry_run: bool
    scan: ScanResult | None
    selected_session_ids: set[str]
```

The exact type layout may differ if needed to avoid import cycles, but the responsibilities and invalidation rules below are required.

### `interactive/render.py`

Responsibilities:

- Render the current screen with Rich.
- Keep footer-control wording consistent across screens.
- Render selection markers and collapsed/expanded repository groups.
- Keep rendering separate from state mutation so output can be tested without a real terminal.

### `interactive/selection.py`

Responsibilities:

- Build and mutate per-session selection state.
- Toggle an entire repository group.
- Toggle one session.
- Derive repository selection status from child sessions only.
- Produce the filtered `ScanResult` used by report generation.

Repository selection state is never stored independently from its children.

## Screen 1: Main Menu

The bare command opens:

```text
 Agent Worklog
 Turn coding-agent sessions into engineering reports

 ❯ Generate Report
   Browse Sessions
   Check Setup
   Settings

 ↑↓ / jk Navigate   Enter Select   q Quit
```

Required controls:

- `↑` or `k`: move up.
- `↓` or `j`: move down.
- `Enter`: select the current item.
- `1` through `4`: activate the matching item directly.
- `q` or `Esc`: quit from the main menu.

Actions do not permanently terminate the interactive process after completion. They return to an interactive result/recovery screen or the main menu.

`Check Setup` and `Settings` may reuse the existing doctor/config editing seams, but the interactive controller owns what happens afterward so successful completion returns to the interactive application rather than ending the process.

## Screen 2: Report Setup

Selecting **Generate Report** opens a summary screen immediately using the values that would otherwise be the wizard defaults:

```text
 Generate Report

 Harness        OpenCode
 Period         Last week
 Detail         Full
 Subagents      Included
 Narrative      Enabled
 Sanitize       Off

 ❯ Review sessions
   Harness
   Period
   Detail
   Subagents
   Narrative
   Sanitize
   Dry run
   Back

 ↑↓ Navigate   Enter Edit   r Review   b Back
```

### Behavior

- No linear questionnaire runs on entry.
- Each editable row changes one field and returns to the same summary screen.
- `Review sessions` runs a scan only after the draft is configured.
- `r` is a shortcut to `Review sessions`.
- `b` or `Esc` returns to the main menu.
- Output path is intentionally not editable in P0 interactive mode.
- Interactive report generation uses the existing `_default_output_path(settings, period)` rule.
- `dry_run=True` prints the report without writing, preserving current semantics.
- If a non-dry-run default output already exists, the interactive flow must offer an explicit **Overwrite once** recovery action that retries generation with `force=True`, plus a Back action. It must never overwrite implicitly.
- Direct `report --output ...` remains the supported route for choosing a custom path.

### Scan invalidation invariant

The scan identity is:

```text
(harness, period, include_subagents, sanitize)
```

Changing any of those fields must perform both:

```python
draft.scan = None
draft.selected_session_ids.clear()
```

Changing these fields must **not** invalidate the scan:

- `detail`
- `narrative`
- `dry_run`

This invariant must be unit tested.

## Screen 3: Session Review

The report review supports the chosen **repository + individual session** selection model.

Example:

```text
 Review Sessions   15 / 18 selected · 240 / 260 msgs

 ▼ ● agent-worklog                         8 / 9   Aug 3–8 · 24 msgs
      ● Fix sanitize export                        Aug 3 · 4 msgs
    ❯ ● Add interactive menu                       [sub] Aug 5 · 3 msgs
      ○ Scratch parser debugging                   Aug 4 · 2 msgs
      ● Release v0.8.0                             Aug 3 · 1 msg

 ▶ ● assets-tracker                        5 / 5   Aug 4–7 · 96 msgs

 ▼ ◐ obsidian-wiki                         2 / 4   Jul 30 – Aug 4 · 40 msgs
      ● Improve wiki synthesis                     [sub] Aug 4 · 3 msgs
      ○ ses-7f21ac                                 Aug 3 · 2 msgs · No title
      ● Update docs                                Aug 2 · 3 msgs
      ○ Scratch session                            [sub] Aug 1 · 1 msg

 ↑↓ Navigate   Space Toggle   Enter Expand
 a All   n None   g Generate   b Back
```

Titles are left-aligned in a fixed column so the eye can run straight down
them; the dim date and message count (the in-period conversation volume) sit
in their own column to the right, making a session's activity and recency
visible without opening it. A `[sub]` tag marks sessions spawned by a parent
session, and any reason a session starts deselected is appended there too.
Repository rows append a date span and summed message count.

When the terminal is too narrow to hold both columns, the title absorbs the
truncation; below a floor of 12 title cells the metadata is dropped instead,
so a row never collapses to an ellipsis with no title in it.

The header totals the same message volume across the selection, because the
question in front of the user is whether the selection covers the period and a
row count cannot answer it: three light sessions and one heavy one read as
`3 / 4 selected · 9 / 309 msgs` against `1 / 4 selected · 300 / 309 msgs`. A
scan holding no messages at all omits the clause rather than showing `0 / 0`.

### Repository states

Repository marker is derived from its child-session selection state:

```text
●  every session selected
○  no sessions selected
◐  partially selected
```

No separate repository checkbox value is stored.

### Controls

When the cursor is on a repository:

- `Space`: if every child is selected, deselect all children; otherwise select all children.
- `Enter`: expand or collapse the repository.

When the cursor is on a session:

- `Space`: toggle that session.
- `Enter`: no P0 action; session inspection is deferred.

Global controls:

- `↑/↓` or `j/k`: move among visible rows.
- `a`: select all sessions.
- `n`: select no sessions.
- `g`: generate the report using the current selection.
- `b` or `Esc`: return to Report Setup while retaining valid scan/selection state.
- `q`: leave the report flow and return to the main menu without a confirmation prompt.

### Selection filtering

Selection happens after scanning and before report generation:

```text
ScanService
    ↓
ScanResult
    ↓
SelectionState
    ↓
filtered ScanResult
    ↓
ReportService.generate(scan=filtered_scan)
```

Harness discovery logic is not changed to implement selection.

The filtered `ScanResult` must remain structurally valid for the existing `ReportService.generate(scan=...)` path and preserve warnings and repository/session metadata required downstream.

### Empty selection safety

`g` must not invoke report generation when zero sessions are selected. The screen remains active and communicates that at least one session must be selected.

## Browse Sessions

`Browse Sessions` uses the same grouped session renderer but without selection controls.

P0 behavior:

```text
Browse Sessions
    ↓
choose harness
    ↓
choose period
    ↓
scan
    ↓
read-only grouped browser
```

Controls are limited to navigation, expand/collapse, Back, and Quit-to-main-menu. Browse Sessions is read-only in P0 and does not transfer its scan directly into Generate Report. Browse Sessions uses the same grouped renderer and metadata as Session Review — a date and message count per session, and a date span and message total per repository — so the read-only record carries the same decision signals.

## Screen 4: Report Result

A successful report generation shows an explicit result screen:

```text
 ✓ Report generated

 Period          Aug 3 – Aug 9
 Repositories    3
 Sessions        15
 Output          reports/worklog-2026-08-03_2026-08-09.md

 ❯ Back to main menu
   Generate another report
   Print report path

 ↑↓ Navigate   Enter Select   q Main menu
```

### Behavior

- **Back to main menu** clears the report-flow navigation state and returns to Main Menu.
- **Generate another report** preserves the current report option values but clears `scan` and `selected_session_ids`, then returns to Report Setup.
- **Print report path** prints or exposes the path without launching a platform-specific application.
- `q` returns to Main Menu.

`Open report` is intentionally excluded from P0 because it introduces platform-specific launcher behavior (`open`, `xdg-open`, Windows shell behavior, and headless/SSH concerns).

## Error Handling

### Direct CLI

Existing direct-command exception and exit-code contracts remain unchanged.

### Interactive flow

Expected errors become recoverable screen states instead of terminating the entire interactive process.

Example for a harness source failure:

```text
 Generate Report

 ✗ Could not read OpenCode sessions
   <safe existing error detail>

 ❯ Check setup
   Change harness
   Back to report
   Main menu
```

The interactive layer should reuse existing exception types and safe/redacted error messages rather than creating a second error taxonomy.

A report-output collision is also recoverable: the interactive screen offers **Overwrite once** and Back. The overwrite action applies only to that generation attempt and does not become persisted configuration.

### Zero-session recovery

A scan with no matching sessions does not terminate the interactive application. Show a recovery screen such as:

```text
 No sessions found

 Harness    Claude Code
 Period     Last week

 ❯ Change period
   Change harness
   Back
```

The direct `scan`/`report` commands retain their current no-session exit semantics.

## Terminal Safety

The interactive input layer must guarantee restoration of terminal state after:

- normal quit,
- returning from a screen,
- expected errors,
- unexpected exceptions,
- Ctrl-C / `KeyboardInterrupt`.

At minimum this includes restoring any raw/cbreak mode, input echo behavior, and cursor visibility changed by the UI.

Terminal setup/teardown must be centralized in `interactive/input.py` or a single equivalent abstraction so screens cannot leave the terminal partially configured.

## TTY Compatibility

- Bare `agent-worklog` requires a TTY.
- `agent-worklog --help` must not enter interactive mode.
- Named subcommands must not enter interactive mode.
- Piped/non-TTY bare invocation must fail clearly instead of reading from stdin.
- Direct subcommands remain the supported automation path.
- Key navigation must work on supported POSIX terminals and Windows consoles without adding a third-party terminal UI dependency.

## Testing Strategy

### 1. State-machine unit tests

The majority of interaction behavior should be tested without a real terminal.

Required examples:

```text
MAIN + DOWN
→ selected item becomes Browse Sessions
```

```text
REPORT_SETUP + change detail
→ cached scan remains
→ selections remain
```

```text
REPORT_SETUP + change period
→ cached scan cleared
→ selections cleared
```

```text
SESSION_REVIEW + SPACE(repository)
→ all child sessions toggle together
```

```text
SESSION_REVIEW + SPACE(one session)
→ repository marker becomes partial when appropriate
```

```text
SESSION_REVIEW + g with zero selected
→ report service is not invoked
```

```text
REPORT_GENERATE + existing default output
→ no overwrite occurs automatically
→ Overwrite once retries with force=True
```

### 2. Renderer tests

Render screens into a test console/string buffer and assert semantic content rather than exact ANSI output.

Main-menu assertions include:

- `Agent Worklog`
- `Generate Report`
- `↑↓ / jk`
- `Enter`
- `q Quit`

Session-review assertions include:

- selected/total count,
- repository markers `●`, `○`, `◐`,
- `Space Toggle`,
- `g Generate`,
- `b Back`.

Avoid snapshots that are coupled to exact whitespace or escape sequences unless a specific alignment regression requires one.

### 3. CLI integration tests

Preserve current integration coverage and add tests for the interactive seam.

Required cases:

- `agent-worklog --help` does not show the interactive menu.
- `agent-worklog report ...` does not show the interactive menu.
- bare `agent-worklog` with non-TTY stdin exits with the existing configuration-error class/code behavior.
- a mocked key source can drive this end-to-end path without a real TTY:

```text
Main
→ Generate Report
→ Review sessions
→ toggle a session
→ Generate
→ Result
→ Main
→ Quit
```

- Ctrl-C/input exceptions restore terminal state.
- mocked POSIX and Windows key adapters normalize navigation keys to the same logical input values.

## Documentation Impact

Update the user-facing interactive-menu documentation after implementation to reflect:

- key-driven navigation,
- Report Setup summary behavior,
- session selection,
- result-screen navigation,
- default-output-path and overwrite-once behavior,
- the fact that direct subcommands remain unchanged.

The existing `docs/interactive-menu-design.md` remains historical design context for the v0.8.0 numbered-prompt implementation; this spec supersedes its interactive-flow decisions for the P0 upgrade rather than silently rewriting that historical document.

## Acceptance Criteria

P0 is complete when all of the following are true:

1. Bare `agent-worklog` presents a key-driven menu rather than requiring a typed numeric `Choice:` prompt.
2. Main-menu navigation supports `↑/↓`, `j/k`, `Enter`, numeric shortcuts, and quit controls.
3. Completed interactive actions can return to the main menu without restarting the process.
4. Generate Report opens a settings summary first rather than immediately walking a linear questionnaire.
5. Users can edit one setting and return to the summary screen.
6. Scan invalidation follows the exact identity `(harness, period, include_subagents, sanitize)`.
7. Session Review groups sessions by repository.
8. A repository can be selected/deselected as a group.
9. Expanded repositories allow individual session selection.
10. Repository `●/○/◐` status is derived exclusively from child session state.
11. A report cannot be generated with zero selected sessions.
12. Report generation receives a filtered, valid `ScanResult` and existing report business logic remains authoritative.
13. P0 interactive report generation uses the normal default output path; custom paths remain a direct-CLI feature.
14. Existing output files are never overwritten implicitly; **Overwrite once** is an explicit recovery action.
15. Result screens provide explicit navigation back to the main menu and a generate-another path.
16. Expected interactive errors offer recovery actions without terminating the whole interactive application.
17. Bare non-TTY invocation remains rejected, while named subcommands remain automation-safe.
18. Terminal input/cursor state is restored after normal exit, errors, and Ctrl-C.
19. Navigation input is normalized consistently on supported POSIX and Windows terminals using the Python standard library only.
20. All interactive screens use consistent control hints.
21. Browse Sessions remains read-only in P0 and returns through the interactive navigation flow.
22. No Textual/curses dependency or other P1/P2 feature is introduced as part of this work.
