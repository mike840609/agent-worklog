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

Agent Worklog supports OpenCode, Claude Code, and Codex. Across supported coding-agent
harnesses, it can:

- Find coding-agent sessions across all projects, no matter which folder you are in.
- Select sessions from recent days, a calendar week, or a specific date range.
- Group Git worktrees that belong to the same repository.
- Keep child and subagent sessions linked to the correct repository, or leave them out
  with `--root-only`.
- List each repository's session titles and working folders in the report.
- Summarize model and token usage when the selected harness provides it.
- Include source activity IDs and confidence levels as supporting information.
- Check session information for common secret patterns before creating a report or
  sending data to an optional LLM.
- Continue when one session cannot be read and add a warning to the report.
- On POSIX systems, write reports with owner-only `0600` permissions.

## Requirements

- Python 3.11 or newer.
- Git available as `git`.
- One coding-agent harness: OpenCode (default), Claude Code, or Codex. OpenCode needs an
  `opencode` executable that provides `opencode db` and `opencode export --sanitize`;
  Claude Code and Codex need no CLI, only a readable transcript store
  (`~/.claude/projects` or `~/.codex`).

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

Check that the selected harness and Git are available:

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

Those three commands default to `--harness opencode`. For Claude Code or Codex, add
`--harness claude-code` or `--harness codex` to each — no OpenCode installation is
needed:

```bash
agent-worklog doctor --harness claude-code
agent-worklog report --harness claude-code --period last-week --no-llm
agent-worklog doctor --harness codex
agent-worklog report --harness codex --period last-week --no-llm
```

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
| `--harness NAME` | Harness to read sessions from: `opencode` (default), `claude-code`, or `codex`. |
| `--root-only` | Leaves out child and subagent sessions. |
| `--verbose` | Also shows export, fallback, and LLM warnings. For `scan`, also lists each repository's session titles and working folders. |
| `--quiet` | Shows only the session count for `scan`, or the output path for `report`. |

While `scan` and `report` are working, they show a transient progress status with the
current stage. Session and repository stages also show a `completed/total` count.
`--quiet` hides the progress status. For `report --dry-run`, progress is written to
stderr so stdout contains only Markdown.

`report` also accepts:

| Option | What it does |
|---|---|
| `--output PATH` | Writes to this file instead of the default folder. |
| `--force` | Replaces the output file if it already exists. |
| `--dry-run` | Prints the Markdown instead of writing a file. |
| `--no-llm` | Creates the summary without an external LLM. |
| `--detail LEVEL` | How much detail the report contains: `full` (default) or `brief`. |

`--detail brief` produces a short report for a status update: it keeps the
header, and for each repository the `Repository:` remote line, the session
counts, and the summary and up to five each of Completed, Problems Resolved,
and In Progress. It leaves out Key Files, Directories, Sessions, Branches, and
the usage table. Warnings are always kept, at both detail levels, because they
report data the tool could not read rather than work you did.

`doctor` also accepts `--harness NAME`, `--quiet`, and `--verbose`. `--quiet` hides the
list of checks and reports only through the exit code; `--verbose` does not change what
`doctor` prints. With `--harness claude-code`, `doctor` checks that
the configured `~/.claude/projects` directory exists and is readable, instead of checking
for the `opencode` executable and database. With `--harness codex`, `doctor` checks that
the configured `~/.codex` directory exists and is readable, and reports which discovery
path it will take: the state database by name, or `directory scan` when none is present.

Three rules apply:

- Give exactly one of `--days`, `--period`, or `--since` (`scan` and `report`).
- Use `--until` only together with `--since` (`scan` and `report`).
- Do not use `--verbose` and `--quiet` together (all three commands).

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

Agent Worklog requests OpenCode exports with `--sanitize`, redacts common secret patterns
before any report or LLM request, and caps every piece of supporting information at 300
characters. Reports may still contain private goals, filenames, commands, and full working
paths — always review a report before sharing it.

See
[Privacy and security](https://github.com/mike840609/agent-worklog/blob/main/docs/privacy.md)
for the full details about data safety and current limits.

## Exit codes

| Code | Meaning |
|---:|---|
| 0 | Success |
| 2 | Invalid command options |
| 3 | Settings error |
| 4 | No matching activity |
| 5 | Harness or Git dependency error |
| 7 | Report file error |

If one session cannot be read, Agent Worklog skips it and adds a warning to the report. If
no sessions can be read, the command stops with an error instead of creating an empty
report.

## Support and limits

OpenCode, Claude Code, and Codex are the supported tools, selected with `--harness`.
Markdown is the only report format, and Agent Worklog keeps no cache between runs.

- [Usage guides](https://github.com/mike840609/agent-worklog/blob/main/docs/guides.md) — reporting periods, subagents, repository grouping,
  LLM summaries, output handling.
- [Usage statistics](https://github.com/mike840609/agent-worklog/blob/main/docs/usage-statistics.md) — how the usage section is built and the
  window caveat.
- [Current support and limits](https://github.com/mike840609/agent-worklog/blob/main/docs/limitations.md) — the full per-harness caveat list.

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
