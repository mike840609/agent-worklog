# Changelog

All notable changes to this project are documented in this file.

## Unreleased

- Split the README into a condensed landing page and dedicated published docs. The
  README now points to three new files in `docs/` that hold the detail it used to
  carry: `docs/guides.md` (reporting periods, subagents, repository grouping, LLM
  summaries, and output handling), `docs/usage-statistics.md` (the usage window
  caveat), and `docs/limitations.md` (the full per-harness limit list). `README.md`
  drops from 434 to 228 lines and the Traditional Chinese `README.zh-TW.md` is
  mirrored to the same shape. Documentation links stay absolute so they resolve from
  PyPI, which renders the README as its long description. The Codex-limit assertions
  in `tests/unit/test_documentation.py` now read `docs/limitations.md` because the
  content moved there.

## 0.5.0

- Add `codex` to `--harness`. Sessions are discovered from `~/.codex/state_<n>.sqlite`,
  which already indexes every session with its rollout path, working directory,
  timestamps, and parent edge, so a period query is one SQL statement instead of
  opening every rollout file; a scan of `sessions/` and `archived_sessions/` is the
  fallback when that database is absent or its schema has changed.
- No Codex report claims that a command passed or failed. Codex records exit codes
  only inside free-form tool output text, in at least three formats, so a regex over
  it would fail silently the day Codex changes it. `patch_apply_end`'s `success` flag
  is the one structured signal used, and it reports a file change.
- Leave commands run from inside Codex's `exec` tool out of the report. `exec` takes
  an arbitrary JavaScript program rather than a command — a strict parse for a single
  wrapped `exec_command` call matched none of 4,963 measured calls — so its input is
  never put in an activity, which also keeps it out of outbound LLM requests.
- Build the Codex usage table by differencing the running `total_token_usage` rather
  than summing `last_token_usage`, which over-counted by 3.7% on a measured session
  because Codex emits some `token_count` events more than once.
- Drop the change values Codex records in `patch_apply_end.changes` in the mapper —
  a unified diff (`unified_diff`) for the majority `update` case, or a whole file
  (`content`) for a new one. Only the changed paths reach a session, so neither a
  diff nor a written file's full body carries toward the report's 300-character cap.
- Move the per-model usage table out of the Claude Code package. It reads only
  activity metadata, so Claude Code and Codex now share one implementation.
- Stop naming Claude Code in the missing-prompt warning for sessions from other
  harnesses.
- Lose Codex session titles when falling back to the rollout scan: across 238 measured
  rollout files, no `session_meta` payload carried a `title` key, only
  `agent_nickname` (171 of 238), and only the state database's `threads.title` column
  has the real title.
- Fix the rollout fallback picking the wrong session id. `session_meta.session_id` is the
  originating/root thread id, inherited by every resumed session and every subagent, not
  the session's own id; `session_meta.id` is. Measured against a real `~/.codex`, 220
  rollout files carried 220 distinct `id`s but only 42 distinct `session_id`s, so the
  fallback path was collapsing 220 real sessions onto 42 report entries. The descriptor
  now prefers `id`, falling back to `session_id` only when `id` is absent.
- Stop treating machine-injected `event_msg/user_message` payloads as human goals.
  Codex writes attached shell input/output, browser context, file-mention envelopes,
  slash-command records, task notifications, and resume summaries using the same
  `user_message` record type as a real prompt, and none of them carried a marker the
  mapper checked for. Measured against real data, 88 of 592 `user_message` payloads
  were machine-injected, including raw local command output that `docs/privacy.md`
  promises never reaches a report. The mapper now drops a `user_message` whose text
  opens with one of a documented set of markers, contributing no goal for it; a message
  sent with attachments therefore contributes no goal at all rather than a
  mis-attributed one.

## 0.4.1

- Redact the repository name in `scan`'s table and in `scan --verbose`'s
  repository heading, and stop the table from interpreting that name as Rich
  markup. Both call sites now match the session listing's existing handling, so
  the same repository's name can no longer read differently across the two
  views of one `scan` run.
- Report Claude Code verification commands as completed when the harness observed
  them succeed. Claude Code records no exit code, so the extractor treated every
  command as having an unobservable outcome and `Completed` was empty in every
  report — measured across 282 real sessions, it fired zero times. Claude Code
  does record `is_error` on the tool result, which is observed rather than
  inferred, and the mapper was dropping it: a *failed* call records
  `toolUseResult` as a plain error string instead of an object, and the mapper
  required an object before reading anything. On the same 282 sessions this
  yields 354 completed verifications and 143 observed failures, where both were
  previously zero. Where a real exit code exists it still wins, being the more
  precise signal.
- Stop treating a test command named inside a heredoc as a verification run.
  `gh pr create --body "$(cat <<'EOF' … pytest … EOF)"` runs no tests; matching
  the whole command string accounted for 26 of 378 matches on real transcripts.
  This was harmless while such items were only recorded as having run, but an
  observed success would have promoted each one to a false "Verification passed"
  claim in the report.
- Move report list truncation from the rule-based summarizer into the Markdown
  renderer, so there is one truncation point and the `Additional items omitted`
  count is always the real remainder. LLM-produced lists are now capped at 20
  items like rule-based ones; they were previously unbounded. The overflow line
  under `Key Files` is no longer wrapped in backticks — previously the
  summarizer injected it into the `key_files` list itself, so the template's
  code-item formatting wrapped it like a filename, which it never was.
- Add `--detail {full,brief}` to `report`, defaulting to `full`, which is the
  existing output. `--detail brief` keeps the header, and for each repository the
  summary and up to five each of Completed, Problems Resolved, and In Progress;
  it leaves out Key Files, Directories, Sessions, Branches, and the usage table.
  Warnings are kept at both levels.
- List each repository's session titles and working directories under
  `scan --verbose`, so the selected sessions can be checked without generating a
  report. Titles and directories are redacted before printing; the Claude Code
  path has no upstream sanitize step.

## 0.4.0

- Rewrite both README capability lists as outcome-oriented capability summaries while
  keeping harness-specific acquisition and accounting details in their dedicated sections.
- Keep the runtime and project versions consistent with release metadata, and correct the
  stale Claude Code stderr limitation.
- Add `--harness {opencode,claude-code}` to `doctor`, `scan`, and `report`, defaulting
  to `opencode`. Read Claude Code session transcripts directly from
  `AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY` (default
  `~/.claude/projects`); `--harness claude-code` runs no external harness CLI, and
  `doctor` instead checks that the projects directory exists and is readable, plus
  `git --version`.
- Build the Claude Code usage table from token counters recorded on the sessions
  themselves, so it covers the report period rather than a trailing window ending at
  report generation time, which is what `opencode stats` still reports. Every model turn
  in the period is counted, including turns that emitted only internal reasoning; their
  tokens are carried by the neighbouring recorded activity, which is also the table's one
  imprecision — a turn on the period boundary can be counted on the other side of it.
- Report Claude Code verification commands without claiming an outcome. Claude Code tool
  results carry no exit code, so a command whose stderr was empty is recorded as `Ran
  verification command: <command>` at MEDIUM confidence with an unknown status, and
  appears under "In Progress" rather than "Completed". A command that redirects or
  discards its stderr (`2>`, `&>`, `|&`) produces no outcome at all, because its empty
  stderr is an artefact of the redirection. "Verification passed" remains reserved for the
  OpenCode path, which observes a real exit code.
- Stop treating non-empty stderr as a failed command on the Claude Code path. Git writes
  to stderr on success, so the rule produced 31 items of `git stash` and `cd … && uv sync`
  noise against real transcripts — none of which any report section renders, while all of
  them travelled in the outbound LLM request. Only an observed exit code now records a
  failure, which keeps the LLM and `--no-llm` reports describing the same set of problems.
- Cap every evidence item's text at 300 characters for both harnesses, marking the cut
  with an ellipsis. A Claude Code `input.command` is retained whole, so a heredoc used to
  write a file previously carried that file's entire body into the report and into
  optional LLM requests; secret-pattern redaction cannot detect such text.
- Group a Claude Code session that spans several working directories under the last
  one, and read subagent transcripts alongside root sessions, excluded by `--root-only`
  like OpenCode child sessions.
- Warn when a root session records assistant work but no user messages. A Claude Code
  transcript written before roughly version 2.1.187 does not mark human prompts, so such
  a session contributes no goals; the warning replaces a silent loss. Subagent sessions
  are exempt, because a subagent is spawned with its parent's prompt and holds no human
  prompt by design.
- Skip models whose usage totals are all zero in the Claude Code usage table, so the
  `<synthetic>` placeholder Claude Code writes for local and error turns no longer adds
  an all-zero row.
- Honor `AGENT_WORKLOG_HARNESSES__*__ENABLED`. Selecting a disabled harness now fails
  with a configuration error (exit code 3) instead of the setting being ignored.
- Move the shared subprocess runner out of the OpenCode package into
  `agent_worklog.process.CommandRunner` so both harnesses depend on one implementation.
## 0.3.0

- Add a transient, single-line progress status to `scan` and `report`, showing the
  current stage and accurate session or repository counts during long operations.
- Keep progress on stderr so `report --dry-run` stdout remains valid Markdown, and
  suppress progress completely with `--quiet`.
- Keep progress labels generic to avoid exposing session, path, repository, warning,
  or API details; clip long statuses to one row on narrow terminals.

## 0.2.0

- Re-release 0.1.1 under a correct semantic version. That release added features, so it
  belongs in a minor version. The contents are otherwise unchanged; prefer 0.2.0.

## 0.1.1

- Add a Traditional Chinese README and a status badge row, and declare MIT and
  Python 3.11–3.13 classifiers so the PyPI project page reports them.
- Add `--root-only` to `scan` and `report` to exclude child and subagent sessions. Child
  sessions remain included by default and stay attributed to the repository they ran in.
- List each repository's session titles, session IDs, and working directories in the report.
  Session identifiers are always derived from recorded evidence, never from an LLM response.
- Add a `## Usage` report section from `opencode stats`. The window runs from the report
  period's start to generation time, because OpenCode reports usage only for a window ending
  now; the report states this. An unavailable `opencode stats` becomes a warning, not a
  failed report.
- Translate subprocess timeouts and launch failures inside the command runner, so a hung
  `opencode` or `git` call degrades to a failed check or a fallback identity instead of an
  unhandled traceback.
- Read the clock once per `report` invocation, so `--days N` no longer reports an N+1 day
  usage window. An invalid timezone is now reported before invalid period selectors.

## 0.1.0

- Add an installable Python 3.11+ CLI with `doctor`, `scan`, and `report` commands.
- Query OpenCode sessions across all projects through the OpenCode CLI.
- Select sessions by interval overlap and filter exact half-open activity ranges.
- Export transcripts with `--sanitize` and tolerate individual export failures.
- Normalize Git remotes and group sessions from multiple worktrees by repository.
- Preserve repository ownership for parent and child sessions.
- Extract provenance-aware evidence and recursively redact common secrets.
- Generate secure deterministic Markdown reports.
- Add optional OpenAI-compatible structured summaries with retry and fallback.
- Add Python 3.11–3.13 CI and trusted-publishing release automation.
