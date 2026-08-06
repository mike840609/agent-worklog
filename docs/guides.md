# Usage guides

Deep dives for the topics the README only summarizes. For the command options
and the three rule set, see the README's [Command reference](../README.md#command-reference).

## Reporting periods

The `last-week` period means the previous full calendar week in the configured time
zone. It starts on Monday at 00:00 and ends just before the next Monday at 00:00.

```bash
agent-worklog report --period last-week
```

Use `--days` to report activity from a number of recent days:

```bash
agent-worklog report --days 7
```

Use ISO timestamps to set exact start and end times:

```bash
agent-worklog report \
  --since 2026-07-20T00:00:00+08:00 \
  --until 2026-07-27T00:00:00+08:00
```

You must provide one of `--period`, `--days`, or `--since`. If you use `--until`, you
must also use `--since`.

## Subagent sessions

Subagent sessions are included by default. Each one is linked to the repository it actually
ran in, so a subagent that worked in another checkout appears under that repository. To
report only root sessions:

```bash
agent-worklog report --period last-week --root-only
```

Both `scan` and `report` accept `--root-only`.

## Repository grouping

Agent Worklog checks each session separately to decide which repository it belongs to.
It uses the following information in order:

1. The Git `origin` remote.
2. An ID created from a hash of the shared Git directory.
3. The harness project ID — OpenCode's project ID, or the per-project directory name
   Claude Code stores transcripts under.
4. An ID created from a hash of the working directory.
5. A separate unknown ID for the session.

SSH and HTTPS addresses for the same repository are treated as the same repository.
Different branches are also grouped together. If a child session works in another
repository, it stays linked to that repository.

## LLM summaries

LLM summaries are optional. Agent Worklog connects to an OpenAI-compatible service only
when all of the following are true:

- LLM support is turned on.
- `--no-llm` is not used.
- The API key is set in the selected environment variable.

For the default OpenAI-compatible configuration:

```bash
export OPENAI_API_KEY="..."
agent-worklog report --period last-week
```

LLM requests contain selected work information rather than full transcripts. Agent
Worklog checks session information for common secret patterns before building each
request. The request may still include repository and branch names, session and activity
IDs, goals, commands, and filenames.

If the service times out, returns an HTTP 429 or 5xx error, or returns invalid data,
Agent Worklog tries once more. If the second request fails, it creates a summary without
the LLM. Use `--no-llm` to keep report generation on your computer.

## Output and file handling

Set the output file with `--output`:

```bash
agent-worklog report \
  --period last-week \
  --no-llm \
  --output weekly.md
```

Agent Worklog does not replace an existing file unless you use `--force`:

```bash
agent-worklog report --period last-week --output weekly.md --force
```

Use `--dry-run` to preview the Markdown without writing a file:

```bash
agent-worklog report --period last-week --no-llm --dry-run
```

Use `--verbose` to show export and LLM fallback warnings. Use `--quiet` to show only the
output path after a successful report.

## OpenCode privacy modes

`agent-worklog report --days 7` uses raw OpenCode export and local rule-based
summarization. Add `--sanitize` to ask OpenCode to redact the export; the report
then retains repository and session metadata but most work details are unavailable.
Add `--allow-remote-llm` only when extracted evidence may be sent to the configured
OpenAI-compatible endpoint. `--no-llm` and `--allow-remote-llm` cannot be combined.
