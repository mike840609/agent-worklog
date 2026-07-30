# Changelog

All notable changes to this project are documented in this file.

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
