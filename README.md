# Agent Worklog

Agent Worklog turns coding-agent sessions into repository-based engineering reports.
The first release supports OpenCode and groups work by canonical Git repository, so
sessions from separate folders and Git worktrees appear in one project section.

## What it does

- queries OpenCode sessions across every project, independent of the current directory;
- selects sessions with activity inside a rolling or calendar-week period;
- exports each session with `opencode export --sanitize`;
- resolves Git remotes and groups worktrees by repository identity;
- preserves child-session repository ownership;
- extracts evidence with source activity IDs and confidence;
- redacts common secrets before rendering or optional LLM summarization;
- continues after individual export failures and records warnings;
- writes Markdown reports atomically with owner-only permissions.

## Requirements

- Python 3.11 or newer
- OpenCode available as `opencode`
- An OpenCode version that provides `opencode db` and `opencode export --sanitize`
- Git available as `git`

## Installation

The recommended installation method for the CLI is `pipx`:

```bash
pipx install agent-worklog
```

A regular Python environment also works:

```bash
pip install agent-worklog
```

For development:

```bash
git clone https://github.com/mike840609/agent-worklog.git
cd agent-worklog
uv sync --locked --extra dev
```

## First run

Check that OpenCode and Git are accessible:

```bash
agent-worklog doctor
```

Preview how the previous complete Monday-to-Monday week is grouped:

```bash
agent-worklog scan --period last-week
```

Generate the corresponding Markdown report without an external LLM:

```bash
agent-worklog report --period last-week --no-llm
```

The default output is written under `reports/`.

## Report periods

`last-week` means the previous complete calendar week in the configured timezone. The
range is half-open: Monday 00:00 is included and the following Monday 00:00 is excluded.

```bash
agent-worklog report --period last-week
```

A rolling range ending now is available with `--days`:

```bash
agent-worklog report --days 7
```

An explicit range can be supplied with ISO timestamps:

```bash
agent-worklog report \
  --since 2026-07-20T00:00:00+08:00 \
  --until 2026-07-27T00:00:00+08:00
```

Exactly one of `--period`, `--days`, or `--since` is required. `--until` requires
`--since`.

## Subagent sessions

Child/subagent sessions are included by default and are attributed to the repository they
actually ran in, so a subagent that worked in another checkout appears under that
repository. To report only root sessions:

```bash
agent-worklog report --period last-week --root-only
```

## Repository grouping

Agent Worklog resolves every loaded session independently before considering
parent/child relationships. Identity selection follows this order:

1. normalized Git `origin` remote;
2. hashed Git common directory;
3. OpenCode project ID;
4. hashed working directory;
5. per-session unknown identity.

SSH and HTTPS remotes for the same repository normalize to the same identity. Branches
do not split a repository, and child sessions that run in another repository remain in
the child repository.

## LLM summaries

LLM use is optional. Agent Worklog constructs an OpenAI-compatible client only when all
of these conditions are true:

- LLM support is enabled;
- `--no-llm` is not supplied;
- the configured API-key environment variable is present.

For the default OpenAI-compatible configuration:

```bash
export OPENAI_API_KEY="..."
agent-worklog report --period last-week
```

The request contains redacted structured evidence, not raw transcripts or raw metadata.
Timeouts, HTTP 429/5xx responses, and invalid structured output are retried once and then
fall back to the deterministic summary. Use `--no-llm` to guarantee a local-only report.

## Usage statistics

Each report includes an OpenCode usage section built from `opencode stats`, covering
models, tokens, and tools. OpenCode reports usage only for a window ending now, so the
window shown starts at the report period's start and runs to generation time; it contains
the report period but is wider than it. If `opencode stats` is unavailable, the section is
omitted and a warning is recorded in the report.

## Output and overwrite behavior

Choose an output path explicitly:

```bash
agent-worklog report \
  --period last-week \
  --no-llm \
  --output weekly.md
```

Existing files are not overwritten unless `--force` is supplied:

```bash
agent-worklog report --period last-week --output weekly.md --force
```

Preview the generated Markdown without writing a file:

```bash
agent-worklog report --period last-week --no-llm --dry-run
```

Use `--verbose` to print partial-export and fallback warnings. Use `--quiet` to print only
the output path after a successful report.

## Configuration

The MVP uses environment-based configuration with the `AGENT_WORKLOG_` prefix and `__`
for nested fields. Common examples:

```bash
export AGENT_WORKLOG_REPORT__TIMEZONE="Asia/Taipei"
export AGENT_WORKLOG_REPORT__OUTPUT_DIRECTORY="reports"
export AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__EXECUTABLE="opencode"
export AGENT_WORKLOG_LLM__MODEL="gpt-5-mini"
export AGENT_WORKLOG_LLM__BASE_URL="https://api.openai.com/v1/"
export AGENT_WORKLOG_LLM__ENABLED="false"
```

See [Configuration](docs/configuration.md) for all current settings.

## Privacy

OpenCode exports are requested with `--sanitize`, and Agent Worklog applies recursive
redaction before report rendering and before optional LLM calls. Generated reports can
still contain proprietary goals, filenames, commands, and work descriptions. Review a
report before sharing it outside its intended audience.

See [Privacy and security](docs/privacy.md) for the exact trust boundary and limitations.

## Partial failures and exit codes

A failed individual session export is skipped and recorded as a report warning. If every
candidate export fails, the harness command fails instead of producing a misleading empty
report.

| Code | Meaning |
|---:|---|
| 0 | Success |
| 2 | Invalid CLI usage |
| 3 | Configuration error |
| 4 | No matching activity |
| 5 | Harness/OpenCode failure |
| 7 | Report output failure |

## MVP limitations

- OpenCode is the only supported harness.
- The source is the OpenCode CLI, not direct SQLite access.
- Markdown is the only report format.
- Usage statistics cover a window ending at generation time, not the report period exactly.
- There is no persistent cache or `inspect` command.
- Historical sessions whose working directories were deleted may use a fallback identity.
- Repository resolution reflects the Git metadata currently available at the recorded path.
- Codex and Claude Code adapters are explicitly deferred.

## Development checks

```bash
uv sync --locked --extra dev
uv run pytest --cov=agent_worklog --cov-fail-under=80
uv run ruff check .
uv run pyright
uv build
```

See [Releasing Agent Worklog](docs/releasing.md) for PyPI Trusted Publishing setup and the tag-based release process.

## License

MIT
