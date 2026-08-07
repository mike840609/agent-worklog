# OpenCode Run Report Engine Design

**Date:** 2026-08-06
**Status:** Approved design
**Target release:** v0.7.0

## Summary

Agent Worklog currently produces a per-repository structured worklog. Its only LLM summarization path is the `OpenAICompatibleSummarizer`, which requires an external OpenAI-compatible endpoint and API key, and which is unusable with the free OpenCode models because the tool posts to `/responses` with a strict `json_schema` that free models do not reliably honor.

This change replaces the external LLM engine with the locally installed `opencode run` CLI. The `report` command builds a transcript grouped by Git repository from the already-sanitized, already-redacted session content, feeds it to `opencode run` with a fixed weekly-review prompt, and writes the resulting narrative markdown as the report. The existing structured per-repository report remains as a deterministic fallback when `opencode run` is unavailable, fails, or is explicitly skipped with `--no-llm`.

## Goals

- Generate the whole weekly narrative report (Executive Summary, Work by Project, Cross-Project Patterns, Priorities for Next Week, Usage Overview) using the locally installed `opencode run`.
- Remove the external OpenAI-compatible summarizer and all `llm.*` configuration.
- Keep `opencode run` as the only LLM engine; no API key, base URL, or provider configuration is required.
- Repurpose `--no-llm` to mean "skip `opencode run` and produce the structured fallback report directly".
- Keep the existing structured per-repository report as a warning-labeled fallback when `opencode run` fails or is unavailable.
- Reuse existing session discovery, repository grouping, sanitize/redaction, usage statistics, secure file writes, and `--dry-run`.
- Keep the earlier pipe-truncation fix: capture `opencode run` stdout through a temporary file, never through a pipe.
- Keep all existing tests passing.

## Non-goals

- Sending session content to any external API.
- Parsing or validating the narrative output (the LLM output is treated as free-form markdown; only non-empty is required).
- Producing the structured per-repository sections alongside the narrative in the same report.
- Adding a `--model` CLI flag; the model is configurable only through settings and defaults to OpenCode's configured default.
- Changing `scan`, session discovery, repository grouping, or the structured fallback path.
- Changing Claude Code or Codex session mappers.

## User-facing behavior

### Default behavior

```bash
agent-worklog report --days 7
```

This command:

- discovers and groups sessions as today;
- builds a repository-grouped transcript;
- runs `opencode run` with the weekly-review prompt;
- writes the narrative markdown (with a minimal header and warnings) as the report.

### Structured fallback, explicitly

```bash
agent-worklog report --days 7 --no-llm
```

This command skips `opencode run` entirely and produces the current structured per-repository report.

### Structured fallback, automatic

When `opencode run` is not on `PATH`, times out, exits non-zero, or produces empty output, the command emits a warning and produces the structured fallback report.

### Removed option

`--allow-remote-llm` is removed. No external LLM request can occur.

## CLI design

### `report`

- Remove `--allow-remote-llm`.
- Keep `--no-llm` with new help text:

```text
--no-llm
    Skip opencode run and produce the structured fallback report.
```

- All other options (`--sanitize/--no-sanitize`, `--root-only`, `--days/--period/--since/--until`, `--output`, `--dry-run`, `--force`, `--harness`, `--detail`, `--quiet`, `--verbose`) are unchanged.

### `scan`

Unchanged.

## Configuration

Remove `LlmSettings` (the `llm.*` block) from `AppSettings` and the CLI wiring that reads `settings.llm.*`.

Extend `OpenCodeCliSettings`:

```python
class OpenCodeCliSettings(BaseModel):
    executable: str = "opencode"
    timeout_seconds: float = 30.0
    run_timeout_seconds: float = 600.0
    sanitize: bool = False
    model: str = ""
```

Environment configuration:

```bash
AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__RUN_TIMEOUT_SECONDS=900
AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__MODEL=opencode/deepseek-v4-flash-free
```

- `run_timeout_seconds` bounds the `opencode run` subprocess (default 600 seconds). Discovery and export continue to use `timeout_seconds`.
- `model` is passed as `--model` when non-empty; empty means "use OpenCode's configured default model".

## Internal architecture

### New module: `summarizers/transcript.py`

`build_grouped_transcript(...)` builds a markdown transcript from the scan result:

- Header: period, generated timestamp, project count, session count, subagent-included flag, sanitized flag.
- One `## Project: <display_name>` section per repository, listing working directories, branches, and session titles.
- Per session: `### <session title>` followed by its user and assistant text activities (`ActivityType.USER_MESSAGE` and `ActivityType.ASSISTANT_MESSAGE`) in order.
- Tool calls are not included as transcript lines; their intent is already represented by the assistant text.
- Usage text, when available, is appended as a final `## Usage` section so only one `--file` is needed.

The transcript is built from `AgentSession.activities`, not by re-parsing raw exports.

### New module: `summarizers/opencode_run.py`

`OpenCodeRunError` — raised when `opencode run` cannot produce a narrative (missing executable, timeout, non-zero exit, or empty stdout).

`OpenCodeRunner`:

```python
def run(
    self,
    *,
    transcript_path: Path,
    prompt: str,
    period: DateRange,
) -> str:
```

Invocation:

```python
args = [
    executable, "run",
    "--title", f"Agent Worklog - {period.since:%Y-%m-%d} to {period.until:%Y-%m-%d}",
    "--file", str(transcript_path),
    "--print-logs",
]
if model:
    args += ["--model", model]
result = runner.run(args, stdout_path=output_path)
```

- The prompt is written to the subprocess stdin.
- Logs go to stderr via `--print-logs`; stdout stays clean.
- stdout is captured through a temporary file (`stdout_path`) so the pipe-truncation bug cannot recur.
- Empty or non-parseable output is not validated as markdown; only emptiness fails.
- The narrative string is returned.

### Prompt

A fixed prompt with `__DAYS__` substituted. It instructs the model to write a report with these sections, using only the attached transcript and usage statistics:

- `# Weekly OpenCode Review`
- `## Executive Summary` — 3–6 bullets across all projects
- `## Work by Project` — one `### <project>` section per transcript project, each with **Directory**, **Completed**, **Investigated**, **Technical Decisions**, **Verification**, **Remaining Work**, and **Related Sessions**
- `## Cross-Project Patterns`
- `## Priorities for Next Week`
- `## Usage Overview`

Rules: use the transcript's project headings verbatim; treat listed directories as worktrees of that project; keep projects separate; do not invent completed work; distinguish completed/investigated/decided/verified; mention concrete files, components, and commands when available. This matches the weekly-review script's prompt so results stay comparable.

### `ReportService` changes

`ReportService` gains a narrative branch in `generate()`:

```python
if narrative and not no_llm:
    try:
        transcript = build_grouped_transcript(...)
        narrative = opencode_runner.run(
            transcript_path=...,
            prompt=...,
            period=...,
        )
        content = wrap_narrative(header, narrative, warnings)
    except OpenCodeRunError as exc:
        warnings.append(f"opencode run unavailable; used structured fallback ({exc})")
        content = self._structured_content(scan, warnings)
else:
    content = self._structured_content(scan, warnings)
```

`_structured_content()` is the existing evidence → `RuleBasedSummarizer` → `MarkdownRenderer` path, extracted unchanged into a helper.

### Narrative wrapper

A small renderer (`render_narrative`) produces:

```text
# Engineering Worklog
**Period:** ...
**Generated:** ...

<narrative from opencode run>

## Warnings
- ...
```

Warnings are appended; the narrative body is not modified. The wrapper output passes through the existing `redact_text()` chain.

### Data flow

```text
opencode export (sanitized per settings)
      ↓
AgentSession activities
      ↓
build_grouped_transcript
      ↓
opencode run --file transcript --print-logs  (stdout via temp file)
      ↓
narrative markdown
      ↓
wrap_narrative(header + narrative + warnings) → redact_text → atomic_secure_write
```

## Error handling

- `opencode` missing from `PATH` → `OpenCodeRunError` → structured fallback + warning.
- `opencode run` exits non-zero → `OpenCodeRunError` → structured fallback + warning.
- `opencode run` times out → `OpenCodeRunError` → structured fallback + warning.
- Empty stdout → `OpenCodeRunError` → structured fallback + warning.
- Usage collection failure → existing warning; does not block the narrative run.
- `--dry-run` and `--force` behave as today; the narrative run still executes because it is the content source.

## Security

- The transcript is built only from already-sanitized/redacted `AgentSession` content and passes through `redact_text()`.
- Transcript and stdout temp files live in a `tempfile.TemporaryDirectory` and are removed after use.
- `opencode run` output is treated as untrusted free-form text and is wrapped, not interpreted.
- No session content is ever sent to an external service.

## Testing strategy

### Transcript unit tests

- Repositories are grouped by display name.
- Only user and assistant text activities appear, in order.
- Tool calls are excluded.
- Branches and directories are listed per repository.
- Usage text is appended when present.

### OpenCodeRunner unit tests

- Args include `run`, `--title`, `--file <transcript>`, `--print-logs`, and `stdout_path`.
- A configured model adds `--model <model>`.
- Non-zero exit raises `OpenCodeRunError`.
- Empty stdout raises `OpenCodeRunError`.
- Timeout raises `OpenCodeRunError`.
- Prompt is written to stdin.

### CLI unit tests

- `report --no-llm` does not invoke `opencode run`.
- The narrative path invokes `opencode run` once with the transcript.
- On `OpenCodeRunError`, the structured report is produced and a warning is present.
- `--allow-remote-llm` is gone; `llm.*` configuration is gone.
- `--detail` still applies to the structured fallback.

### Integration tests

- Fake runner returns narrative markdown → report contains header + narrative, and `opencode run` was called with `--file` and `stdout_path`.
- Fake runner returns non-zero → structured report with warning.
- Existing structured-path integration tests are unchanged and continue to pass.

## Documentation changes

Update:

- `README.md`;
- `README.zh-TW.md`;
- the guides covering LLM behavior;
- CLI `--help` text;
- release notes or changelog.

Document these primary examples:

```bash
# Full narrative weekly report via local opencode run (no API key)
agent-worklog report --days 7

# Structured fallback report without opencode run
agent-worklog report --days 7 --no-llm
```

Document that the narrative report is generated by the locally installed `opencode` model and that `--sanitize` still limits the evidence available to it.

## Compatibility and release

Release as **v0.7.0**: the `report` output default changes from structured per-repository to a narrative weekly review, and `--allow-remote-llm` is removed.

## Acceptance criteria

- `agent-worklog report --days 7` produces a narrative weekly report from `opencode run` with no external API key.
- `agent-worklog report --days 7 --no-llm` produces the structured fallback report and never invokes `opencode run`.
- When `opencode run` fails, the structured fallback report is produced with a warning.
- `OpenCodeCliSettings.run_timeout_seconds` and `OpenCodeCliSettings.model` are configurable via environment.
- `llm.*` configuration and `--allow-remote-llm` are removed.
- `opencode run` stdout is captured through a temporary file, never a pipe.
- The complete unit and integration test suites pass.
- English and Traditional Chinese documentation describes the new default and the removed option.
- The release is versioned as v0.7.0.
