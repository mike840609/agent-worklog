# OpenCode Raw Export Default Design

**Date:** 2026-08-06  
**Status:** Approved design  
**Target release:** v0.6.0

## Summary

Agent Worklog currently invokes `opencode export <session-id> --sanitize` for every OpenCode session. OpenCode's sanitizer redacts the session title, working directory, conversation text, tool input, tool output, file paths, patches, and other content required to build a useful engineering worklog. The JSON remains valid, but the mapper receives placeholders instead of evidence.

This change makes raw OpenCode export the default, preserves an explicit sanitized mode, and prevents evidence from being sent to a remote LLM unless the user opts in for that invocation.

The design separates two independent decisions:

1. **How the session is read:** raw or OpenCode-sanitized.
2. **Where summarization runs:** local rule-based summarization or an explicitly authorized remote LLM.

## Goals

- Make OpenCode exports raw by default so reports retain useful work details.
- Preserve `--sanitize` as an explicit OpenCode-only privacy option.
- Support both CLI and environment-based configuration for sanitization.
- Let CLI flags override environment or application settings in both directions.
- Require explicit per-command authorization before sending extracted evidence to a remote LLM.
- Prevent OpenCode redaction placeholders from appearing as report evidence.
- Keep raw export JSON in process memory only; do not create a raw export cache or temporary file.
- Keep existing discovery, repository grouping, report rendering, and usage-statistics behavior intact.

## Non-goals

- Building a general-purpose secret scanner or regex redaction framework.
- Guaranteeing that arbitrary raw session content is safe to share externally.
- Reading OpenCode message tables directly from SQLite.
- Caching or persisting raw OpenCode exports.
- Restoring content already replaced by OpenCode's sanitizer.
- Changing Claude Code or Codex session mappers.
- Adding remote-LLM authorization to configuration or environment variables.

## User-facing behavior

### Default behavior

```bash
agent-worklog report --harness opencode --days 7
```

This command:

- runs `opencode export <session-id>` without `--sanitize`;
- extracts complete local evidence;
- uses the local `RuleBasedSummarizer`;
- does not call a remote LLM, even when an API key is available.

The same raw-export default applies to `scan` because `scan` also loads sessions.

### Sanitized OpenCode export

```bash
agent-worklog report --harness opencode --days 7 --sanitize
```

This command runs:

```bash
opencode export <session-id> --sanitize
```

OpenCode-redacted content cannot be restored. Agent Worklog retains discovery metadata where possible and omits redacted placeholders from activities and evidence.

### Explicit remote LLM authorization

```bash
agent-worklog report \
  --harness opencode \
  --days 7 \
  --allow-remote-llm
```

A remote LLM is used only when all of the following are true:

- LLM support is enabled in settings;
- the configured API-key environment variable is present;
- `--no-llm` is not specified;
- `--allow-remote-llm` is explicitly specified for this invocation.

Only extracted `RepositoryEvidence` is sent to the configured OpenAI-compatible endpoint. The complete raw export JSON is never sent directly.

### Complete local-only override

```bash
agent-worklog report --harness opencode --days 7 --no-llm
```

`--no-llm` always selects local rule-based summarization.

## CLI design

### `scan`

Add the following OpenCode-only option:

```text
--sanitize / --no-sanitize
```

The Typer parameter is tri-state:

```python
sanitize: bool | None = typer.Option(
    None,
    "--sanitize/--no-sanitize",
    help="Ask OpenCode to redact exported session content. OpenCode only.",
)
```

`None` means no CLI override was supplied.

### `report`

Add:

```text
--sanitize / --no-sanitize
--allow-remote-llm
```

`--allow-remote-llm` is report-only because `scan` does not use a summarizer.

Suggested help text:

```text
--sanitize / --no-sanitize
    Ask OpenCode to redact exported session content. Disabled by default.
    OpenCode only.

--allow-remote-llm
    Allow extracted work evidence to be sent to the configured
    OpenAI-compatible endpoint for this invocation.
```

### Invalid combinations

The CLI must fail before scanning when:

- `--sanitize` or `--no-sanitize` is used with `--harness claude-code`;
- `--sanitize` or `--no-sanitize` is used with `--harness codex`;
- `--no-llm` and `--allow-remote-llm` are supplied together.

Expected messages:

```text
Error: --sanitize and --no-sanitize are supported only with --harness opencode
```

```text
Error: --no-llm and --allow-remote-llm cannot be used together
```

A single validation helper should enforce these rules for both `scan` and `report`:

```python
def _validate_privacy_options(
    *,
    harness: Harness,
    sanitize: bool | None,
    no_llm: bool = False,
    allow_remote_llm: bool = False,
) -> None:
    ...
```

## Configuration and precedence

Add `sanitize` to `OpenCodeCliSettings`:

```python
class OpenCodeCliSettings(BaseModel):
    executable: str = "opencode"
    timeout_seconds: float = 30.0
    sanitize: bool = False
```

Environment configuration:

```bash
AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__SANITIZE=true
```

Effective value:

```python
effective_sanitize = (
    cli_sanitize
    if cli_sanitize is not None
    else settings.harnesses.opencode.cli.sanitize
)
```

Precedence is therefore:

1. CLI `--sanitize` or `--no-sanitize`;
2. environment/application settings;
3. default `False`.

There is intentionally no environment or persistent setting for `--allow-remote-llm`. Authorization must be explicit on every command that may transmit evidence.

## Internal architecture

### OpenCode source

Extend `OpenCodeCliSource` with one resolved constructor dependency:

```python
class OpenCodeCliSource(HarnessSessionSource):
    def __init__(
        self,
        *,
        runner: Runner,
        executable: str = "opencode",
        root_only: bool = False,
        sanitize: bool = False,
    ) -> None:
        self._runner = runner
        self._executable = executable
        self._root_only = root_only
        self._sanitize = sanitize
```

`load()` builds the export command conditionally:

```python
args = [self._executable, "export", descriptor.session_id]
if self._sanitize:
    args.append("--sanitize")
result = self._runner.run(args)
```

The source remains independent of global settings. The CLI resolves configuration and passes the effective value into the source.

### Data flow

```text
opencode export
      ↓
CommandResult.stdout
      ↓
json.loads()
      ↓
OpenCodeExportMapper
      ↓
AgentSession
      ↓
Evidence extraction
      ↓
RuleBasedSummarizer by default
      ↓
Optional remote summarizer only with explicit authorization
      ↓
Markdown report
```

### Raw-data handling requirements

- Raw JSON exists only in subprocess stdout and Python memory.
- Raw JSON is not written to a temporary file or cache.
- Raw stdout is not included in debug or verbose logs.
- Parse errors identify the affected session but do not echo raw stdout.
- Existing report-file permission protections remain unchanged.
- Documentation must warn that `--dry-run` prints report content to the terminal and may therefore enter terminal, CI, or redirected logs.

## Sanitized placeholder handling

OpenCode replaces content with strings beginning with `[redacted:`. These strings are syntactically valid but must not be treated as meaningful evidence.

Add a focused helper in the OpenCode mapper:

```python
def _is_redacted_placeholder(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.strip().startswith("[redacted:")
    )
```

### Metadata fallback

For redacted title and directory fields, use the `SessionDescriptor` values collected from `opencode db`:

```python
title = usable_export_value(export_title) or descriptor.title
directory = (
    usable_export_value(export_directory)
    or descriptor.working_directory_hint
)
```

The discovery descriptor remains authoritative fallback data for:

- title;
- working directory;
- project ID;
- parent session ID;
- created and updated timestamps.

### Activity filtering

Do not create activities from redacted message or tool content:

```text
[redacted:text:...]
[redacted:tool-input:...]
[redacted:tool-output:...]
```

A sanitized report may still contain repository grouping, session metadata, counts, time range, and usage statistics, but it must not render placeholders or claim work details that are no longer available.

## Remote LLM decision

Centralize remote-summarizer selection in a pure decision function or equivalently isolated helper:

```python
def _remote_llm_enabled(
    *,
    settings: AppSettings,
    api_key: str | None,
    no_llm: bool,
    allow_remote_llm: bool,
) -> bool:
    return bool(
        settings.llm.enabled
        and api_key
        and not no_llm
        and allow_remote_llm
    )
```

This authorization rule applies to all report harnesses. The new flag controls external transmission; `--sanitize` remains OpenCode-specific.

Behavior matrix:

| Export/session source | Default | `--allow-remote-llm` | `--no-llm` |
|---|---|---|---|
| OpenCode raw | local rule-based | remote when configured | local rule-based |
| OpenCode sanitized | local rule-based | remote when configured | local rule-based |
| Claude Code | local rule-based | remote when configured | local rule-based |
| Codex | local rule-based | remote when configured | local rule-based |

When `--allow-remote-llm` is specified but the API key is missing or LLM support is disabled, the command continues with the local summarizer and adds a warning explaining why remote summarization was unavailable.

## Error handling

The existing source-error behavior remains unchanged:

- non-zero `opencode db` exits raise `HarnessSourceError`;
- non-zero `opencode export` exits raise `SessionParseError`;
- invalid export JSON raises `SessionParseError`;
- raw stdout is never copied into these errors.

Sanitized placeholders are not parse errors. They are expected unavailable values and are handled through metadata fallback or activity omission.

## Testing strategy

Use the existing unit and integration test structure.

### Configuration tests

- `OpenCodeCliSettings.sanitize` defaults to `False`.
- The nested environment variable can set `sanitize=True`.
- Invalid boolean configuration produces a configuration error.

### OpenCode source tests

- The default export command is exactly `opencode export <session-id>`.
- `sanitize=True` appends `--sanitize`.
- The discovery command is unchanged.
- Invalid JSON behavior is unchanged.
- Error messages do not contain raw stdout.

### Mapper tests

- Raw title, directory, user text, and tool command are retained.
- A redacted title falls back to `descriptor.title`.
- A redacted directory falls back to `descriptor.working_directory_hint`.
- Redacted text does not produce a message activity.
- Redacted tool content does not produce meaningful command/file evidence.
- Sanitized placeholders never appear in extracted report evidence.

### CLI unit tests

- `scan --harness opencode --sanitize` passes `sanitize=True` to the source.
- `report --harness opencode --no-sanitize` overrides an environment setting of `true`.
- `--sanitize` with Claude Code fails before scanning.
- `--sanitize` with Codex fails before scanning.
- `--no-llm --allow-remote-llm` fails before scanning.
- Without `--allow-remote-llm`, a configured API key does not create the remote summarizer.
- With the flag, enabled settings, and an API key, the remote summarizer is created.
- With the flag but no API key, the local summarizer is used and a warning is emitted.
- With the flag but disabled LLM settings, the local summarizer is used and a warning is emitted.

### Integration tests

#### Raw default

Expected OpenCode calls:

```text
opencode db ...
opencode export ses_xxx
```

Assertions:

- useful work details appear in the report;
- repository grouping remains correct;
- no external HTTP request occurs by default.

#### Sanitized mode

Expected OpenCode calls:

```text
opencode db ...
opencode export ses_xxx --sanitize
```

Assertions:

- discovery metadata is retained;
- `[redacted:...]` does not appear in the report;
- no unsupported completed work, command, or file evidence is generated.

#### Remote opt-in

```bash
agent-worklog report --harness opencode --allow-remote-llm ...
```

Assertions:

- the OpenAI-compatible client is called only when its API key and settings are available;
- the request contains extracted evidence, not complete export JSON.

## Documentation changes

Update:

- `README.md`;
- `README.zh-TW.md`;
- the detailed guides covering LLM and privacy behavior;
- OpenCode limitations documentation;
- CLI `--help` text;
- release notes or changelog.

Document these primary examples:

```bash
# Complete local report; raw OpenCode export; no remote LLM
agent-worklog report --days 7

# Ask OpenCode to redact export content
agent-worklog report --days 7 --sanitize

# Explicitly authorize remote summarization for this invocation
agent-worklog report --days 7 --allow-remote-llm
```

The documentation must explain that OpenCode sanitization removes most evidence and therefore produces a deliberately limited report.

## Compatibility and release

Release this behavior as **v0.6.0** rather than a patch release because two observable defaults change:

1. OpenCode export changes from sanitized to raw.
2. Remote LLM summarization changes from API-key-triggered to explicit CLI opt-in.

Existing commands remain syntactically valid, but their privacy and summarization behavior changes. Release notes must call out both changes prominently.

## Acceptance criteria

The feature is complete when all of the following are true:

- OpenCode exports are raw by default.
- `--sanitize/--no-sanitize` is available to `scan` and `report` for OpenCode.
- The nested OpenCode environment setting can enable sanitization.
- CLI flags override the setting in both directions.
- Sanitization flags fail explicitly for Claude Code and Codex.
- Remote LLM use requires `--allow-remote-llm` for every report invocation.
- `--no-llm` and `--allow-remote-llm` cannot be combined.
- Sanitized placeholders do not enter activities, evidence, or rendered reports.
- Sanitized metadata falls back to discovery metadata where available.
- Raw export JSON is not persisted or logged.
- The complete unit and integration test suites pass.
- English and Traditional Chinese documentation describes the new defaults and risks.
- The release is versioned as v0.6.0.
