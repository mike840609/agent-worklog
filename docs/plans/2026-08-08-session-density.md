# Session Density on Interactive Rows — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-row information density (date, message volume, subagent tag) to the interactive session review and browse screens so a user can judge whether a session is worth a weekly report row without opening it.

**Architecture:** A new pure `interactive/density.py` module computes per-session and per-repository density strings from the existing filtered `ScanResult`; `interactive/render.py` composes them into dim metadata ahead of each title via a small `Text`-row helper, keeping `no_wrap` + `overflow="ellipsis"` truncation.

**Tech Stack:** Python 3.11, pydantic models, Rich `Text`/`Console`. Tests via pytest (importlib import mode per `pyproject.toml`).

## Global Constraints

- No contract changes: `ScanResult`, `ResolvedSession`, `AgentSession`, `SelectionState`, report generation, and CLI are untouched.
- `message_volume` counts only activities with `activity_type` in `{USER_MESSAGE, ASSISTANT_MESSAGE}`.
- The per-session date is the last non-None `activity.timestamp`; fall back to `session.updated_at` then `session.created_at` only when a session has no activities.
- Subagent = `session.parent_session_id is not None`.
- Session density metadata renders **before** the title so the variable title absorbs ellipsis truncation and the signals never clip. Repository rows instead append density after the repo count (`... 8 / 9   Aug 3–5 · 240 msgs`), matching the spec's rendered example; repo display names are short so the trailing density is not a truncation risk.
- Date labels are non-padded (`Aug 5`), not `Aug 05`; same-month spans use `Aug 3–5`, cross-month spans use `Jul 30 – Aug 4` with the en dash `–`.
- A session with no date and no message volume renders no metadata; existing render tests that use unresolvable sessions must stay green.

---

### Task 1: Pure density module and its unit tests

**Files:**
- Create: `src/agent_worklog/interactive/density.py`
- Test: `tests/unit/interactive/test_density.py`

**Interfaces:**
- Consumes: `AgentSession` (models/session.py:56-66), `ScanResult` (services/scan.py:75-83).
- Produces:
  - `message_volume(session: AgentSession) -> int`
  - `last_activity_at(session: AgentSession) -> datetime | None`
  - `is_subagent(session: AgentSession) -> bool`
  - `session_meta(session: AgentSession) -> str` — e.g. `"Aug 5 · 12 msgs"`
  - `repository_meta(repository_id: str, scan: ScanResult) -> str` — e.g. `"Aug 3–5 · 240 msgs"`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/interactive/test_density.py`:

```python
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from agent_worklog.interactive.density import (
    is_subagent,
    last_activity_at,
    message_volume,
    repository_meta,
    session_meta,
)
from agent_worklog.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from agent_worklog.models.session import ActivityType, AgentSession, SessionActivity
from agent_worklog.models.time_range import DateRange
from agent_worklog.services.scan import ScanResult

TZ = ZoneInfo("Asia/Taipei")


def _session(*, created_at: datetime | None = None, updated_at: datetime | None = None,
             activities: list[SessionActivity] | None = None, parent_session_id: str | None = None) -> AgentSession:
    return AgentSession(
        harness="opencode",
        session_id="s1",
        parent_session_id=parent_session_id,
        created_at=created_at,
        updated_at=updated_at,
        activities=activities or [],
    )


def _activity(kind: ActivityType, ts: datetime) -> SessionActivity:
    return SessionActivity(activity_id="act", activity_type=kind, timestamp=ts, content="c")


def _resolved(session: AgentSession, repository_id: str = "repo") -> ResolvedSession:
    return ResolvedSession(
        session=session,
        repository=RepositoryIdentity(
            repository_id=repository_id,
            display_name=repository_id,
            identity_type=RepositoryIdentityType.PATH_FALLBACK,
            working_directory=f"/tmp/{repository_id}",
            resolution_method="test",
        ),
    )


def _scan(items: list[ResolvedSession]) -> ScanResult:
    by_repo: dict[str, list[ResolvedSession]] = {}
    for item in items:
        by_repo.setdefault(item.repository.repository_id, []).append(item)
    return ScanResult(
        period=DateRange(
            since=datetime(2026, 8, 1, tzinfo=TZ),
            until=datetime(2026, 8, 10, tzinfo=TZ),
        ),
        candidate_session_count=len(items),
        loaded_session_count=len(items),
        failed_session_count=0,
        resolved_sessions=items,
        sessions_by_repository=by_repo,
    )


def test_message_volume_counts_only_user_and_assistant() -> None:
    session = _session(
        updated_at=datetime(2026, 8, 5, tzinfo=TZ),
        activities=[
            _activity(ActivityType.USER_MESSAGE, datetime(2026, 8, 5, 9, 0, tzinfo=TZ)),
            _activity(ActivityType.ASSISTANT_MESSAGE, datetime(2026, 8, 5, 9, 1, tzinfo=TZ)),
            _activity(ActivityType.TOOL_CALL, datetime(2026, 8, 5, 9, 2, tzinfo=TZ)),
            _activity(ActivityType.SYSTEM, datetime(2026, 8, 5, 9, 3, tzinfo=TZ)),
        ],
    )
    assert message_volume(session) == 2


def test_last_activity_at_uses_latest_activity_timestamp() -> None:
    session = _session(
        created_at=datetime(2026, 8, 3, 9, 0, tzinfo=TZ),
        updated_at=datetime(2026, 8, 4, 9, 0, tzinfo=TZ),
        activities=[
            _activity(ActivityType.USER_MESSAGE, datetime(2026, 8, 5, 9, 0, tzinfo=TZ)),
        ],
    )
    assert last_activity_at(session) == datetime(2026, 8, 5, 9, 0, tzinfo=TZ)


def test_last_activity_at_falls_back_to_updated_then_created() -> None:
    created = datetime(2026, 8, 3, 9, 0, tzinfo=TZ)
    updated = datetime(2026, 8, 4, 9, 0, tzinfo=TZ)
    assert last_activity_at(_session(updated_at=updated, created_at=created)) == updated
    assert last_activity_at(_session(created_at=created)) == created
    assert last_activity_at(_session()) is None


def test_last_activity_at_none_when_activities_lack_timestamps() -> None:
    session = _session(
        updated_at=datetime(2026, 8, 4, 9, 0, tzinfo=TZ),
        activities=[
            SessionActivity(
                activity_id="a",
                activity_type=ActivityType.USER_MESSAGE,
                timestamp=None,
                content="c",
            )
        ],
    )
    assert last_activity_at(session) is None
    assert session_meta(session) == "1 msgs"


def test_is_subagent() -> None:
    assert is_subagent(_session(parent_session_id="parent")) is True
    assert is_subagent(_session()) is False


def test_session_meta_renders_date_and_volume() -> None:
    session = _session(
        updated_at=datetime(2026, 8, 5, 9, 0, tzinfo=TZ),
        activities=[
            _activity(ActivityType.USER_MESSAGE, datetime(2026, 8, 5, 9, 0, tzinfo=TZ)),
            _activity(ActivityType.ASSISTANT_MESSAGE, datetime(2026, 8, 5, 9, 1, tzinfo=TZ)),
            _activity(ActivityType.TOOL_CALL, datetime(2026, 8, 5, 9, 2, tzinfo=TZ)),
        ],
    )
    assert session_meta(session) == "Aug 5 · 2 msgs"


def test_session_meta_omits_volume_when_zero() -> None:
    session = _session(
        updated_at=datetime(2026, 8, 5, 9, 0, tzinfo=TZ),
        activities=[_activity(ActivityType.TOOL_CALL, datetime(2026, 8, 5, 9, 2, tzinfo=TZ))],
    )
    assert session_meta(session) == "Aug 5"


def test_session_meta_empty_without_date_or_volume() -> None:
    assert session_meta(_session()) == ""


def test_repository_meta_spans_dates_and_sums_volume() -> None:
    items = [
        _resolved(
            _session(
                updated_at=datetime(2026, 8, 3, tzinfo=TZ),
                activities=[
                    _activity(ActivityType.USER_MESSAGE, datetime(2026, 8, 3, 9, 0, tzinfo=TZ)),
                ],
            )
        ),
        _resolved(
            _session(
                updated_at=datetime(2026, 8, 5, tzinfo=TZ),
                activities=[
                    _activity(ActivityType.USER_MESSAGE, datetime(2026, 8, 5, 9, 0, tzinfo=TZ)),
                    _activity(ActivityType.ASSISTANT_MESSAGE, datetime(2026, 8, 5, 9, 1, tzinfo=TZ)),
                ],
            )
        ),
    ]
    assert repository_meta("repo", _scan(items)) == "Aug 3–5 · 3 msgs"


def test_repository_meta_cross_month_uses_en_dash() -> None:
    items = [
        _resolved(
            _session(
                updated_at=datetime(2026, 7, 30, tzinfo=TZ),
                activities=[
                    _activity(ActivityType.USER_MESSAGE, datetime(2026, 7, 30, 9, 0, tzinfo=TZ)),
                ],
            )
        ),
        _resolved(
            _session(
                updated_at=datetime(2026, 8, 4, tzinfo=TZ),
                activities=[
                    _activity(ActivityType.USER_MESSAGE, datetime(2026, 8, 4, 9, 0, tzinfo=TZ)),
                ],
            )
        ),
    ]
    assert repository_meta("repo", _scan(items)) == "Jul 30 – Aug 4 · 2 msgs"


def test_repository_meta_empty_when_no_dates() -> None:
    items = [_resolved(_session())]
    assert repository_meta("repo", _scan(items)) == ""


def test_repository_meta_single_date() -> None:
    items = [
        _resolved(
            _session(
                updated_at=datetime(2026, 8, 5, tzinfo=TZ),
                activities=[
                    _activity(ActivityType.USER_MESSAGE, datetime(2026, 8, 5, 9, 0, tzinfo=TZ)),
                ],
            )
        )
    ]
    assert repository_meta("repo", _scan(items)) == "Aug 5 · 1 msgs"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/interactive/test_density.py -v`
Expected: FAIL/ERROR with `ModuleNotFoundError: No module named 'agent_worklog.interactive.density'`.

- [ ] **Step 3: Write the module**

Create `src/agent_worklog/interactive/density.py`:

```python
"""Per-row information density for the interactive session lists."""

from datetime import datetime

from agent_worklog.models.session import ActivityType, AgentSession
from agent_worklog.services.scan import ScanResult

_MESSAGE_TYPES = frozenset({ActivityType.USER_MESSAGE, ActivityType.ASSISTANT_MESSAGE})


def message_volume(session: AgentSession) -> int:
    """Count user- and assistant-message activities in a session."""
    return sum(activity.activity_type in _MESSAGE_TYPES for activity in session.activities)


def last_activity_at(session: AgentSession) -> datetime | None:
    """Return the latest activity timestamp, or updated_at/created_at when the
    session has no activities at all."""
    timestamps = [
        activity.timestamp
        for activity in session.activities
        if activity.timestamp is not None
    ]
    if timestamps:
        return max(timestamps)
    if session.activities:
        return None
    return session.updated_at or session.created_at


def is_subagent(session: AgentSession) -> bool:
    """Return whether this session was spawned as a subagent."""
    return session.parent_session_id is not None


def session_meta(session: AgentSession) -> str:
    """Render density for one session row, e.g. ``Aug 5 · 12 msgs``."""
    parts: list[str] = []
    timestamp = last_activity_at(session)
    if timestamp is not None:
        parts.append(_day_label(timestamp))
    volume = message_volume(session)
    if volume:
        parts.append(f"{volume} msgs")
    return " · ".join(parts)


def repository_meta(repository_id: str, scan: ScanResult) -> str:
    """Render density for a repository row, e.g. ``Aug 3–5 · 240 msgs``."""
    sessions = scan.sessions_by_repository[repository_id]
    dates = [
        timestamp
        for item in sessions
        if (timestamp := last_activity_at(item.session)) is not None
    ]
    if not dates:
        return ""
    parts = [_span_label(min(dates), max(dates))]
    volume = sum(message_volume(item.session) for item in sessions)
    if volume:
        parts.append(f"{volume} msgs")
    return " · ".join(parts)


def _day_label(timestamp: datetime) -> str:
    return f"{timestamp:%b} {timestamp.day}"


def _span_label(first: datetime, last: datetime) -> str:
    if first.date() == last.date():
        return _day_label(first)
    if first.year == last.year and first.month == last.month:
        return f"{first:%b} {first.day}–{last.day}"
    return f"{_day_label(first)} – {_day_label(last)}"
```

This is the complete module and the complete `_span_label`; use it verbatim.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/interactive/test_density.py -v`
Expected: PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add src/agent_worklog/interactive/density.py tests/unit/interactive/test_density.py
git commit -m "feat: add interactive session density helpers"
```

---

## Task 2: Render density rows in review and browse

**Files:**
- Modify: `src/agent_worklog/interactive/render.py`
- Test: `tests/unit/interactive/test_render.py`

**Interfaces:**
- Consumes: `message_volume`, `last_activity_at`, `is_subagent`, `session_meta`, `repository_meta` from Task 1.
- Produces: `_print_viewport_text(console, text)` and `_session_row(...)` private helpers; updated session/repository rows in `render_session_review` and `render_session_browser`.

- [ ] **Step 1: Write failing renderer tests**

First extend the existing model import at the top of `tests/unit/interactive/test_render.py` (currently `from agent_worklog.models.session import AgentSession`, test_render.py:24):

```python
from agent_worklog.models.session import ActivityType, AgentSession, SessionActivity
```

Then append these definitions and tests to the file (no import statements — the added imports go only in the top block above):

```python
def _dense_resolved(
    session_id: str,
    repo: str,
    *,
    last_day: int,
    volume: int,
    subagent: bool = False,
) -> ResolvedSession:
    activities = [
        SessionActivity(
            activity_id=f"{session_id}:m{i}",
            activity_type=ActivityType.USER_MESSAGE if i == 0 else ActivityType.ASSISTANT_MESSAGE,
            timestamp=datetime(2026, 8, last_day, tzinfo=TZ),
            content="hi",
        )
        for i in range(volume)
    ]
    return ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id=session_id,
            title=f"Meta {session_id}",
            parent_session_id="parent" if subagent else None,
            created_at=datetime(2026, 8, last_day, tzinfo=TZ),
            activities=activities,
        ),
        repository=RepositoryIdentity(
            repository_id=repo,
            display_name=repo,
            identity_type=RepositoryIdentityType.PATH_FALLBACK,
            working_directory=f"/tmp/{repo}",
            resolution_method="test",
        ),
    )


def test_session_review_renders_density_and_subagent_tag() -> None:
    console, stream = _console()
    items = [
        _dense("d1", "repo-x", last_day=5, volume=2, subagent=True),
        _dense("d2", "repo-x", last_day=4, volume=1),
    ]
    scan = ScanResult(
        period=_period(),
        candidate_session_count=2,
        loaded_session_count=2,
        failed_session_count=0,
        resolved_sessions=items,
        sessions_by_repository={"repo-x": items},
    )
    state = SelectionState.from_scan(scan)

    render_session_review(console, state, expanded_repositories={"repo-x"}, cursor=1)

    text = stream.getvalue()
    assert "Aug 5 · 2 msgs" in text
    assert "Aug 4 · 1 msgs" in text
    assert "[sub]" in text


def test_session_browser_renders_repository_and_session_density() -> None:
    console, stream = _console()
    items = [
        _dense("d1", "repo-a", last_day=3, volume=1),
        _dense("d2", "repo-a", last_day=5, volume=2),
    ]
    scan = ScanResult(
        period=_period(),
        candidate_session_count=2,
        loaded_session_count=2,
        failed_session_count=0,
        resolved_sessions=items,
        sessions_by_repository={"repo-a": items},
    )

    render_session_browser(console, scan, expanded_repositories={"repo-a"}, cursor=0)

    text = stream.getvalue()
    assert "Aug 3–5 · 3 msgs" in text
    assert "Aug 5 · 2 msgs" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/interactive/test_render.py::test_session_review_renders_density_and_subagent_tag tests/unit/interactive/test_render.py::test_session_browser_renders_repository_and_session_density -v`
Expected: FAIL — the rows print only titles today, no density or `[sub]`.

- [ ] **Step 3: Add the render helpers and wire rows**

In `src/agent_worklog/interactive/render.py`:

3a. Add the density import and the `AgentSession` import to the existing import block (the file already imports `ReportDraft`, `SelectionMark`/`SelectionState`, `DateRange`, and `ScanResult`; do not duplicate them):

```python
from agent_worklog.interactive.density import (
    is_subagent,
    repository_meta,
    session_meta,
)
from agent_worklog.models.session import AgentSession
```

3b. Add `_print_viewport_text` and `_session_row` after `_print_viewport_line`:

```python
def _print_viewport_text(console: Console, text: Text) -> None:
    """Print a pre-composed row, truncating rather than wrapping."""
    console.print(text, no_wrap=True, overflow="ellipsis")


def _session_row(
    session: AgentSession,
    *,
    prefix: str,
    mark: str | None,
    title: str,
    selected: bool,
) -> Text:
    """Compose one session row with dim subagent/density metadata before the title."""
    row_style = "bold" if selected else ""
    text = Text(prefix, style=row_style)
    if mark is not None:
        text.append(f"     {mark}", style=row_style)
    else:
        text.append("     ", style=row_style)
    tag: list[str] = []
    if is_subagent(session):
        tag.append("[sub]")
    density = session_meta(session)
    if density:
        tag.append(density)
    if tag:
        text.append(f" {' '.join(tag)}", style="dim")
    text.append(f" {title}", style=row_style)
    return text
```

3c. Add a session-lookup helper near `_session_titles`:

```python
def _sessions_by_id(scan: ScanResult) -> dict[str, AgentSession]:
    return {
        item.session.session_id: item.session for item in scan.resolved_sessions
    }
```

3d. In `render_session_review`, after `titles = _session_titles(selection.scan)` and before the loop, add `sessions = _sessions_by_id(selection.scan)`.

Replace the session-row branch (render.py:238-245 today):

```python
        else:
            assert row.session_id is not None
            mark = "●" if row.session_id in selection.selected_session_ids else "○"
            _print_viewport_text(
                console,
                _session_row(
                    sessions[row.session_id],
                    prefix=prefix,
                    mark=mark,
                    title=titles[row.session_id],
                    selected=index == cursor,
                ),
            )
```

Replace the repository-row tail (render.py:233-237 today) to append dim metadata:

```python
            text = Text(
                f"{prefix} {arrow} {mark} {name}   {selected} / {total}",
                style="bold" if index == cursor else "",
            )
            density = repository_meta(row.repository_id, selection.scan)
            if density:
                text.append(f"   {density}", style="dim")
            _print_viewport_text(console, text)
```

3e. In `render_session_browser`, after `titles = _session_titles(scan)` add `sessions = _sessions_by_id(scan)`.

Replace the repository-row branch (render.py:292-296 today):

```python
            text = Text(
                f"{prefix} {arrow} {name}   {count}",
                style="bold" if index == cursor else "",
            )
            density = repository_meta(row.repository_id, scan)
            if density:
                text.append(f"   {density}", style="dim")
            _print_viewport_text(console, text)
```

Replace the session-row branch (render.py:298-303 today):

```python
            assert row.session_id is not None
            _print_viewport_text(
                console,
                _session_row(
                    sessions[row.session_id],
                    prefix=prefix,
                    mark=None,
                    title=titles[row.session_id],
                    selected=index == cursor,
                ),
            )
```

- [ ] **Step 4: Run the full interactive render suite to verify pass + no regressions**

Run: `uv run pytest tests/unit/interactive/test_render.py -v`
Expected: PASS — new density assertions appear; all existing assertions (markers, titles, footers, `◐ repo-a`, `Work on ses-a1`, etc.) still pass because non-dated sessions produce no density.

Run the rest of the interactive tests to catch regressions from the shared helper use:

`uv run pytest tests/unit/interactive -v`
Expected: PASS.

- [ ] **Step 5: Type-check and lint**

```bash
uv run pyright
uv run ruff check src/agent_worklog/interactive/render.py src/agent_worklog/interactive/density.py tests/unit/interactive/test_density.py tests/unit/interactive/test_render.py
```
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/agent_worklog/interactive/render.py tests/unit/interactive/test_render.py
git commit -m "feat: surface session density in interactive rows"
```

---

## Task 3: Documentation and changelog

**Files:**
- Modify: `docs/p0-interactive-ux-design.md` (Session Review + Browse mocks and prose)
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update the Session Review mock in `docs/p0-interactive-ux-design.md`**

Replace the block under `## Screen 3: Session Review` (render today at lines ~289-310) with a version whose rows carry density metadata:

```text
 Review Sessions                         15 / 18 selected

 ▼ ● agent-worklog                         8 / 9   Aug 3–8 · 24 msgs
      ● Aug 3 · 4 msgs  Fix sanitize export
      ❯ ● [sub] Aug 5 · 3 msgs  Add interactive menu
      ○ Aug 4 · 2 msgs  Scratch parser debugging
      ● Aug 3 · 1 msgs  Release v0.8.0

 ▶ ● assets-tracker                        5 / 5   Aug 4–7 · 96 msgs

 ▼ ◐ obsidian-wiki                         2 / 4   Jul 30 – Aug 4 · 40 msgs
      ● [sub] Aug 4 · 3 msgs  Improve wiki synthesis
      ○ Aug 3 · 2 msgs  Test prompt
      ● Aug 2 · 3 msgs  Update docs
      ○ [sub] Aug 1 · 1 msgs  Scratch session

 ↑↓ Navigate   Space Toggle   Enter Expand
 a All   n None   g Generate   b Back
```

Add one sentence after the mockup paragraph:

> Each session row carries a dim date and message count (the in-period
> conversation volume) ahead of its title, so a session's activity and recency
> are visible without opening it. A `[sub]` tag marks sessions spawned by a
> parent session. Repository rows append a date span and summed message count.

- [ ] **Step 2: Add a density note to the Browse Sessions prose in the same file**

Under the `## Browse Sessions` section (today at lines ~385-387), the P0 paragraph ends with:
"Browse Sessions is read-only in P0 and does not transfer its scan directly into Generate Report."
Append a new sentence after that paragraph, keeping the existing prose untouched:

> Browse Sessions uses the same grouped renderer and metadata as Session Review —
> a date and message count per session, and a date span and message total per
> repository — so the read-only record carries the same decision signals.

- [ ] **Step 3: Add an `Unreleased` entry to `CHANGELOG.md`**

After the `# Changelog` intro line (CHANGELOG.md:4), insert:

```markdown
## Unreleased

- Session review and browse rows now show density — a dim date and message count
  per session (the conversation actually recorded in the report period), a `[sub]`
  tag for subagent sessions, and a date span plus message total per repository —
  so the interactive screens carry enough signal to judge whether a session
  belongs in the weekly report without opening it.

## 0.8.0 - 2026-08-07
```

(If a `## Unreleased` section already exists, append the bullet under it instead
and skip the header insert.)

- [ ] **Step 4: Verify the doc edits render**

Run: `uv run pytest tests/unit/test_documentation.py -v`
Expected: PASS (docs lint test, if present, still passes.)

- [ ] **Step 5: Commit**

```bash
git add docs/p0-interactive-ux-design.md CHANGELOG.md
git commit -m "docs: document interactive row density"
```

---

## Task 4: Final verification

- [ ] **Step 1: Run the full test suite**

`uv run pytest -q`
Expected: all tests pass.

- [ ] **Step 2: Review the diff**

```bash
git diff main --stat
git status --short
```
Intent: three commits (module+tests, render wiring, docs+changelog), nothing left unplanned.

- [ ] **Step 3: Manual smoke check (optional)**

If a TTY is available: `uv run agent-worklog` → Generate Report → Review sessions — confirm rows show `Aug 5 · 12 msgs`-style density, `[sub]` on subagent rows, and the browser shows repo spans. `q` to quit cleanly.