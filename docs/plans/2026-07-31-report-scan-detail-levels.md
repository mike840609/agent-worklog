# Report and Scan Detail Levels Implementation Plan

**Goal:** Add `report --detail brief|full` so a worklog can be produced as a short bulleted digest, and extend `scan --verbose` to list the sessions it selected.

**Architecture:** Report list truncation moves out of `RuleBasedSummarizer` and into `MarkdownRenderer`, giving one truncation point whose omitted-item counts are always correct. The renderer then takes a detail level that selects the per-section item limit and gates the appendix sections and the Usage block. `scan` gains no option; its existing `--verbose` branch prints one line per session.

**Tech Stack:** Python 3.11+, Typer, Jinja2, Rich, Pydantic, pytest, ruff, pyright, uv.

**Spec:** `docs/report-scan-detail-levels-design.md`

## Global Constraints

- Python 3.11+; `from __future__ import annotations` is used in modules that need
  it, matching each file's existing header.
- ruff line-length is 100, `target-version = "py311"`, lint rules `E, F, I, UP, B, SIM`.
- pyright runs in `standard` mode over `src` only.
- ruff's B008 rejects a `typer.Option(...)` call as an inline default when its
  type is an enum. Enum-typed options MUST be constructed once as a module-level
  singleton, following the existing `_HARNESS_OPTION` in `src/agent_worklog/cli.py:48`.
- `ConsoleReporter`'s contract is that callers pass already-redacted strings
  (`src/agent_worklog/logging.py:80`). Any new session-derived text printed to
  the console must pass through `redact_text` first.
- Rich's `console.print` interprets `[...]` as markup. Any string containing
  user or session content must be printed with `markup=False`.
- Run all commands from the repository root. Tests run with `uv run pytest`.

## Two Corrections to the Spec

The spec says the `DetailLevel` enum lives in `cli.py`. It cannot: `cli.py`
imports `MarkdownRenderer`, so `markdown.py` importing `DetailLevel` from
`cli.py` is an import cycle. The enum lives in `src/agent_worklog/renderers/markdown.py`
and `cli.py` imports it.

The spec's `scan --verbose` section does not mention redaction. Session titles
and working directories are raw harness data on the Claude Code path, which has
no upstream `--sanitize` step. They pass through `redact_text` before printing,
per the `ConsoleReporter` contract.

## File Structure

| File | Responsibility | Task |
| --- | --- | --- |
| `src/agent_worklog/renderers/markdown.py` | Owns `DetailLevel`, the per-level item limits, and the template context | 1, 2 |
| `src/agent_worklog/templates/worklog.md.j2` | One `section` macro; limit and overflow line; level gating | 1, 2 |
| `src/agent_worklog/summarizers/rule_based.py` | Emits complete deduplicated lists; no longer truncates | 1 |
| `src/agent_worklog/services/report.py` | Threads the detail level to the renderer | 2 |
| `src/agent_worklog/cli.py` | `--detail` option and passthrough | 2 |
| `src/agent_worklog/logging.py` | `scan --verbose` session listing | 3 |
| `tests/unit/renderers/test_markdown.py` | Golden full output, truncation, brief gating | 1, 2 |
| `tests/unit/summarizers/test_rule_based.py` | Completeness, not truncation | 1 |
| `tests/integration/test_cli.py` | `--detail` passthrough and composition | 2 |
| `tests/unit/test_logging.py` | Scan verbose listing | 3 |
| `tests/unit/test_documentation.py` | README coverage of both features | 2, 3 |

---

### Task 1: Move truncation from the summarizer into the renderer

`RuleBasedSummarizer._limited` caps lists at 20 and appends the literal string
`Additional items omitted: N` as an extra list item. `OpenAICompatibleSummarizer`
applies no cap at all. Task 2 needs a second, smaller cap at 5; layering it on
top of a list that already contains a synthetic marker item would produce a wrong
count and would count the marker as a work item. This task makes the renderer the
only place that truncates.

Full-mode output must not change, except that a previously unbounded LLM list
longer than 20 items is now capped.

**Files:**
- Modify: `src/agent_worklog/summarizers/rule_based.py:16-36` (delete `_MAX_ITEMS` and `_limited`), `:112-114` (call sites)
- Modify: `src/agent_worklog/renderers/markdown.py`
- Modify: `src/agent_worklog/templates/worklog.md.j2`
- Test: `tests/unit/renderers/test_markdown.py`, `tests/unit/summarizers/test_rule_based.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `MarkdownRenderer.render(report: WorklogReport) -> str` (signature
  unchanged in this task); a Jinja macro
  `section(heading, items, limit, code=false)` in `worklog.md.j2`; a
  `section_limit` integer in the template context. Task 2 replaces the fixed
  limit with a per-level one and adds a `full` boolean to the same context.

- [ ] **Step 1: Write the golden full-output test**

This is a characterization test for a refactor. Unlike the other tests in this
plan it is expected to **pass before** the change; its job is to fail if the
refactor alters whitespace or ordering.

Append to `tests/unit/renderers/test_markdown.py`:

```python
def test_full_output_is_unchanged_byte_for_byte() -> None:
    """Characterization guard for the truncation refactor.

    The macro rewrite in worklog.md.j2 is a pure whitespace hazard: Jinja's
    trim_blocks and lstrip_blocks make blank lines easy to gain or lose. This
    pins the exact bytes so any drift fails loudly.
    """

    output = MarkdownRenderer().render(sample_report())

    assert output == EXPECTED_FULL_OUTPUT
```

- [ ] **Step 2: Generate the expected string**

Run this and paste its output into `tests/unit/renderers/test_markdown.py` as a
module-level `EXPECTED_FULL_OUTPUT = """..."""` constant, placed directly below
the `sample_report` function:

```bash
uv run python -c "
import sys; sys.path.insert(0, 'tests/unit/renderers')
from test_markdown import sample_report
from agent_worklog.renderers.markdown import MarkdownRenderer
print(repr(MarkdownRenderer().render(sample_report())))
"
```

Read the generated string before pasting it. It must contain
`# Engineering Worklog`, `### Agent Worklog`, `#### Completed`,
`#### Directories`, `#### Sessions`, `#### Branches`, and `## Warnings`, and it
must NOT contain `#### Problems Resolved` (the sample has none). Prefer a triple-quoted
string over the `repr` form for readability, but only if you keep the bytes identical.

- [ ] **Step 3: Run the golden test to confirm it passes against current code**

Run: `uv run pytest tests/unit/renderers/test_markdown.py::test_full_output_is_unchanged_byte_for_byte -v`
Expected: PASS. If it fails, the pasted string is wrong — fix the string, not the renderer.

- [ ] **Step 4: Write the failing test for renderer-side truncation**

Append to `tests/unit/renderers/test_markdown.py`:

```python
def report_with_completed(items: list[str]) -> WorklogReport:
    return WorklogReport(
        generated_at=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
        period=DateRange(
            since=datetime(2026, 7, 20, tzinfo=TZ),
            until=datetime(2026, 7, 27, tzinfo=TZ),
        ),
        repositories=[
            RepositorySummary(
                repository_id="repo",
                display_name="Repo",
                summary="Worked.",
                completed=items,
                session_count=1,
            )
        ],
    )


def test_full_caps_a_long_section_at_twenty_items() -> None:
    items = [f"Completed {index:02d}" for index in range(25)]

    output = MarkdownRenderer().render(report_with_completed(items))

    assert "- Completed 19" in output
    assert "- Completed 20" not in output
    assert "- Additional items omitted: 5" in output


def test_a_section_at_exactly_the_limit_has_no_overflow_line() -> None:
    items = [f"Completed {index:02d}" for index in range(20)]

    output = MarkdownRenderer().render(report_with_completed(items))

    assert "- Completed 19" in output
    assert "Additional items omitted" not in output
```

`test_full_caps_a_long_section_at_twenty_items` covers the previously unbounded
LLM path: this report is built directly, never through `RuleBasedSummarizer`.

- [ ] **Step 5: Run the new tests to verify they fail**

Run: `uv run pytest tests/unit/renderers/test_markdown.py -v -k "caps_a_long_section or exactly_the_limit"`
Expected: `test_full_caps_a_long_section_at_twenty_items` FAILS — `- Completed 20`
is present and no overflow line is rendered, because nothing truncates yet.
`test_a_section_at_exactly_the_limit_has_no_overflow_line` already passes.

- [ ] **Step 6: Remove truncation from the summarizer**

In `src/agent_worklog/summarizers/rule_based.py`, delete the `_MAX_ITEMS`
constant and the entire `_limited` function, then change the three call sites in
`summarize` to use `_unique_sorted` directly:

```python
            completed=_unique_sorted(completed),
            in_progress=_unique_sorted(in_progress),
            key_files=_unique_sorted(key_files),
```

Leave `_unique_sorted`, `_completed`, `_unobserved`, and everything else in the
file untouched.

- [ ] **Step 7: Add the limit to the renderer context**

Replace the body of `src/agent_worklog/renderers/markdown.py` with:

```python
"""Markdown rendering for worklog reports."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from agent_worklog.models.report import WorklogReport

# The renderer is the report's only truncation point. Both summarizers now emit
# complete lists, so the omitted-item count below is always the real remainder.
_FULL_SECTION_LIMIT = 20


class MarkdownRenderer:
    """Render a WorklogReport using the bundled safe summary template."""

    def __init__(self) -> None:
        template_directory = Path(__file__).parents[1] / "templates"
        environment = Environment(
            loader=FileSystemLoader(template_directory),
            undefined=StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )
        self._template = environment.get_template("worklog.md.j2")

    def render(self, report: WorklogReport) -> str:
        tzinfo = report.period.since.tzinfo
        timezone = getattr(tzinfo, "key", str(tzinfo))
        output = self._template.render(
            report=report,
            timezone=timezone,
            section_limit=_FULL_SECTION_LIMIT,
        )
        return f"{output.rstrip()}\n"
```

- [ ] **Step 8: Rewrite the template with one section macro**

Replace `src/agent_worklog/templates/worklog.md.j2` with:

```jinja
{% macro section(heading, items, limit, code=false) %}
{% if items %}

#### {{ heading }}
{% for item in items[:limit] %}
- {{ ("`" ~ item ~ "`") if code else item }}
{% endfor %}
{% if limit and items|length > limit %}
- Additional items omitted: {{ items|length - limit }}
{% endif %}
{% endif %}
{% endmacro %}
# Engineering Worklog

**Period:** {{ report.period.since.strftime("%Y-%m-%d %H:%M") }} – {{ report.period.until.strftime("%Y-%m-%d %H:%M") }}
**Timezone:** {{ timezone }}
**Generated:** {{ report.generated_at.strftime("%Y-%m-%d %H:%M") }}

## Repositories
{% for repository in report.repositories %}
### {{ repository.display_name }}
{% if repository.normalized_remote %}
Repository: `{{ repository.normalized_remote }}`
{% endif %}

{{ repository.summary }}

Sessions: {{ repository.session_count }}{% if repository.child_session_count %} · Child sessions: {{ repository.child_session_count }}{% endif %}
{{ section("Completed", repository.completed, section_limit) -}}
{{ section("Problems Resolved", repository.problems_resolved, section_limit) -}}
{{ section("In Progress", repository.in_progress, section_limit) -}}
{{ section("Key Files", repository.key_files, section_limit, code=true) -}}
{{ section("Directories", repository.directories, none, code=true) -}}
{% if repository.sessions %}

#### Sessions
{% for item in repository.sessions %}
- {{ item.title or item.session_id }} — `{{ item.session_id }}`
{% endfor %}
{% endif %}
{{ section("Branches", repository.branches, none, code=true) }}

{% endfor %}
{% if report.usage_text %}
## Usage
{% if report.usage_days %}

Window: the last {{ report.usage_days }} days ending at generation time. It contains the
report period but does not match it exactly, because OpenCode reports usage only for a
window ending now.
{% endif %}

```text
{{ report.usage_text }}
```
{% endif %}
{% if report.warnings %}
## Warnings
{% for warning in report.warnings %}
- {{ warning }}
{% endfor %}
{% endif %}
```

Three details that keep the output bytes identical:

- `Directories` and `Branches` are uncapped today and stay uncapped, so they pass
  `none` as the limit. Jinja's `items[:none]` is the whole list, and the
  `{% if limit and ... %}` guard on the overflow line keeps `items|length > none`
  from raising.
- `Key Files` was capped at 20 by the summarizer and is now capped at 20 by the
  renderer, so it passes `section_limit`. Same for `Completed`, `In Progress`,
  and `Problems Resolved`.
- The `Sessions` block keeps its own `{% for %}`. Its items are `SessionRef`
  objects rendered as `title — \`session_id\``, not plain strings, so the macro
  does not fit. `session_refs` in `src/agent_worklog/summarizers/base.py:23`
  documents why it must stay uncapped.

- [ ] **Step 9: Run the full renderer suite and fix whitespace**

Run: `uv run pytest tests/unit/renderers/test_markdown.py -v`
Expected: all tests PASS.

If the golden test fails on blank lines, adjust Jinja whitespace control on the
macro-call lines and inside the macro (`{%-`, `-%}`, `-}}`) until it passes.
**Do not edit `EXPECTED_FULL_OUTPUT` to match the new behavior** — that string is
the contract. The `-}}` on each macro call exists because `{{ ... }}` is not a
block tag, so `trim_blocks` does not remove the newline that follows it; without
`-}}` every section gains a blank line. The final `Branches` call deliberately
uses plain `}}` so the blank line separating repositories survives.

- [ ] **Step 10: Replace the summarizer truncation test**

In `tests/unit/summarizers/test_rule_based.py`, delete
`test_rule_summary_limits_each_section_to_twenty_items` (lines 52-75) and add in
its place:

```python
def test_rule_summary_returns_complete_deduplicated_sorted_lists() -> None:
    """Truncation belongs to the renderer, which is the report's only cap."""

    evidence = RepositoryEvidence(
        repository_id="repo",
        display_name="Repo",
        sessions=[
            SessionEvidence(
                session_id="s1",
                repository_id="repo",
                outcomes=[
                    item(
                        f"Completed {index:02d}",
                        EvidenceStatus.COMPLETED,
                        EvidenceConfidence.HIGH,
                    )
                    for index in range(22)
                ]
                + [
                    item(
                        "Completed 00",
                        EvidenceStatus.COMPLETED,
                        EvidenceConfidence.HIGH,
                    )
                ],
            )
        ],
    )

    summary = RuleBasedSummarizer().summarize(evidence)

    assert len(summary.completed) == 22
    assert summary.completed[0] == "Completed 00"
    assert summary.completed[-1] == "Completed 21"
    assert not any("Additional items omitted" in text for text in summary.completed)
```

- [ ] **Step 11: Run the whole suite and the linters**

Run: `uv run pytest`
Expected: all tests PASS.

Run: `uv run ruff check . && uv run ruff format --check . && uv run pyright`
Expected: clean.

If an integration test in `tests/integration/` asserts on a report body that had
more than 20 items in a section, it was previously relying on the summarizer's
cap and now sees the renderer's — the rendered output is the same, so any failure
here means a real behavior difference worth reading carefully before changing the test.

- [ ] **Step 12: Add the CHANGELOG entry**

Add to the `## Unreleased` list in `CHANGELOG.md`:

```markdown
- Move report list truncation from the rule-based summarizer into the Markdown
  renderer, so there is one truncation point and the `Additional items omitted`
  count is always the real remainder. LLM-produced lists are now capped at 20
  items like rule-based ones; they were previously unbounded.
```

- [ ] **Step 13: Commit**

```bash
git add src/agent_worklog/summarizers/rule_based.py \
        src/agent_worklog/renderers/markdown.py \
        src/agent_worklog/templates/worklog.md.j2 \
        tests/unit/renderers/test_markdown.py \
        tests/unit/summarizers/test_rule_based.py \
        CHANGELOG.md
git commit -m "refactor: make the renderer the report's only truncation point"
```

---

### Task 2: Add `report --detail brief|full`

**Files:**
- Modify: `src/agent_worklog/renderers/markdown.py` (add `DetailLevel`, per-level limits, `detail` parameter)
- Modify: `src/agent_worklog/services/report.py:25-27` (`Renderer` protocol), `:46-67` (constructor), `:139-140` (render call)
- Modify: `src/agent_worklog/cli.py` (option singleton, `report` signature, `_build_report_service`)
- Modify: `src/agent_worklog/templates/worklog.md.j2` (level gating)
- Test: `tests/unit/renderers/test_markdown.py`, `tests/integration/test_cli.py`, `tests/unit/test_documentation.py`
- Modify: `README.md`, `README.zh-TW.md`, `CHANGELOG.md`

**Interfaces:**
- Consumes: `MarkdownRenderer.render`, the `section` macro, and the
  `section_limit` context variable from Task 1.
- Produces: `DetailLevel` (a `StrEnum` in `agent_worklog.renderers.markdown` with
  members `BRIEF = "brief"` and `FULL = "full"`);
  `MarkdownRenderer.render(report: WorklogReport, *, detail: DetailLevel = DetailLevel.FULL) -> str`;
  `ReportService(..., detail: DetailLevel = DetailLevel.FULL)`; a `full` boolean
  in the template context.

- [ ] **Step 1: Write the failing brief-mode renderer tests**

Append to `tests/unit/renderers/test_markdown.py` (add `DetailLevel` to the
existing `from agent_worklog.renderers.markdown import ...` line):

```python
def test_brief_keeps_the_narrative_sections_and_drops_the_appendices() -> None:
    output = MarkdownRenderer().render(sample_report(), detail=DetailLevel.BRIEF)

    assert "# Engineering Worklog" in output
    assert "### Agent Worklog" in output
    assert "Implemented the MVP." in output
    assert "Sessions: 2" in output
    assert "#### Completed" in output
    assert "#### In Progress" in output

    assert "#### Key Files" not in output
    assert "#### Directories" not in output
    assert "#### Sessions" not in output
    assert "#### Branches" not in output


def test_brief_keeps_warnings() -> None:
    """A shorter report is a request for less detail, not less disclosure."""

    output = MarkdownRenderer().render(sample_report(), detail=DetailLevel.BRIEF)

    assert "## Warnings" in output
    assert "One session could not be exported." in output


def test_brief_drops_the_usage_block() -> None:
    report = sample_report()
    report.usage_text = "OVERVIEW\nSessions 2"
    report.usage_days = 5

    output = MarkdownRenderer().render(report, detail=DetailLevel.BRIEF)

    assert "## Usage" not in output
    assert "OVERVIEW" not in output
    assert "Window: the last" not in output


def test_full_keeps_the_usage_block() -> None:
    report = sample_report()
    report.usage_text = "OVERVIEW\nSessions 2"
    report.usage_days = 5

    output = MarkdownRenderer().render(report, detail=DetailLevel.FULL)

    assert "## Usage" in output
    assert "OVERVIEW" in output


def test_brief_caps_sections_at_five_items() -> None:
    items = [f"Completed {index:02d}" for index in range(25)]

    output = MarkdownRenderer().render(
        report_with_completed(items),
        detail=DetailLevel.BRIEF,
    )

    assert "- Completed 04" in output
    assert "- Completed 05" not in output
    assert "- Additional items omitted: 20" in output


def test_brief_default_is_full() -> None:
    assert MarkdownRenderer().render(sample_report()) == EXPECTED_FULL_OUTPUT
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/renderers/test_markdown.py -v -k "brief or keeps_the_usage"`
Expected: collection FAILS with `ImportError: cannot import name 'DetailLevel'`.

- [ ] **Step 3: Add `DetailLevel` and the per-level limits to the renderer**

In `src/agent_worklog/renderers/markdown.py`, add the `StrEnum` import, replace
`_FULL_SECTION_LIMIT` with a per-level mapping, and add the parameter.

`DetailLevel` lives here rather than in `cli.py` because `cli.py` already imports
`MarkdownRenderer`; defining it in `cli.py` and importing it back into the
renderer would be an import cycle.

```python
"""Markdown rendering for worklog reports."""

from enum import StrEnum
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from agent_worklog.models.report import WorklogReport


class DetailLevel(StrEnum):
    BRIEF = "brief"
    FULL = "full"


# The renderer is the report's only truncation point. Both summarizers now emit
# complete lists, so the omitted-item count is always the real remainder.
_SECTION_LIMITS = {
    DetailLevel.FULL: 20,
    DetailLevel.BRIEF: 5,
}
```

Then change `render`:

```python
    def render(
        self,
        report: WorklogReport,
        *,
        detail: DetailLevel = DetailLevel.FULL,
    ) -> str:
        tzinfo = report.period.since.tzinfo
        timezone = getattr(tzinfo, "key", str(tzinfo))
        output = self._template.render(
            report=report,
            timezone=timezone,
            section_limit=_SECTION_LIMITS[detail],
            full=detail is DetailLevel.FULL,
        )
        return f"{output.rstrip()}\n"
```

A plain `full` boolean goes into the context rather than the enum itself, so the
template never has to compare enum members.

- [ ] **Step 4: Gate the appendix sections and Usage in the template**

In `src/agent_worklog/templates/worklog.md.j2`, wrap the Key Files, Directories,
Sessions, and Branches output in `{% if full %}`, and wrap the whole Usage block
in the same. The repository body becomes:

```jinja
{{ section("Completed", repository.completed, section_limit) -}}
{{ section("Problems Resolved", repository.problems_resolved, section_limit) -}}
{{ section("In Progress", repository.in_progress, section_limit) -}}
{% if full %}
{{ section("Key Files", repository.key_files, section_limit, code=true) -}}
{{ section("Directories", repository.directories, none, code=true) -}}
{% if repository.sessions %}

#### Sessions
{% for item in repository.sessions %}
- {{ item.title or item.session_id }} — `{{ item.session_id }}`
{% endfor %}
{% endif %}
{{ section("Branches", repository.branches, none, code=true) }}
{% endif %}

{% endfor %}
```

and the Usage block becomes:

```jinja
{% if full and report.usage_text %}
## Usage
```

The Warnings block is left exactly as it is — it renders at both levels.

Note the blank line before `{% endfor %}` now sits outside the `{% if full %}`,
so repositories stay separated in brief mode too.

- [ ] **Step 5: Run the renderer tests**

Run: `uv run pytest tests/unit/renderers/test_markdown.py -v`
Expected: all PASS, including `test_full_output_is_unchanged_byte_for_byte` and
`test_brief_default_is_full`. If the golden test now fails, the `{% if full %}`
wrapper changed full-mode whitespace — fix the template, not the expected string.

- [ ] **Step 6: Thread the level through `ReportService`**

In `src/agent_worklog/services/report.py`:

Add the import:

```python
from agent_worklog.renderers.markdown import DetailLevel, MarkdownRenderer
```

Update the protocol so both branches of the `Renderer | MarkdownRenderer`
annotation accept the keyword:

```python
class Renderer(Protocol):
    def render(
        self,
        report: WorklogReport,
        *,
        detail: DetailLevel = DetailLevel.FULL,
    ) -> str: ...
```

Add the constructor parameter after `usage_days`:

```python
        detail: DetailLevel = DetailLevel.FULL,
```

and store it:

```python
        self._detail = detail
```

Change the render call in `generate`:

```python
        content = redact_text(self._renderer.render(report, detail=self._detail))
```

- [ ] **Step 7: Add the CLI option**

In `src/agent_worklog/cli.py`:

Extend the existing renderer import:

```python
from agent_worklog.renderers.markdown import DetailLevel, MarkdownRenderer
```

Add the option singleton directly below `_HARNESS_OPTION` (around line 52). It
must be a module-level singleton for the same reason `_HARNESS_OPTION` is: ruff's
B008 does not accept an enum-typed `typer.Option(...)` call as an inline default.

```python
_DETAIL_OPTION = typer.Option(
    DetailLevel.FULL,
    "--detail",
    help="How much detail the report contains: full (default) or brief.",
)
```

Add the parameter to `_build_report_service`, after `harness`:

```python
    detail: DetailLevel = DetailLevel.FULL,
```

and pass it to `ReportService(...)`, after `usage_days=days`:

```python
        detail=detail,
```

Add the option to the `report` command signature, after `harness`:

```python
    detail: DetailLevel = _DETAIL_OPTION,
```

and pass it in the `_build_report_service(...)` call inside `report`, after
`harness=harness`:

```python
                detail=detail,
```

- [ ] **Step 8: Write the failing CLI tests**

Append to `tests/integration/test_cli.py`:

```python
def test_report_passes_the_detail_level_to_the_report_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def build(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        harness=cli.Harness.OPENCODE,
        progress=None,
        detail=cli.DetailLevel.FULL,
    ):
        captured["detail"] = detail
        return StubReportService(output_path, period)

    monkeypatch.setattr(cli, "_build_report_service", build)

    result = runner.invoke(
        cli.app,
        [
            "report",
            "--days",
            "7",
            "--detail",
            "brief",
            "--dry-run",
            "--output",
            str(tmp_path / "report.md"),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert captured["detail"] is cli.DetailLevel.BRIEF


def test_report_defaults_to_full_detail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def build(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        harness=cli.Harness.OPENCODE,
        progress=None,
        detail=cli.DetailLevel.FULL,
    ):
        captured["detail"] = detail
        return StubReportService(output_path, period)

    monkeypatch.setattr(cli, "_build_report_service", build)

    result = runner.invoke(
        cli.app,
        [
            "report",
            "--days",
            "7",
            "--dry-run",
            "--output",
            str(tmp_path / "report.md"),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert captured["detail"] is cli.DetailLevel.FULL


def test_report_rejects_an_unknown_detail_level(tmp_path: Path) -> None:
    output_path = tmp_path / "report.md"

    result = runner.invoke(
        cli.app,
        ["report", "--days", "7", "--detail", "medium", "--output", str(output_path)],
    )

    assert result.exit_code == 2
    assert not output_path.exists()
```

`cli.DetailLevel` in these tests is the name re-exported by the `from
agent_worklog.renderers.markdown import DetailLevel, MarkdownRenderer` line added
in Step 7.

- [ ] **Step 9: Run the CLI tests**

Run: `uv run pytest tests/integration/test_cli.py -v -k detail`
Expected: all three PASS.

- [ ] **Step 10: Document `--detail` in both READMEs**

In `README.md`, add a row to the `report` also accepts table (below `--no-llm`):

```markdown
| `--detail LEVEL` | How much detail the report contains: `full` (default) or `brief`. |
```

and add this paragraph directly below that table:

```markdown
`--detail brief` produces a short report for a status update: it keeps the
header, and for each repository the summary and up to five each of Completed,
Problems Resolved, and In Progress. It leaves out Key Files, Directories,
Sessions, Branches, and the usage table. Warnings are always kept, at both
detail levels, because they report data the tool could not read rather than work
you did.
```

In `README.zh-TW.md`, add the matching row to the `report` 另外還接受 table:

```markdown
| `--detail LEVEL` | 報告的詳細程度：`full`（預設）或 `brief`。 |
```

and the matching paragraph below it:

```markdown
`--detail brief` 會產生適合貼進週報的簡短報告：保留標頭，每個 repository 保留摘要與
Completed、Problems Resolved、In Progress 各最多五條，不輸出 Key Files、Directories、
Sessions、Branches 與用量表格。警告在兩種詳細程度下都會保留，因為警告說明的是工具讀不到的
資料，而不是你做過的工作。
```

- [ ] **Step 11: Add the documentation test**

Append to `tests/unit/test_documentation.py`:

```python
def test_readmes_document_the_report_detail_option() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh_tw = Path("README.zh-TW.md").read_text(encoding="utf-8")

    assert "`--detail LEVEL`" in readme
    assert "`--detail brief`" in readme
    assert "`--detail LEVEL`" in readme_zh_tw
    assert "`--detail brief`" in readme_zh_tw
```

- [ ] **Step 12: Run the whole suite and the linters**

Run: `uv run pytest`
Expected: all PASS.

Run: `uv run ruff check . && uv run ruff format --check . && uv run pyright`
Expected: clean. If pyright reports the `Renderer` protocol is not satisfied,
the protocol signature in `services/report.py` and `MarkdownRenderer.render` have
drifted — they must both be keyword-only `detail` with the same default.

- [ ] **Step 13: Add the CHANGELOG entry**

Add to the `## Unreleased` list in `CHANGELOG.md`:

```markdown
- Add `--detail {full,brief}` to `report`, defaulting to `full`, which is the
  existing output. `--detail brief` keeps the header, and for each repository the
  summary and up to five each of Completed, Problems Resolved, and In Progress;
  it leaves out Key Files, Directories, Sessions, Branches, and the usage table.
  Warnings are kept at both levels.
```

- [ ] **Step 14: Commit**

```bash
git add src/agent_worklog/renderers/markdown.py \
        src/agent_worklog/services/report.py \
        src/agent_worklog/cli.py \
        src/agent_worklog/templates/worklog.md.j2 \
        tests/unit/renderers/test_markdown.py \
        tests/integration/test_cli.py \
        tests/unit/test_documentation.py \
        README.md README.zh-TW.md CHANGELOG.md
git commit -m "feat: add report --detail brief|full"
```

---

### Task 3: List selected sessions under `scan --verbose`

`scan` gains no option. Its `--verbose` flag already means "show me more" and
today adds only warnings. Every value needed is already on `ScanResult`, so no
service, source, or model changes are required.

**Files:**
- Modify: `src/agent_worklog/logging.py:120-134`
- Test: `tests/unit/test_logging.py`, `tests/unit/test_documentation.py`
- Modify: `README.md`, `README.zh-TW.md`, `CHANGELOG.md`

**Interfaces:**
- Consumes: nothing from Tasks 1 and 2. This task is independent and may be done
  in any order relative to them.
- Produces: no new public names. `ConsoleReporter.scan_result(result: ScanResult) -> None`
  keeps its signature.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_logging.py`. Note the imports these need at the top of
the file:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from agent_worklog.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from agent_worklog.models.session import AgentSession
from agent_worklog.models.time_range import DateRange
from agent_worklog.services.scan import ScanResult
```

and the tests:

```python
SCAN_TZ = ZoneInfo("Asia/Taipei")


def scan_result_with(sessions: list[AgentSession]) -> ScanResult:
    identity = RepositoryIdentity(
        repository_id="git:github.com/mike/agent-worklog",
        display_name="Agent Worklog",
        identity_type=RepositoryIdentityType.GIT_REMOTE,
        normalized_remote="github.com/mike/agent-worklog",
        resolution_method="test",
    )
    resolved = [
        ResolvedSession(session=session, repository=identity) for session in sessions
    ]
    return ScanResult(
        period=DateRange(
            since=datetime(2026, 7, 20, tzinfo=SCAN_TZ),
            until=datetime(2026, 7, 27, tzinfo=SCAN_TZ),
        ),
        candidate_session_count=len(sessions),
        loaded_session_count=len(sessions),
        failed_session_count=0,
        resolved_sessions=resolved,
        sessions_by_repository={"git:github.com/mike/agent-worklog": resolved},
        warnings=["One session could not be exported."],
    )


def test_verbose_scan_lists_session_titles_and_directories() -> None:
    output_stream = StringIO()
    reporter = ConsoleReporter(
        verbose=True,
        console=forced_console(output_stream, width=200),
    )

    reporter.scan_result(
        scan_result_with(
            [
                AgentSession(
                    harness="opencode",
                    session_id="ses_abc",
                    title="Fix the exporter",
                    working_directory="/repos/agent-worklog",
                )
            ]
        )
    )

    output = output_stream.getvalue()
    assert "Fix the exporter" in output
    assert "/repos/agent-worklog" in output
    assert "One session could not be exported." in output


def test_a_session_without_a_title_falls_back_to_its_id() -> None:
    output_stream = StringIO()
    reporter = ConsoleReporter(
        verbose=True,
        console=forced_console(output_stream, width=200),
    )

    reporter.scan_result(
        scan_result_with(
            [AgentSession(harness="opencode", session_id="ses_def")]
        )
    )

    assert "ses_def" in output_stream.getvalue()


def test_non_verbose_scan_does_not_list_sessions() -> None:
    output_stream = StringIO()
    reporter = ConsoleReporter(console=forced_console(output_stream, width=200))

    reporter.scan_result(
        scan_result_with(
            [
                AgentSession(
                    harness="opencode",
                    session_id="ses_abc",
                    title="Fix the exporter",
                    working_directory="/repos/agent-worklog",
                )
            ]
        )
    )

    output = output_stream.getvalue()
    assert "Agent Worklog" in output
    assert "Fix the exporter" not in output


def test_quiet_scan_still_prints_only_the_count() -> None:
    output_stream = StringIO()
    reporter = ConsoleReporter(
        quiet=True,
        verbose=False,
        console=forced_console(output_stream, width=200),
    )

    reporter.scan_result(
        scan_result_with(
            [
                AgentSession(
                    harness="opencode",
                    session_id="ses_abc",
                    title="Fix the exporter",
                )
            ]
        )
    )

    assert output_stream.getvalue().strip() == "1"


def test_verbose_scan_redacts_secrets_in_session_titles() -> None:
    """Claude Code transcripts have no upstream sanitize step.

    ConsoleReporter's contract is that callers hand it redacted strings, and a
    scanned title is raw harness data, so the listing must redact it here.
    """

    output_stream = StringIO()
    reporter = ConsoleReporter(
        verbose=True,
        console=forced_console(output_stream, width=200),
    )

    reporter.scan_result(
        scan_result_with(
            [
                AgentSession(
                    harness="claude-code",
                    session_id="ses_ghi",
                    title="debug with token=hunter2secretvalue",
                    working_directory="/repos/agent-worklog",
                )
            ]
        )
    )

    output = output_stream.getvalue()
    assert "hunter2secretvalue" not in output
    assert "[REDACTED]" in output


def test_verbose_scan_does_not_interpret_a_title_as_rich_markup() -> None:
    """A title is user content; Rich would otherwise eat anything in brackets."""

    output_stream = StringIO()
    reporter = ConsoleReporter(
        verbose=True,
        console=forced_console(output_stream, width=200),
    )

    reporter.scan_result(
        scan_result_with(
            [
                AgentSession(
                    harness="opencode",
                    session_id="ses_jkl",
                    title="[bold]not markup[/bold]",
                )
            ]
        )
    )

    assert "[bold]not markup[/bold]" in output_stream.getvalue()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_logging.py -v -k "scan"`
Expected: `test_verbose_scan_lists_session_titles_and_directories`,
`test_a_session_without_a_title_falls_back_to_its_id`,
`test_verbose_scan_redacts_secrets_in_session_titles`, and
`test_verbose_scan_does_not_interpret_a_title_as_rich_markup` FAIL — the titles
are never printed. The `non_verbose` and `quiet` tests already pass; they guard
against regression.

- [ ] **Step 3: Extend the verbose branch**

In `src/agent_worklog/logging.py`, add the import:

```python
from agent_worklog.security.redactor import redact_text
```

and replace the `if self.verbose:` branch at the end of `scan_result`:

```python
        if self.verbose:
            for warning in result.warnings:
                self.console.print(f"[yellow]Warning:[/yellow] {warning}")
            for repository_id, sessions in result.sessions_by_repository.items():
                name = sessions[0].repository.display_name if sessions else repository_id
                self.console.print(f"\n{name}", markup=False, highlight=False)
                for resolved in sessions:
                    session = resolved.session
                    label = redact_text(session.title or session.session_id)
                    directory = session.working_directory
                    location = f" — {redact_text(directory)}" if directory else ""
                    self.console.print(
                        f"  • {label}{location}",
                        markup=False,
                        highlight=False,
                    )
```

`redact_text` is required because a scanned session title is raw harness data —
the Claude Code path has no upstream `opencode export --sanitize` step — and
`ConsoleReporter` is documented as taking already-redacted strings.
`markup=False` is required because Rich would otherwise parse `[...]` in a title
as style markup and silently drop it.

- [ ] **Step 4: Run the logging tests**

Run: `uv run pytest tests/unit/test_logging.py -v`
Expected: all PASS.

- [ ] **Step 5: Document the behavior in both READMEs**

In `README.md`, change the shared-options table row for `--verbose` from:

```markdown
| `--verbose` | Also shows export, fallback, and LLM warnings. |
```

to:

```markdown
| `--verbose` | Also shows export, fallback, and LLM warnings. For `scan`, also lists each repository's session titles and working folders. |
```

In `README.zh-TW.md`, change:

```markdown
| `--verbose` | 同時顯示匯出、備援與 LLM 相關的警告。 |
```

to:

```markdown
| `--verbose` | 同時顯示匯出、備援與 LLM 相關的警告。用於 `scan` 時，也會列出每個 repository 的工作階段標題與工作目錄。 |
```

- [ ] **Step 6: Add the documentation test**

Append to `tests/unit/test_documentation.py`:

```python
def test_readmes_document_the_verbose_scan_session_listing() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh_tw = Path("README.zh-TW.md").read_text(encoding="utf-8")

    assert "lists each repository's session titles and working folders" in readme
    assert "列出每個 repository 的工作階段標題與工作目錄" in readme_zh_tw
```

- [ ] **Step 7: Run the whole suite and the linters**

Run: `uv run pytest`
Expected: all PASS.

Run: `uv run ruff check . && uv run ruff format --check . && uv run pyright`
Expected: clean.

- [ ] **Step 8: Add the CHANGELOG entry**

Add to the `## Unreleased` list in `CHANGELOG.md`:

```markdown
- List each repository's session titles and working directories under
  `scan --verbose`, so the selected sessions can be checked without generating a
  report. Titles and directories are redacted before printing; the Claude Code
  path has no upstream sanitize step.
```

- [ ] **Step 9: Commit**

```bash
git add src/agent_worklog/logging.py \
        tests/unit/test_logging.py \
        tests/unit/test_documentation.py \
        README.md README.zh-TW.md CHANGELOG.md
git commit -m "feat: list selected sessions under scan --verbose"
```

---

## Verification Against the Spec's Acceptance Criteria

| Criterion | Covered by |
| --- | --- |
| 1. `report` without `--detail` is byte-identical, except LLM lists over 20 items | Task 1 Steps 1-3 and 9 (golden test), Task 2 Step 1 (`test_brief_default_is_full`), Task 1 Step 4 (`test_full_caps_a_long_section_at_twenty_items`) |
| 2. `--detail brief` content is exactly the specified subset | Task 2 Step 1 (`test_brief_keeps_the_narrative_sections_and_drops_the_appendices`, `test_brief_caps_sections_at_five_items`, `test_brief_drops_the_usage_block`) |
| 3. Overflow counts correct, produced in one place | Task 1 Steps 4, 6, 10 |
| 4. Warnings appear at both detail levels | Task 2 Step 1 (`test_brief_keeps_warnings`) |
| 5. `scan` and `scan --quiet` unchanged | Task 3 Step 1 (`test_non_verbose_scan_does_not_list_sessions`, `test_quiet_scan_still_prints_only_the_count`) |
| 6. `scan --verbose` lists titles and directories | Task 3 Step 1 (`test_verbose_scan_lists_session_titles_and_directories`) |
| 7. Redaction coverage unchanged; no level emits unredacted content | Report path is unchanged — `redact_text` still wraps the render call in `services/report.py`. Scan path gains coverage: Task 3 Step 1 (`test_verbose_scan_redacts_secrets_in_session_titles`) |
| 8. Both READMEs document the new option and behavior | Task 2 Steps 10-11, Task 3 Steps 5-6 |
