# CLI Progress Feedback Design

**Date:** 2026-07-30

## Summary

Add a single-line, stage-based progress indicator to the interactive `scan` and
`report` commands. The indicator will show a spinner for work with an unknown
duration and `completed/total` counts where the total is known. Core services
will publish progress through a small, Rich-independent interface; the CLI will
render those events with Rich.

`doctor` is outside this change because its checks are short and its existing
completed-check output is sufficient.

## Goals

- Give immediate, continuously animated feedback during blocking work.
- Identify the current stage of `scan` and `report`.
- Show accurate counts while sessions and repositories are processed.
- Keep only one transient progress line on screen.
- Preserve existing final output, warnings, and exit codes.
- Keep Rich and terminal-specific behavior outside core services.
- Avoid exposing session IDs, paths, repository names, or other sensitive data
  through progress messages.

## Non-goals

- Supporting machine-readable progress, CI logs, or shell-pipeline consumers.
- Adding percentages, elapsed-time estimates, nested progress bars, or a
  `--progress` option.
- Running operations concurrently or improving their runtime.
- Adding progress feedback to `doctor`.

## Approaches Considered

### 1. Service progress events with a Rich CLI adapter

Core services publish semantic stage and count events through an optional
`ProgressReporter`. The CLI supplies a Rich-backed implementation.

This is the selected approach. It provides real counts while keeping terminal
rendering out of business logic. A no-op implementation preserves current
service use outside the CLI.

### 2. One spinner around each complete command

The CLI could wrap `ScanService.scan()` and `ReportService.generate()` with a
generic spinner. This requires less code, but it cannot say where the command is
blocked or provide `completed/total` counts.

### 3. Rich progress rendering inside services

Services could update Rich directly. This is straightforward initially, but it
couples application logic to a terminal UI, complicates tests, and makes the
services less reusable.

## Architecture

### Progress contract

Introduce a Rich-independent progress module containing:

- A fixed set of stage identifiers.
- A `ProgressReporter` protocol.
- A `NullProgressReporter`.

The protocol exposes these operations:

```python
start(stage, total=None)
advance(completed)
finish()
```

`start` replaces the currently displayed stage. `advance` reports the absolute
number of completed items for the current stage. Absolute values are preferred
to incremental deltas so retries and skipped work cannot accidentally
double-count. `finish` ends the live display and is safe to call when no stage
is active.

Services accept the reporter as an optional dependency and use the no-op
implementation when it is absent. Domain and service modules do not import
Rich or perform terminal detection.

### Rich adapter

The CLI layer provides a Rich-backed reporter, owned by `ConsoleReporter`. It:

- Maps stage identifiers to stable user-facing text.
- Renders one spinner and an optional `completed/total` counter.
- Writes live progress to stderr.
- Uses a transient display so the progress line is removed when work finishes.
- Refreshes animation independently while synchronous subprocess or HTTP calls
  block the main thread.
- Cleans up the live display and restores the cursor on success, exception, or
  keyboard interrupt.

The CLI creates one reporter per command. `ReportService` and its nested
`ScanService` share that instance so stage changes replace the same live line.

Interactive progress is enabled by default. `--quiet` selects the no-op
reporter. No new command-line option is added.

## Stages and Data Flow

### `scan`

1. `discovering_sessions`
   - Starts before the OpenCode database query.
   - Has no total, so only the spinner and stage label are displayed.
2. `exporting_sessions`
   - Starts after discovery with `total=len(descriptors)`.
   - Advances after every descriptor is handled, whether the session loads,
     fails to export, is filtered out of the period, or resolves successfully.
3. The progress display finishes and is removed.
4. The existing scan table is printed.

Example display:

```text
⠋ Finding sessions
⠙ Exporting sessions 8/20
```

### `report`

`report` first runs the same scan stages, then continues with:

1. `preparing_evidence`
   - Total is the number of repositories returned by the scan.
   - Advances after evidence for each repository is prepared.
2. `summarizing_repositories`
   - Uses the same repository total.
   - Advances after each repository receives either its requested summary or a
     deterministic fallback.
   - An LLM retry remains on the same completed count while the spinner
     continues to animate.
3. `collecting_usage`
   - Has no total.
   - Usage collection failure follows the existing warning behavior.
4. `rendering_report`
   - Has no total.
5. `writing_report`
   - Runs only when `dry_run` is false.
   - Has no total.
6. The progress display finishes and is removed.
7. The command prints its existing Markdown, output path, and optional warnings.

Example display:

```text
⠋ Finding sessions
⠙ Exporting sessions 8/20
⠹ Preparing repository evidence 2/4
⠸ Summarizing repositories 2/4
⠼ Collecting usage statistics
⠴ Rendering report
⠦ Writing report
```

## Output Modes

- Default: show transient progress, followed by existing final output.
- `--verbose`: show the same progress and retain existing post-completion
  warnings.
- `--quiet`: show no progress and retain current quiet final output.
- `--dry-run`: write Markdown to stdout and progress to stderr so the two
  streams never mix.

Progress messages contain only generic stage names and counts. They do not
include session IDs, titles, paths, repository names, warning details, or API
error details.

## Error and Cancellation Handling

The CLI owns the reporter lifecycle through a context manager or equivalent
`try/finally` boundary around service execution. Every exit path calls
`finish()` before existing success or error output is produced.

- A recoverable per-session export failure advances the processed count and is
  retained as an existing warning.
- An LLM failure advances after fallback summarization completes.
- A usage-statistics failure finishes that stage and remains an existing
  warning.
- An unrecoverable exception removes the live line before the existing error
  handler prints.
- Ctrl-C removes the live line and restores terminal state before interruption
  propagates through Typer's normal handling.
- No success marker is rendered for an interrupted or failed command.

## Component Changes

- Add the progress contract, stage identifiers, and no-op reporter in a focused
  module under `agent_worklog`.
- Extend `ConsoleReporter` with the Rich-backed live-progress lifecycle.
- Pass the optional reporter through the CLI service builders.
- Emit discovery and per-descriptor progress from `ScanService`.
- Emit per-repository and finalization progress from `ReportService`.
- Update English and Traditional Chinese CLI documentation to describe the
  interactive progress behavior and `--quiet` suppression.

No report model, template, configuration file, or persisted output format
changes are required.

## Testing

### Service tests

- Assert the `ScanService` stage sequence and exact absolute counts.
- Assert every discovered descriptor advances the count, including export
  failure and period-filtered sessions.
- Assert the `ReportService` stage sequence and repository totals.
- Assert summary counts advance only after success or completed fallback.
- Assert dry-run omits `writing_report`.
- Assert usage failure preserves warning behavior while allowing later stages
  to run.

Tests use a recording fake `ProgressReporter`; they do not inspect Rich output.

### CLI and rendering tests

- Assert default interactive commands activate the Rich-backed reporter.
- Assert `--quiet` uses no progress reporter.
- Assert `--dry-run` keeps Markdown on stdout and progress on stderr.
- Assert the live display closes on success, expected exceptions, unexpected
  exceptions, and keyboard interruption.
- Assert the existing scan table, report path, warnings, and exit codes remain
  unchanged.

Rich-specific tests use an in-memory console with terminal behavior forced,
keeping animation assertions deterministic and independent of wall-clock
timing.

## Acceptance Criteria

1. A long-running `scan` or `report` immediately shows an animated current
   stage.
2. Session and repository stages show accurate `completed/total` values.
3. Only one transient progress line is present at any time.
4. The terminal cursor and output are normal after success, error, or Ctrl-C.
5. `--quiet` produces no progress output.
6. `--dry-run` Markdown is not contaminated by progress text.
7. Progress output reveals no session, path, repository, or error-detail data.
8. Core services have no dependency on Rich.
9. Existing final output, warnings, exit codes, and report contents do not
   change.
