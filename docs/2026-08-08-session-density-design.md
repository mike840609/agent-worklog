# Session Density on Interactive Rows

**Date:** 2026-08-08

## Summary

Give every row in the interactive session review and browse screens the information
density that the mole launcher gives its app list: enough per-row signal to decide
"is this session worth writing into the weekly report" without opening it.

Today a session row is just its title (`render.py:238`, `render.py:292`) and a repo row
just `n / m`. The `AgentSession` already carries everything needed — `created_at`,
`updated_at`, an in-period-filtered `activities` list, and `parent_session_id`
(models/session.py:39-43, 56-66) — but the UI renders none of it.

This design adds, per row:

- **session rows** — last activity date + message count, plus a subagent tag
  (`● [sub] Aug 5 · 12 msgs Fix sanitize export`)
- **repository rows** — date span + summed message count (`● repo  8 / 9  Aug 3–5 · 240 msgs`)

## Goals

- Let a user judge "is this session worth writing into the report" by skimming one row.
- Surface conversation volume and recency per session, and both per repository.
- Distinguish subagent sessions at a glance when `include_subagents` is on.
- Reuse the data already carried by the filtered `ScanResult`; no contract changes.

## Non-goals

- No token usage display (OpenCode usage is UNKNOWN; per-activity usage lives in
  `activity.metadata` and is a usage-statistics concern, not a row density concern).
- No new sorting, alignment grids, or fixed-width columns.
- No changes to the report output, `ScanResult`, `ResolvedSession`, or selection model.

## Metrics

- **Message volume**: count of `SessionActivity` entries whose `activity_type` is
  `USER_MESSAGE` or `ASSISTANT_MESSAGE`. Tool calls/results, commands, errors, and system
  messages are excluded. Because `filter_session_to_period` already narrowed
  `session.activities` to the report period, the count is the **in-period** conversation.
- **Date**: the **last in-period activity timestamp**. If the session has no activities
  (a sanitized/metadata-only OpenCode export), fall back to `session.updated_at` then
  `session.created_at`.
- **Subagent**: `session.parent_session_id is not None`.

## Component

### New module `interactive/density.py`

Pure functions, no `rich`, no model changes — fully unit-testable without a renderer:

```python
def message_volume(session: AgentSession) -> int
    # user_message + assistant_message count

def last_activity_at(session: AgentSession) -> datetime | None
    # last activity.timestamp; else updated_at; else created_at

def session_meta(session: AgentSession) -> str
    # "Aug 5 · 32 msgs", "Aug 5" (volume 0), or "" (no date, no volume)

def repository_meta(repository_id: str, scan: ScanResult) -> str
    # "Aug 3–5 · 240 msgs", "Aug 3 · 240 msgs", or "" when nothing dated
```

Repository span = min first-date to max last-date across the repo's sessions (single date
becomes just that date); volume = sum of `message_volume` across the repo's sessions.

Date format follows the existing `_period_label` convention (`%b %d`, en dash between a
two-date span).

## Row composition in `interactive/render.py`

Metadata is rendered **before** the variable portion (title / repo name) so the existing
`overflow="ellipsis"` truncation (`_print_viewport_line`, render.py:53-65) clips the title
and never the signals.

Session row in review / browser:

```text
     ○ [sub] Aug 5 · 12 msgs Improve wiki synthesis
     ● Aug 4 · 8 msgs Audit task list
```

Repository row:

```text
▼ ● agent-worklog  8 / 9   Aug 3–5 · 240 msgs
  ◐ assets-tracker  5 / 5   Aug 4–7 · 96 msgs
```

Styling: the `[sub]` tag and the `Aug 5 · 12 msgs` meta render dim; the title is plain
(or bold on the cursor row as today). A small `_print_viewport_text` helper keeps
`no_wrap` + ellipsis for pre-composed multi-style `Text` rows.

- Both `render_session_review` and `render_session_browser` use the same density helpers.
- Rows with no date and no volume show no meta (a metadata-only session degrades to today's
  title-only row).

## Data flow

```text
ScanResult  →  density.py (pure)  →  Text composed in render.py  →  console.print(no_wrap, ellipsis)
```

No changes to `SelectionState`, `ReportDraft`, scanning, filtering, or report generation.

## Edge cases

| Case                                            | Behavior                                  |
|-------------------------------------------------|-------------------------------------------|
| Session has activities but all timestamps None  | no date rendered; volume still shown      |
| Metadata-only sanitized session (0 activities)  | date from `updated_at`/`created_at`; no volume |
| Repo mixes dated and undated sessions           | span from dated ones; volume sums all      |
| Multi-day span / cross-month                    | `Jul 30 – Aug 4` keeps the en dash       |
| Existing render unit tests                      | no timestamps/activities → no meta is rendered; existing assertions unchanged |

## Testing strategy

1. **Pure unit tests for `density.py`** (`tests/unit/interactive/test_density.py`):
   - volume counts user+assistant only (tool calls excluded)
   - last date falls back across activities → updated_at → created_at
   - single-date vs span rendering
   - subagent flag
   - empty results → `""`
2. **Renderer tests** (`tests/unit/interactive/test_render.py`): fixtures carrying
   timestamps and activities assert `Aug 5 · 32 msgs`, `[sub]`, and repo-span text; all
   existing substring assertions remain green.
3. Run the interactive unit suite: `pytest tests/unit/interactive`.

## Documentation impact

- Update the ASCII examples in `docs/p0-interactive-ux-design.md` (Session Review screen,
  and the Browser description) so the examples show dates, densities, and `[sub]` tags.
- No CLI or public API documentation changes: this only enriches interactive-only rows.

## Acceptance criteria

1. Session rows in Review and Browser show a date and message volume when available.
2. Subagent sessions in Review are marked with a `[sub]` tag when `include_subagents` is on.
3. Repository rows show a date span and summed message volume in Review and Browser.
4. Metadata renders before the variable portion and survives truncation.
5. No contract or model changes; existing render/selection/scan tests stay green.
6. A metadata-only session falls back to its timestamps for the date and shows no volume.