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

## Architecture

<!-- Rendered image, not a mermaid block: the GitHub mobile app and PyPI show
     mermaid source as plain text. Edit docs/assets/architecture.mmd and follow
     the regenerate command at the top of that file. -->

![Architecture: CLI reads one of three session sources, scans and resolves repositories, then extracts, redacts, summarizes, and writes the report](https://github.com/mike840609/agent-worklog/raw/refs/heads/main/docs/assets/architecture.svg)

Agent Worklog runs one of three sources per harness, loads only the sessions that overlap
the requested period, groups them by repository, redacts and summarizes the evidence, and
writes the Markdown report atomically with owner-only permissions.

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
- Check session information for common secret patterns before creating a report or
  invoking the local narrative `opencode run`.

## Requirements

- Python 3.11 or newer.
- Git available as `git`.
- One coding-agent harness: OpenCode (default), Claude Code, or Codex. OpenCode needs an
  `opencode` executable that provides `opencode db` and `opencode export`; the default
  narrative report also uses `opencode run`, and the usage section uses `opencode stats`.
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

Create the Markdown report; the default runs your local `opencode run` to write a
narrative weekly review:

```bash
agent-worklog report --period last-week
```

Use `--no-llm` for the deterministic structured report instead:

```bash
agent-worklog report --period last-week --no-llm
```

The default output is written under `reports/`.

Those three commands default to `--harness opencode`. For Claude Code or Codex, add
`--harness claude-code` or `--harness codex` to each. The narrative default behaves
the same for every harness: it reads that harness's sessions and still calls your
local `opencode run` to write the review. Add `--no-llm` when OpenCode is not
installed — the deterministic structured report works for every harness without it:

```bash
agent-worklog doctor --harness claude-code
agent-worklog report --harness claude-code --period last-week
agent-worklog report --harness claude-code --period last-week --no-llm
agent-worklog doctor --harness codex
agent-worklog report --harness codex --period last-week
agent-worklog report --harness codex --period last-week --no-llm
```

Prefer a guided walk-through instead of flags? `run` asks the same questions one at a
time — which harness, which period, how much detail — then previews the scan for your
approval before writing the report:

```bash
agent-worklog run
```

`run` and `config init` need an interactive terminal, so they refuse to run when stdin
is not a terminal; the `scan` and `report` commands cover the non-interactive route.

## Command reference

| Command | What it does |
|---|---|---|
| `doctor` | Checks that the selected harness and `git` are ready to use. |
| `scan` | Shows which sessions fall in a period and how they group into repositories. |
| `report` | Writes the Markdown report for a period. |
| `run` | Walks you through the wizard: pick a harness and period, preview the scan, then write the report. |
| `config` | Shows and edits the settings file: `path`, `list`, `init`, `set`, `unset`. |

`scan` and `report` share these options:

| Option | What it does |
|---|---|
| `--days N` | Reports the last N days, ending now. |
| `--period last-week` | Reports the previous full calendar week. `last-week` is the only accepted value. |
| `--since ISO` | Starts the period at an exact time. |
| `--until ISO` | Ends the period at an exact time. Requires `--since`. |
| `--harness NAME` | Harness to read sessions from: `opencode` (default), `claude-code`, or `codex`. |
| `--root-only` | Leaves out child and subagent sessions. |
| `--sanitize / --no-sanitize` | Enables or disables OpenCode export redaction. Raw export is the default. OpenCode only. |
| `--verbose` | Also shows export, fallback, and narrative warnings. For `scan`, also lists each repository's session titles and working folders. |
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
| `--no-llm` | Skips the local `opencode run` narrative and emits the deterministic structured report. |
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

Agent Worklog reads every setting from an environment variable, and reads a settings
file for the ones the environment does not set. For each setting it takes the
environment variable, then the settings file, then the default.

To set everything up at once, `config init` walks through every setting, showing the
value in force in brackets. Press Enter to keep it:

```
$ agent-worklog config init
Press Enter to keep the value in brackets. Every setting is optional.
report.timezone [Asia/Taipei]:
llm.model [gpt-5-mini]: gpt-5
Wrote 1 setting to /home/dev/.config/agent-worklog/config.env
```

Or set a value once, in the settings file:

```bash
agent-worklog config set opencode.cli.model deepseek-r1
agent-worklog config set report.timezone Europe/Berlin
agent-worklog config set llm.model            # leave the value out to be asked for it
agent-worklog config list
```

`config list` shows every setting with its current value, whether that value came from
the environment, the file, or the default, and what the default is. Every setting is
optional: an empty value restores the default, and so does `unset`.

```bash
agent-worklog config set opencode.cli.model ""
agent-worklog config unset report.timezone
```

`agent-worklog config path` prints the file location. Set `AGENT_WORKLOG_CONFIG_FILE`
to use a different file.

Variable names start with `AGENT_WORKLOG_`, with `__` between parts of a setting name.
An exported variable overrides the file for that shell:

```bash
export AGENT_WORKLOG_REPORT__TIMEZONE="Asia/Taipei"
export AGENT_WORKLOG_REPORT__OUTPUT_DIRECTORY="reports"
export AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__EXECUTABLE="opencode"
export AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__SANITIZE="false"
export AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__RUN_TIMEOUT_SECONDS="600.0"
export AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__MODEL=""
```

See the
[configuration guide](https://github.com/mike840609/agent-worklog/blob/main/docs/configuration.md)
for a complete list of settings.

## Privacy

OpenCode exports are raw by default so reports retain useful work details. Agent Worklog
redacts common secret patterns locally. The default report hands a grouped, redacted raw
transcript to the locally installed `opencode run`, which writes the narrative; nothing
leaves your machine and no API key is needed. Use `--no-llm` for the deterministic
structured report. Use `--sanitize` for OpenCode's stronger redaction, which
intentionally removes most work evidence. Reports may still contain private goals,
filenames, commands, and full working paths — always review a report before sharing it.

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
  narrative and structured reports, output handling.
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
