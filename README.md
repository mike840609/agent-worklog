# Agent Worklog

[![CI](https://github.com/mike840609/agent-worklog/actions/workflows/ci.yml/badge.svg)](https://github.com/mike840609/agent-worklog/actions/workflows/ci.yml)
[![Release](https://github.com/mike840609/agent-worklog/actions/workflows/release.yml/badge.svg)](https://github.com/mike840609/agent-worklog/actions/workflows/release.yml)
[![PyPI](https://img.shields.io/pypi/v/agent-worklog.svg)](https://pypi.org/project/agent-worklog/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://pypi.org/project/agent-worklog/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/mike840609/agent-worklog/blob/main/LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/mike840609/agent-worklog/pulls)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/mike840609/agent-worklog)

English | [繁體中文](https://github.com/mike840609/agent-worklog/blob/main/README.zh-TW.md)

Agent Worklog turns coding-agent sessions into weekly reports for managers, saving
engineers time.

![Agent sessions are grouped into weekly engineering reports](https://github.com/mike840609/agent-worklog/raw/refs/heads/main/docs/assets/agent-worklog-overview.png)

## Capabilities

Agent Worklog works with OpenCode and Claude Code and can:

- Find OpenCode sessions across all projects, no matter which folder you are in.
- Read Claude Code sessions straight from `~/.claude/projects`, including subagent
  transcripts.
- Select sessions from recent days, a calendar week, or a specific date range.
- For OpenCode: export sessions with `opencode export --sanitize`. Claude Code has no
  export command, so this step has no equivalent there.
- Group Git worktrees that belong to the same repository.
- Keep child sessions linked to the correct repository.
- Leave out subagent sessions with `--root-only` when you only want root sessions.
- List each repository's session titles and working folders in the report.
- Summarize models, tokens, and tools from `opencode stats`.
- Include source activity IDs and confidence levels as supporting information.
- Check session information for common secret patterns before creating a report or
  sending data to an optional LLM.
- Continue when one session cannot be exported and add a warning to the report.
- On POSIX systems, write reports with owner-only `0600` permissions.

## Requirements

For `--harness opencode` (the default):

- Python 3.11 or newer
- OpenCode available as `opencode`
- An OpenCode version that provides `opencode db` and `opencode export --sanitize`
- Git available as `git`

For `--harness claude-code`:

- Python 3.11 or newer
- Git available as `git`
- A readable `~/.claude/projects` directory (or the directory configured with
  `AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY`)

No Claude Code CLI is required; Agent Worklog reads the session transcripts directly.

`opencode stats` is optional. Without it, Agent Worklog leaves out the usage section and
still creates the report.

## Installation

The recommended way to install the command-line tool is with `pipx`:

```bash
pipx install agent-worklog
```

You can also install it in a regular Python environment:

```bash
pip install agent-worklog
```

For development:

```bash
git clone https://github.com/mike840609/agent-worklog.git
cd agent-worklog
uv sync --locked --extra dev
```

## Getting started

Check that OpenCode and Git are available:

```bash
agent-worklog doctor
```

Preview how Agent Worklog groups repositories for the previous full week:

```bash
agent-worklog scan --period last-week
```

Create the Markdown report without using an external LLM:

```bash
agent-worklog report --period last-week --no-llm
```

The default output is written under `reports/`.

## Command reference

| Command | What it does |
|---|---|
| `doctor` | Checks that the selected harness and `git` are ready to use. |
| `scan` | Shows which sessions fall in a period and how they group into repositories. |
| `report` | Writes the Markdown report for a period. |

`scan` and `report` share these options:

| Option | What it does |
|---|---|
| `--days N` | Reports the last N days, ending now. |
| `--period last-week` | Reports the previous full calendar week. `last-week` is the only accepted value. |
| `--since ISO` | Starts the period at an exact time. |
| `--until ISO` | Ends the period at an exact time. Requires `--since`. |
| `--harness NAME` | Harness to read sessions from: `opencode` (default) or `claude-code`. |
| `--root-only` | Leaves out subagent sessions. |
| `--verbose` | Also shows export, fallback, and LLM warnings. |
| `--quiet` | Shows only the session count for `scan`, or the output path for `report`. |

`report` also accepts:

| Option | What it does |
|---|---|
| `--output PATH` | Writes to this file instead of the default folder. |
| `--force` | Replaces the output file if it already exists. |
| `--dry-run` | Prints the Markdown instead of writing a file. |
| `--no-llm` | Creates the summary without an external LLM. |

`doctor` also accepts `--harness NAME` and `--quiet`. `--quiet` hides the list of checks
and reports only through the exit code. With `--harness claude-code`, `doctor` checks that
the configured `~/.claude/projects` directory exists and is readable, instead of checking
for the `opencode` executable and database.

Three rules apply to `scan` and `report`:

- Give exactly one of `--days`, `--period`, or `--since`.
- Use `--until` only together with `--since`.
- Do not use `--verbose` and `--quiet` together.

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
3. The OpenCode project ID.
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

## Usage statistics

With `--harness opencode`, each report includes a usage section built from `opencode
stats`, covering models, tokens, and tools. OpenCode reports usage only for a period that
ends now. The period shown in the report therefore starts when the report period starts
and runs to the time the report is created. It covers the report period but is wider than
it. If `opencode stats` is not available, Agent Worklog leaves the section out and adds a
warning to the report.

With `--harness claude-code`, the usage section is built from token counters recorded in
the sessions themselves, so it covers the report period instead of a window that ends when
the report is created; the "wider than the period" caveat above does not apply. It counts
every model turn in the period, including turns that produced only internal reasoning,
whose tokens are carried by the neighbouring recorded activity. That last part is also its
one imprecision: a turn sitting exactly on the period boundary can be counted on the other
side of it.

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

## Configuration

Agent Worklog uses environment variables for its settings. Variable names start with
`AGENT_WORKLOG_`. Use `__` between parts of a setting name. For example:

```bash
export AGENT_WORKLOG_REPORT__TIMEZONE="Asia/Taipei"
export AGENT_WORKLOG_REPORT__OUTPUT_DIRECTORY="reports"
export AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__EXECUTABLE="opencode"
export AGENT_WORKLOG_LLM__MODEL="gpt-5-mini"
export AGENT_WORKLOG_LLM__BASE_URL="https://api.openai.com/v1/"
export AGENT_WORKLOG_LLM__ENABLED="false"
```

See the
[configuration guide](https://github.com/mike840609/agent-worklog/blob/main/docs/configuration.md)
for a complete list of settings.

## Privacy

Agent Worklog requests OpenCode exports with `--sanitize`. Claude Code has no export
command, so with `--harness claude-code` Agent Worklog reads `~/.claude/projects`
transcripts directly and relies on the mapper keeping only prompts, assistant text, tool
names, and one command or path per tool call when the call has one. A call with neither —
WebFetch's `url`, WebSearch's `query`, TodoWrite's `todos` list, and MCP tool calls in
general — has its whole input serialized to JSON and truncated to 200 characters instead.
Raw tool `stdout`/`stderr`, thinking blocks, and hook output are dropped before anything
reaches a report or an LLM request.

For both harnesses, every piece of supporting information that reaches a report is then
capped at 300 characters and marked with a `…` where it was cut. That is what stops a long
command — a heredoc such as `cat > design.md <<'EOF' … EOF`, which carries the whole file
it writes inside one command string — from being copied into the report or an LLM request.
The secret-pattern checks cannot do this job: a design document or a write-up contains no
credential pattern, so only the length limit removes it.

Both harnesses also go through the common secret-pattern checks before creating a report
or making an optional LLM request. Pattern checks cannot find every possible secret.

Reports may still contain private goals, filenames, commands, work descriptions, and the
full paths of your working folders. Those paths often include your user name and the name
of a client or employer, and the secret-pattern checks leave them in place on purpose so a
report can say where the work happened. Always review a report before sharing it.

See
[Privacy and security](https://github.com/mike840609/agent-worklog/blob/main/docs/privacy.md)
for more details about data safety and current limits.

## Failure handling and exit codes

If one session cannot be exported, Agent Worklog skips it and adds a warning to the
report. If no sessions can be exported, the command stops with an error instead of
creating an empty report.

| Code | Meaning |
|---:|---|
| 0 | Success |
| 2 | Invalid command options |
| 3 | Settings error |
| 4 | No matching activity |
| 5 | Harness or Git dependency error |
| 7 | Report file error |

## Current support and limits

- OpenCode and Claude Code are the supported coding-agent tools; select one with
  `--harness`.
- For `--harness opencode`, Agent Worklog gets session data through the OpenCode
  command-line tool. It does not read the SQLite database directly.
- Markdown is the only report format.
- The usage window caveat applies to OpenCode only: `opencode stats` covers a period
  that ends when the report is created, so it is wider than the report period. Claude
  Code usage is built from the sessions themselves, so it covers the report period, to
  within a single model turn at each end of it.
- Agent Worklog does not keep a cache between runs and does not provide an `inspect`
  command.
- Older OpenCode sessions may use a backup ID if their working folders have been deleted.
- Repository grouping uses the Git information available when the report is created.
- Codex is not currently supported.
- Claude Code sessions have no exit codes, so no Claude Code report claims that a test or
  lint command passed. A verification command whose stderr was empty is listed under
  "In Progress" as `Ran verification command: <command>`, and a command that redirects its
  stderr (`2>&1`, `2>/dev/null`) produces no outcome at all, because for those commands an
  empty stderr says nothing. Verification results are reported as passing only for
  OpenCode, where a real exit code is available.
- A Claude Code session that spans several working directories is grouped under the
  last one.

## Development checks

```bash
uv sync --locked --extra dev
uv run pytest --cov=agent_worklog --cov-fail-under=80
uv run ruff check .
uv run pyright
uv build
```

See
[Releasing Agent Worklog](https://github.com/mike840609/agent-worklog/blob/main/docs/releasing.md)
for release instructions.

## License

MIT
