# Configuration

Agent Worklog reads every setting from an environment variable, and reads a settings
file for the ones the environment does not set. For each setting it takes the
environment variable, then the settings file, then the default.

- Prefix: `AGENT_WORKLOG_`
- Nested delimiter: `__`
- Boolean values: `true` or `false`

Every setting is optional. Leaving one out — or setting it to an empty value — uses
the default listed in the tables below.

## The settings file

`agent-worklog config` reads and writes a settings file so that a value survives the
shell it was set in:

```bash
agent-worklog config path                        # where the file is
agent-worklog config list                        # every setting, value, and source
agent-worklog config set llm.model gpt-5         # write one setting
agent-worklog config set llm.model ""            # empty value: back to the default
agent-worklog config unset llm.model             # same thing, spelled out
```

Keys are the lowercase, dot-separated form of the variable name, so
`AGENT_WORKLOG_LLM__MODEL` is `llm.model` and
`AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__EXECUTABLE` is
`harnesses.opencode.cli.executable`. `config list` shows both forms of every setting
with its current value, whether that value came from the environment, the file, or the
default, and what the default is.

The file is a `config.env` in the user configuration directory — run
`agent-worklog config path` to see the exact location, which differs by platform. Set
`AGENT_WORKLOG_CONFIG_FILE` to use a different file, such as one checked into a
project. The file is created readable and writable only by its owner.

An exported variable always beats the file, so `AGENT_WORKLOG_LLM__ENABLED=false
agent-worklog report --period last-week` still works with a file that enables the LLM.
`config set` says so when the setting it just wrote is already exported.

`config set` refuses an unknown key and a value the settings would reject, so a typo
fails at the moment you make it rather than on the next report. Both exit with code 3.

## OpenCode harness

| Environment variable | Default | Purpose |
|---|---|---|
| `AGENT_WORKLOG_HARNESSES__OPENCODE__ENABLED` | `true` | Set to `false` to make `--harness opencode` fail with a configuration error (exit code 3). |
| `AGENT_WORKLOG_HARNESSES__OPENCODE__SOURCE` | `cli` | Source identifier; only `cli` is implemented. |
| `AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__EXECUTABLE` | `opencode` | OpenCode executable name or path. |
| `AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__TIMEOUT_SECONDS` | `30` | Timeout for OpenCode commands. |

Example:

```bash
export AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__EXECUTABLE="$HOME/bin/opencode"
export AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__TIMEOUT_SECONDS="60"
agent-worklog doctor
```

## Claude Code harness

| Environment variable | Default | Purpose |
|---|---|---|
| `AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__ENABLED` | `true` | Set to `false` to make `--harness claude-code` fail with a configuration error (exit code 3). |
| `AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY` | `~/.claude/projects` | Directory containing per-project session transcripts. |

Selecting the harness is a CLI concern, not a settings one: pass `--harness claude-code`
to `doctor`, `scan`, or `report`. No executable or CLI timeout setting applies, because
Agent Worklog reads the JSONL transcripts under `projects_directory` directly and never
launches a Claude Code process.

`ENABLED` is a refusal, not a default: setting it to `false` does not switch the other
harness on, it makes `doctor`, `scan`, and `report` refuse the disabled one. Use it to
forbid reading a transcript store on a machine where that is not permitted.

Example:

```bash
export AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__ENABLED="true"
export AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY="$HOME/.claude/projects"
agent-worklog doctor --harness claude-code
```

## Codex harness

| Environment variable | Default | Purpose |
|---|---|---|
| `AGENT_WORKLOG_HARNESSES__CODEX__ENABLED` | `true` | Set to `false` to make `--harness codex` fail with a configuration error (exit code 3). |
| `AGENT_WORKLOG_HARNESSES__CODEX__HOME_DIRECTORY` | `~/.codex` | Directory holding the Codex state database and rollout files. |

One setting covers all three locations Agent Worklog reads — `state_<n>.sqlite`,
`sessions/`, and `archived_sessions/` are fixed positions under it.

Selecting the harness is a CLI concern, not a settings one: pass `--harness codex` to
`doctor`, `scan`, or `report`. No executable or CLI timeout setting applies, because Agent
Worklog reads the state database or the rollout JSONL files under `home_directory`
directly and never launches a Codex process.

`ENABLED` behaves exactly as it does for Claude Code: setting it to `false` does not
switch another harness on, it makes `doctor`, `scan`, and `report` refuse the disabled one.

Example:

```bash
export AGENT_WORKLOG_HARNESSES__CODEX__ENABLED="true"
export AGENT_WORKLOG_HARNESSES__CODEX__HOME_DIRECTORY="$HOME/.codex"
agent-worklog doctor --harness codex
```

## Report settings

| Environment variable | Default | Purpose |
|---|---|---|
| `AGENT_WORKLOG_REPORT__TIMEZONE` | `Asia/Taipei` | Calendar-week and naive ISO timestamp timezone. |
| `AGENT_WORKLOG_REPORT__OUTPUT_DIRECTORY` | `reports` | Default Markdown output directory. |

The `--output` CLI option overrides the configured output directory for one invocation.

## LLM settings

| Environment variable | Default | Purpose |
|---|---|---|
| `AGENT_WORKLOG_LLM__ENABLED` | `true` | Allows LLM use when a key is available. |
| `AGENT_WORKLOG_LLM__PROVIDER` | `openai-compatible` | Provider label. |
| `AGENT_WORKLOG_LLM__MODEL` | `gpt-5-mini` | Model sent to the endpoint. |
| `AGENT_WORKLOG_LLM__BASE_URL` | `https://api.openai.com/v1/` | OpenAI-compatible API base URL. |
| `AGENT_WORKLOG_LLM__API_KEY_ENV` | `OPENAI_API_KEY` | Name of the environment variable containing the key. |
| `AGENT_WORKLOG_LLM__TIMEOUT_SECONDS` | `60` | HTTP timeout per attempt. |

To use a company endpoint without placing its key in an Agent Worklog setting:

```bash
export COMPANY_LLM_API_KEY="..."
export AGENT_WORKLOG_LLM__API_KEY_ENV="COMPANY_LLM_API_KEY"
export AGENT_WORKLOG_LLM__BASE_URL="https://llm.example.com/v1/"
export AGENT_WORKLOG_LLM__MODEL="company-summary-model"
agent-worklog report --period last-week
```

Agent Worklog reads the value named by `API_KEY_ENV`; it does not log that value.

To disable external summarization globally:

```bash
export AGENT_WORKLOG_LLM__ENABLED="false"
```

To disable it for one command:

```bash
agent-worklog report --period last-week --no-llm
```

## Precedence

For each setting, Agent Worklog takes the environment variable, then the settings file,
then the default. CLI period and output options apply to the current invocation only and
override the settings that back them.
