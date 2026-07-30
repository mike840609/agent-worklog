# Privacy and security

Agent Worklog is local-first, but coding-agent transcripts are sensitive inputs. This
document defines what the MVP protects and what remains the operator's responsibility.

## Data flow

With `--harness opencode` (the default):

1. Agent Worklog queries candidate session metadata with `opencode db`.
2. It requests each transcript with `opencode export <session-id> --sanitize`.

With `--harness claude-code`:

1. Agent Worklog lists the JSONL transcript files under the configured
   `projects_directory` (default `~/.claude/projects`), including subagent transcripts
   unless `--root-only` is used.
2. It reads each file directly from disk. There is no harness-side export or sanitize
   step here: Claude Code provides no export command, so the raw JSONL — with whatever
   tool output, file contents, environment values, and hook output Claude Code wrote to
   it — is read into memory before the mapper described in "Claude Code has no sanitize
   step" below runs.

Both harnesses then continue:

3. Transcript data is parsed in memory and filtered to the requested activity range.
4. Structured evidence is recursively redacted.
5. `report` builds a usage section: for OpenCode, by requesting aggregate counters with
   `opencode stats` over a trailing window that contains the report period; for Claude
   Code, from token counters already attached to each mapped activity, which cover the
   report period exactly. Either way the usage output holds model, token, and tool
   totals rather than session content, and it is redacted before it reaches the report.
6. The redacted evidence is rendered locally or optionally sent to an OpenAI-compatible
   endpoint.
7. Markdown is written with an atomic replacement and owner-only `0600` permissions on
   POSIX systems.

Agent Worklog does not persist raw OpenCode exports or raw Claude Code transcripts beyond
the in-memory read above. The secure writer may create a short-lived sibling file during
atomic report replacement; it is removed after completion or failure.

## Redaction boundary

The redactor covers common patterns including:

- bearer and basic authorization values;
- OpenAI-style provider keys;
- GitHub tokens;
- AWS access keys and secret assignments;
- password, token, secret, and API-key assignments;
- credentials embedded in URLs and `curl -u` arguments;
- JWT-like tokens;
- private-key blocks.

Redaction is applied recursively to evidence metadata, to OpenCode and Claude Code usage
output, before rendering, before verbose warnings are written to reports, and before
optional LLM requests. For Claude Code, redaction runs after the mapper minimization
described below, on the fields that minimization leaves behind.

Pattern-based redaction is not a proof that every secret has been removed. New credential
formats, arbitrary customer identifiers, source code, internal hostnames, filenames,
working-directory paths, session titles, and business-sensitive descriptions may remain.

## OpenCode sanitization

Every OpenCode transcript request includes `--sanitize`. This is a defense-in-depth input
boundary, not a replacement for Agent Worklog redaction. A command fails the acceptance
suite if an OpenCode export is invoked without that flag.

## Claude Code has no sanitize step

Claude Code has no export command at all, so there is nothing equivalent to `opencode
export --sanitize` for Agent Worklog to request. With `--harness claude-code`, Agent
Worklog reads `~/.claude/projects/**/*.jsonl` directly, and those files contain full tool
output, whole file contents, environment dumps, and hook output exactly as Claude Code
wrote them to disk.

What replaces the missing sanitize step is not a scrub of that file on disk — it is that
the JSONL mapper deliberately keeps only a narrow slice of each record before anything
else in Agent Worklog sees it:

- human prompts (tool results, hook injections, and system reminders that Claude Code
  also writes as `type: "user"` records are excluded, so they are never mistaken for
  human intent);
- assistant message text;
- tool names;
- one command or file path per tool call, when the call carries one.

Not every tool call has a `command`, `file_path`, `path`, or `notebook_path` field.
WebFetch's `url`, WebSearch's `query`, Task's `description`/`prompt`/`subagent_type`,
TodoWrite's whole `todos` list, a path-less Glob call, and MCP tool calls in general all
fall outside that set. For those, the mapper falls back to serializing the tool's entire
input object to JSON and truncating it to 200 characters, so what the mapper keeps is not
one command or path but as much of the full call as fits in that budget.

Everything else is dropped at that boundary and never reaches a report or an LLM request:
tool `stdout` and `stderr`, model thinking blocks, hook output, and system reminders. The
only trace a tool result leaves behind is two derived booleans — whether its `stderr` was
empty, and whether the call was interrupted — which is also why verification results for
Claude Code are inferred rather than read from an exit code, and marked `(inferred)` in
the report.

The same pattern-based secret checks described above still run on top of that reduced set
of fields, exactly as they do for OpenCode evidence.

This is a description of a deliberate design choice about what Agent Worklog retains, not
a guarantee about what Claude Code itself writes to disk, and not a claim that the
retained fields are free of secrets — a command, file path, or a truncated serialized
tool input can itself contain a credential, and pattern checks cannot find every possible
secret. Reports built from Claude Code sessions may still contain prompts, commands, file
paths, and full working-directory paths, exactly as reports built from OpenCode sessions
do.

## The 300-character evidence budget

The mapper alone does not bound how much text a single retained field can hold. A Bash
`input.command` is kept whole, and a heredoc puts the entire body of the file it writes
inside that one command string — as far as length goes, `cat > design.md <<'EOF' … EOF` or
`gh pr create --body-file - <<'EOF' … EOF` is a file, not a command. The 200-character
truncation described above applies only to the JSON fallback, which is the rare path.

The bound that does apply to a report is in the extraction layer, and it covers both
harnesses: **every evidence item's text is capped at 300 characters**
(`EVIDENCE_TEXT_MAX_LENGTH` in `extraction/pipeline.py`), with a trailing `…` marking the
cut so a reader can tell that text was removed. 300 characters identify any real command
while refusing to carry a file, a diff, or a write-up. Nothing longer than that reaches
the rendered Markdown, the report's provenance lists, or an outbound LLM request.

Redaction cannot substitute for this cap, which is why the cap exists. A pasted design
document, an incident write-up, or a block of source code contains no credential pattern,
so `redact_text` passes it through untouched; only a length budget removes it.

One neighbouring fallback is closed for the same reason. A file tool call that carries no
path key at all would otherwise have its serialized input treated as a file path and
listed under "Key Files", which for a `Write`-shaped call means the beginning of the
file's own `content`. Text that does not look like a single path is refused instead, so
such a call contributes no "Key File" entry rather than an entry made of file contents.

## Optional LLM use

An HTTP client is constructed only when LLM support is enabled, `--no-llm` is absent, and
the configured API-key environment variable exists. The payload contains canonical,
redacted evidence rather than raw transcripts or raw metadata.

That evidence includes per-session titles and absolute working directories. They are
redacted for secrets like every other field, but redaction does not remove what a path
identifies. A directory such as `/Users/<operator>/work/<client>/service` leaves the
machine with the request, usernames and client or employer names included.

The endpoint operator may retain requests according to its own policies. Use
`--no-llm` or set `AGENT_WORKLOG_LLM__ENABLED=false` when external processing is not
permitted.

## Reports remain sensitive

A generated report can still reveal proprietary information, including:

- project and repository names;
- user goals and feature descriptions;
- commands and test names;
- filenames and branch names;
- absolute working-directory paths, printed verbatim per repository;
- session titles, which are free text written during the session;
- aggregate model, token, and tool usage counters;
- errors and unresolved work;
- the fact that particular repositories were active.

Working-directory paths deserve separate attention. Redaction targets credential patterns
and deliberately leaves paths intact, so a report can state where work happened. On a
typical machine those paths carry the operator's username and often a client or employer
name, for example `/Users/<operator>/work/<client>/service`.

Treat reports as internal engineering records. Review them before posting to chat systems,
issue trackers, shared drives, or public repositories.

## Logs and partial failures

The CLI does not intentionally print raw transcripts, environment values, authorization
headers, or credentials embedded in remotes. Partial export or transcript-read failures
are reported using session IDs and redacted error text.

## Operator responsibilities

- Keep the OpenCode storage (or, for Claude Code, `~/.claude/projects`) and generated
  reports protected by appropriate filesystem permissions.
- Do not enable an external LLM endpoint unless company policy permits it.
- Review generated content before distribution.
- Rotate any credential that appears unredacted and report the pattern so the redactor can
  be extended.
