# Configuration

Agent Worklog 0.1 reads configuration from environment variables through
`pydantic-settings`.

- Prefix: `AGENT_WORKLOG_`
- Nested delimiter: `__`
- Boolean values: `true` or `false`

No YAML configuration file is loaded in the MVP.

## OpenCode harness

| Environment variable | Default | Purpose |
|---|---|---|
| `AGENT_WORKLOG_HARNESSES__OPENCODE__ENABLED` | `true` | Records whether the harness is enabled. |
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
| `AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__ENABLED` | `true` | Records whether the harness is enabled. |
| `AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY` | `~/.claude/projects` | Directory containing per-project session transcripts. |

Selecting the harness is a CLI concern, not a settings one: pass `--harness claude-code`
to `doctor`, `scan`, or `report`. No executable or CLI timeout setting applies, because
Agent Worklog reads the JSONL transcripts under `projects_directory` directly and never
launches a Claude Code process.

Example:

```bash
export AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__ENABLED="true"
export AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY="$HOME/.claude/projects"
agent-worklog doctor --harness claude-code
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

## CLI precedence

CLI period and output options apply to the current invocation. Environment settings
provide defaults for harness execution, timezone, output directory, and LLM behavior.
