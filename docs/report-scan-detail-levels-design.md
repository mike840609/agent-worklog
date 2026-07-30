# Report and Scan Detail Levels Design

**Date:** 2026-07-31

## Summary

Add a `--detail brief|full` option to `report` so a worklog can be produced either
as today's full document or as a short bulleted digest suitable for a weekly
status update. `full` stays the default, so existing output does not change.

`scan` does not gain a new option. Its "more detail" direction is served by the
existing `--verbose` flag, which already means "show me more" on that command and
today only adds warnings. It will additionally list each repository's session
titles and working directories.

Making brief truncation correct requires a second, smaller change: report list
truncation moves from `RuleBasedSummarizer` into `MarkdownRenderer` so there is
exactly one truncation point. This is explained under
[Single truncation point](#single-truncation-point).

## Goals

- Produce a short report that fits in a chat message or a weekly status email.
- Keep the default output of both commands byte-identical to today.
- Let `scan` show which sessions it selected without running the full report
  pipeline.
- Keep safety-relevant output (warnings) present at every detail level.
- Keep the truncation rule in one place so omitted-item counts are always
  correct.

## Non-goals

- A `brief` direction for `scan`. Its table is already the shortest useful form,
  so the value would be a permanent no-op.
- A configuration-file default for the detail level.
- Per-section configurable item limits.
- A machine-readable (JSON) report format.
- Any change to evidence extraction, summarization content, or the LLM prompt.

## Approaches Considered

### 1. `--detail` on `report`, `--verbose` on `scan`

The selected approach. One new option, on the one command whose output actually
spans two useful lengths. `scan` reuses a flag whose existing meaning already
covers the request.

The two commands end up with different option sets, but they already do:
`report` is a strict superset of `scan`, adding `--output`, `--dry-run`,
`--no-llm`, and `--force`. The dividing line is that session-selection options
are shared and output-production options belong to `report` alone, because only
`report` writes a file. `--detail` is an output-production option and lands on
the existing side of that line rather than introducing a new rule.

### 2. `--detail brief|full` on both commands

Rejected. Preserving current behavior forces different defaults per command
(`report` defaults to `full`, `scan` to `brief`), so the same option name and
value set would show two different defaults in `--help` for reasons that are an
artifact of implementation history. It also creates `scan --detail brief`, a
value that can never differ from the default.

### 3. Boolean flags: `report --brief` and `scan --full`

Rejected, though it avoids the divergent-default problem cleanly since "flag
absent" means "current behavior" on both commands. Two differently named,
opposite-polarity flags for one concept read worse in `--help`, and the `scan`
side is redundant with `--verbose`.

## Architecture

### CLI option

Add a `DetailLevel` string enum to `cli.py` with members `BRIEF` and `FULL`, and
a module-level `typer.Option` singleton for it. The singleton follows the
existing `_HARNESS_OPTION` pattern: ruff's B008 does not treat an enum-typed
`typer.Option(...)` call as an immutable default, so it must be constructed once
at module level rather than inline in the command signature.

The option is added to `report` only, with default `DetailLevel.FULL`. Typer
validates the value, so an unknown level exits with its standard
`BadParameter` code and needs no handling in this codebase. `--detail` is
orthogonal to `--quiet` and `--verbose` and adds no mutual-exclusion check.

### Detail levels

`MarkdownRenderer.render` accepts a keyword-only `detail` argument defaulting to
`DetailLevel.FULL`, and the `Renderer` protocol in `services/report.py` gains the
same argument so both branches of its `Renderer | MarkdownRenderer` annotation
satisfy the call. The default keeps existing call sites that pass only the report
valid. The renderer passes `detail` and a per-section item limit into the
template context. `ReportService` threads the level from the CLI to the renderer;
it makes no other use of it.

| Report region | `full` | `brief` |
| --- | --- | --- |
| Period / Timezone / Generated header | rendered | rendered |
| Repository heading and `Repository:` remote line | rendered | rendered |
| Repository summary sentence and session counts | rendered | rendered |
| Completed / Problems Resolved / In Progress | limit 20 | limit 5 |
| Key Files | limit 20 | omitted |
| Directories / Branches | uncapped | omitted |
| Sessions | uncapped | omitted |
| Usage (and its window caveat) | rendered | omitted |
| Warnings | rendered, uncapped | rendered, uncapped |

Warnings stay at both levels because they report degraded data — an unreadable
session, a fallback repository identity, a failed LLM call. A shorter report is a
request for less detail about the work, not for less disclosure about what the
tool could not do.

Usage is omitted from `brief` because it is a multi-line ASCII table and the
single largest block in a typical report, which defeats the purpose of the level.

Sessions and Directories remain uncapped at `full`, unchanged from today. The
`session_refs` docstring records why: it is the report's only index back to
individual sessions, and operators bound it with `--root-only` or a shorter
period.

### Single truncation point

Today `RuleBasedSummarizer._limited` caps its lists at 20 entries and appends a
literal `Additional items omitted: N` string as an extra list item.
`OpenAICompatibleSummarizer` applies no cap at all, so LLM lists reach the
template at whatever length the model produced.

If the renderer added a second cap at 5 on top of that, a rule-based section that
had already been truncated would arrive as 20 real items plus one synthetic
marker item. Slicing that to 5 and reporting "16 omitted" would be wrong twice
over: it counts the marker as a work item, and it discards the count the marker
was carrying.

Truncation therefore moves to the renderer:

- Delete `_MAX_ITEMS` and `_limited` from `rule_based.py`. `_unique_sorted` stays
  and is used directly, so the summarizer emits complete, deduplicated,
  sorted lists.
- The template applies the level's limit and emits the overflow line, using the
  existing `Additional items omitted: N` wording.

This yields one truncation point with an always-correct count, and it applies the
20-item cap to LLM summaries as well, which are currently unbounded.

`RepositorySummary` now carries untruncated lists. The renderer is its only
consumer; no persisted format or JSON output depends on it.

### Template structure

`worklog.md.j2` currently repeats the same `{% if items %}` / `#### Heading` /
`{% for %}` block seven times. Six of those — Completed, Problems Resolved,
In Progress, Key Files, Directories, Branches — differ only in heading, source
list, and whether items are wrapped in backticks. They collapse into one macro
that takes the heading, the list, the limit, and a backtick flag, and that emits
the overflow line when the list exceeds the limit.

Sessions keeps its own block because its items are `SessionRef` objects rendered
as `title — \`session_id\``, not plain strings.

The template ends up shorter than it is today.

### `scan --verbose`

`ConsoleReporter.scan_result` gains no new parameter. Inside its existing
`if self.verbose:` branch, after the current warnings, it prints one block per
repository listing each session's title (falling back to the session ID when the
title is absent) and the distinct working directories.

Every value needed is already on `ScanResult`, so no service, source, or model
changes are required. `--quiet` keeps printing only the session count.

## Data Flow

1. `report` parses `--detail` into a `DetailLevel` and passes it to
   `_build_report_service`.
2. `_build_report_service` passes it to `ReportService`.
3. `ReportService.generate` passes it to `renderer.render(report, detail=...)`.
4. `MarkdownRenderer.render` maps the level to an item limit and renders the
   template with both values in context.
5. Redaction runs over the rendered content exactly as it does today, after
   rendering, so no detail level can bypass it.

`scan` is unaffected by this flow; its change is confined to `ConsoleReporter`.

## Error Handling

No new failure paths. Specifically:

- An invalid `--detail` value is rejected by Typer before any work starts.
- A repository with no items in the kept sections renders its heading, summary,
  and counts with no section bodies, the same as a sparse repository today.
- A report whose repositories are all empty still triggers the existing
  `NoSessionsError` path, which is checked before rendering.
- `brief` omitting the Usage section does not suppress the existing
  `usage statistics unavailable` warning; usage collection still runs and its
  failure is still reported under Warnings.

## Component Changes

- `cli.py` — add `DetailLevel`, add the option singleton, add the parameter to
  `report`, thread it through `_build_report_service`.
- `services/report.py` — accept and forward the detail level.
- `renderers/markdown.py` — accept `detail`, map it to a limit, put both in the
  template context.
- `templates/worklog.md.j2` — add the section macro, apply the limit and overflow
  line, gate the appendix sections and Usage on the level.
- `summarizers/rule_based.py` — remove `_MAX_ITEMS` and `_limited`; call
  `_unique_sorted` directly.
- `logging.py` — extend the verbose branch of `scan_result`.
- `README.md`, `README.zh-TW.md` — document `--detail` in the option tables and
  document that `scan --verbose` lists sessions.
- `CHANGELOG.md` — one entry.

## Testing

### Renderer

- `full` output is unchanged against the existing expected-output assertions.
- `brief` omits Key Files, Directories, Sessions, Branches, and Usage.
- `brief` keeps the header, repository headings, summary sentences, session
  counts, and Warnings.
- `brief` caps Completed, Problems Resolved, and In Progress at 5 and appends
  `Additional items omitted: N` with the correct N.
- A section with exactly the limit renders no overflow line.
- A 25-item list at `full` renders 20 items and `Additional items omitted: 5`,
  covering the count that previously came from the summarizer.
- An LLM-shaped summary with 25 items is capped the same way, covering the
  previously unbounded path.

### Summarizer

- Existing `rule_based` truncation tests move to the renderer. The summarizer
  tests instead assert that lists come back complete, deduplicated, and sorted.

### CLI

- `report --detail brief` reaches the renderer with `BRIEF`.
- `report` without `--detail` reaches the renderer with `FULL`.
- `report --detail bogus` exits non-zero without writing a file.
- `--detail` composes with `--dry-run`, `--quiet`, and `--output`.

### Scan console

- `scan --verbose` prints session titles and working directories.
- `scan` without `--verbose` prints only the table, unchanged.
- `scan --quiet` prints only the count, unchanged.
- A session with no title falls back to its session ID.

### Documentation

- Extend `tests/unit/test_documentation.py` to assert both READMEs document
  `--detail` and the `scan --verbose` session listing.

## Acceptance Criteria

1. `report` without `--detail` produces byte-identical output to the current
   implementation, with one deliberate exception: an LLM-produced list longer
   than 20 items is now capped like a rule-based one, where it previously
   rendered in full.
2. `report --detail brief` produces a report containing only the header, per
   repository the summary and up to five each of Completed, Problems Resolved,
   and In Progress, and the Warnings section.
3. Overflow counts are correct at both levels and are produced in exactly one
   place.
4. Warnings appear at both detail levels.
5. `scan` without flags and `scan --quiet` produce output identical to the
   current implementation.
6. `scan --verbose` additionally lists session titles and working directories.
7. Redaction coverage is unchanged; no detail level emits unredacted content.
8. Both READMEs document the new option and the extended `scan --verbose`
   behavior.
