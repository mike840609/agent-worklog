# OpenCode Raw Export Default Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make OpenCode raw export the default, preserve explicit sanitization controls, and require per-invocation authorization before extracted evidence is sent to a remote LLM.

**Architecture:** The CLI resolves privacy settings and injects an effective `sanitize: bool` into `OpenCodeCliSource`. The OpenCode mapper filters `[redacted:...]` placeholders, while remote-LLM selection is centralized in the CLI and continues to use `ReportService`’s existing local evidence redaction.

**Tech Stack:** Python 3.11+, Typer, Pydantic Settings, pytest, httpx test doubles, Ruff, Pyright, uv.

## Global Constraints

- Keep Python `>=3.11` and add no runtime dependency.
- Default OpenCode command: `opencode export <session-id>`.
- Sanitized command: `opencode export <session-id> --sanitize`.
- `--sanitize/--no-sanitize` is valid only for OpenCode `scan` and `report`.
- CLI flags override `AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__SANITIZE`; default is `false`.
- Remote LLM use requires `--allow-remote-llm` on every report invocation.
- `--no-llm` and `--allow-remote-llm` are mutually exclusive.
- Raw export JSON remains in subprocess stdout and Python memory; do not persist or log it.
- Reuse the existing evidence and Markdown redaction in `ReportService`.
- Redacted placeholders must not become activities, evidence, or rendered text.
- Release as `v0.6.0` and update `uv.lock`.

---

### Task 1: Make OpenCode raw export the configurable default

**Files:**
- Modify: `src/agent_worklog/config.py`
- Modify: `src/agent_worklog/harnesses/opencode/source.py`
- Modify: `tests/unit/test_config.py`
- Modify: `tests/unit/harnesses/opencode/test_mapper.py`

**Interfaces:**
- Produces: `OpenCodeCliSettings.sanitize: bool = False`
- Produces: `OpenCodeCliSource(..., sanitize: bool = False)`

- [ ] **Step 1: Add failing settings tests**

Append to `tests/unit/test_config.py`:

```python
def test_opencode_sanitize_defaults_to_false(monkeypatch) -> None:
    monkeypatch.delenv(
        "AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__SANITIZE",
        raising=False,
    )

    assert AppSettings().harnesses.opencode.cli.sanitize is False


def test_opencode_sanitize_can_be_enabled_from_environment(monkeypatch) -> None:
    monkeypatch.setenv(
        "AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__SANITIZE",
        "true",
    )

    assert AppSettings().harnesses.opencode.cli.sanitize is True
```

- [ ] **Step 2: Replace the existing source command test**

In `tests/unit/harnesses/opencode/test_mapper.py`:

```python
def test_load_uses_raw_export_by_default(fake_runner) -> None:
    fake_runner.stdout = '{"messages": []}'
    source = OpenCodeCliSource(runner=fake_runner, executable="opencode")

    source.load(SessionDescriptor(harness="opencode", session_id="s1"))

    assert fake_runner.calls[0] == ["opencode", "export", "s1"]


def test_load_adds_sanitize_when_enabled(fake_runner) -> None:
    fake_runner.stdout = '{"messages": []}'
    source = OpenCodeCliSource(
        runner=fake_runner,
        executable="opencode",
        sanitize=True,
    )

    source.load(SessionDescriptor(harness="opencode", session_id="s1"))

    assert fake_runner.calls[0] == ["opencode", "export", "s1", "--sanitize"]
```

Update the existing export-failure test fixture suffix from `"export s1 --sanitize"` to `"export s1"`.

- [ ] **Step 3: Verify failure**

```bash
uv run pytest tests/unit/test_config.py tests/unit/harnesses/opencode/test_mapper.py -v
```

Expected: missing `sanitize` setting/constructor support and wrong default command.

- [ ] **Step 4: Add the setting**

```python
class OpenCodeCliSettings(BaseModel):
    executable: str = "opencode"
    timeout_seconds: float = 30.0
    sanitize: bool = False
```

- [ ] **Step 5: Make export command construction conditional**

```python
def __init__(
    self,
    *,
    runner: Runner,
    executable: str = "opencode",
    root_only: bool = False,
    sanitize: bool = False,
) -> None:
    self._runner = runner
    self._executable = executable
    self._root_only = root_only
    self._sanitize = sanitize
```

```python
args = [self._executable, "export", descriptor.session_id]
if self._sanitize:
    args.append("--sanitize")
result = self._runner.run(args)
```

Keep current error handling; never include `result.stdout` in errors.

- [ ] **Step 6: Verify pass**

```bash
uv run pytest tests/unit/test_config.py tests/unit/harnesses/opencode/test_mapper.py -v
```

- [ ] **Step 7: Commit**

```bash
git add src/agent_worklog/config.py src/agent_worklog/harnesses/opencode/source.py tests/unit/test_config.py tests/unit/harnesses/opencode/test_mapper.py
git commit -m "fix: make OpenCode raw export the default"
```

---

### Task 2: Prevent sanitized placeholders from becoming evidence

**Files:**
- Modify: `src/agent_worklog/harnesses/opencode/mapper.py`
- Modify: `tests/unit/harnesses/opencode/test_mapper.py`

**Interfaces:**
- Produces: `_is_redacted_placeholder(value: object) -> bool`
- Produces: `_usable_export_string(value: object) -> str | None`

- [ ] **Step 1: Add failing fallback test**

```python
def test_mapper_falls_back_when_export_metadata_is_redacted() -> None:
    descriptor = SessionDescriptor(
        harness="opencode",
        session_id="s1",
        title="Database title",
        working_directory_hint="/repo/from-db",
    )
    payload = {
        "info": {
            "title": "[redacted:session-title:s1]",
            "directory": "[redacted:session-directory:s1]",
        },
        "messages": [],
    }

    session = OpenCodeExportMapper().map(payload, descriptor)

    assert session.title == "Database title"
    assert session.working_directory == "/repo/from-db"
```

- [ ] **Step 2: Add failing activity omission test**

```python
def test_mapper_omits_redacted_message_and_tool_content() -> None:
    payload = {
        "info": {},
        "messages": [
            {
                "info": {"id": "m1", "role": "user"},
                "parts": [
                    {"type": "text", "text": "[redacted:text:p1]"},
                    {
                        "type": "tool",
                        "tool": "bash",
                        "callID": "call-1",
                        "state": {"input": "[redacted:tool-input:p2]"},
                    },
                ],
            }
        ],
    }

    session = OpenCodeExportMapper().map(
        payload,
        SessionDescriptor(harness="opencode", session_id="s1"),
    )

    assert session.activities == []
```

Retain the existing raw fixture test as the positive control.

- [ ] **Step 3: Verify failure**

```bash
uv run pytest tests/unit/harnesses/opencode/test_mapper.py -v
```

- [ ] **Step 4: Add placeholder helpers**

```python
def _is_redacted_placeholder(value: object) -> bool:
    return isinstance(value, str) and value.strip().startswith("[redacted:")


def _usable_export_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or _is_redacted_placeholder(stripped):
        return None
    return stripped
```

- [ ] **Step 5: Apply them consistently**

For text parts:

```python
text = _usable_export_string(part.get("text"))
if text is None:
    continue
```

For tool parts:

```python
content = _tool_content(part)
if not content or _is_redacted_placeholder(content):
    continue
```

For metadata:

```python
title = (
    _usable_export_string(export_info.get("title"))
    or _usable_export_string(payload.get("title"))
    or descriptor.title
)
directory = (
    _usable_export_string(export_info.get("directory"))
    or _usable_export_string(payload.get("directory"))
    or descriptor.working_directory_hint
)
```

- [ ] **Step 6: Verify pass**

```bash
uv run pytest tests/unit/harnesses/opencode/test_mapper.py tests/unit/extraction -v
```

- [ ] **Step 7: Commit**

```bash
git add src/agent_worklog/harnesses/opencode/mapper.py tests/unit/harnesses/opencode/test_mapper.py
git commit -m "fix: ignore OpenCode redaction placeholders"
```

---

### Task 3: Add CLI sanitization controls and precedence

**Files:**
- Modify: `src/agent_worklog/cli.py`
- Modify: `tests/unit/test_cli.py`
- Modify: `tests/integration/test_cli.py`

**Interfaces:**
- Produces: `_validate_privacy_options(...) -> None`
- Produces: `_effective_sanitize(settings: AppSettings, harness: Harness, override: bool | None) -> bool`
- Changes: `_build_scan_service(..., sanitize: bool = False)`
- Changes: `_build_report_service(..., sanitize: bool = False)`

- [ ] **Step 1: Add failing precedence tests**

```python
def test_effective_sanitize_uses_setting_without_override(monkeypatch) -> None:
    import agent_worklog.cli as cli

    monkeypatch.setenv(
        "AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__SANITIZE",
        "true",
    )

    assert cli._effective_sanitize(
        cli.AppSettings(), cli.Harness.OPENCODE, None
    ) is True


def test_effective_sanitize_cli_false_overrides_setting(monkeypatch) -> None:
    import agent_worklog.cli as cli

    monkeypatch.setenv(
        "AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__SANITIZE",
        "true",
    )

    assert cli._effective_sanitize(
        cli.AppSettings(), cli.Harness.OPENCODE, False
    ) is False
```

- [ ] **Step 2: Add failing CLI validation tests**

In `tests/integration/test_cli.py`:

```python
@pytest.mark.parametrize("command", ["scan", "report"])
@pytest.mark.parametrize("harness", ["claude-code", "codex"])
def test_sanitize_rejected_for_non_opencode(command: str, harness: str) -> None:
    args = [command, "--days", "7", "--harness", harness, "--sanitize"]
    if command == "report":
        args.append("--dry-run")

    result = runner.invoke(cli.app, args)

    assert result.exit_code == 2
    assert "supported only with --harness opencode" in result.stdout
```

- [ ] **Step 3: Verify failure**

```bash
uv run pytest tests/unit/test_cli.py tests/integration/test_cli.py -v
```

- [ ] **Step 4: Add helpers**

```python
def _validate_privacy_options(
    *,
    harness: Harness,
    sanitize: bool | None,
    no_llm: bool = False,
    allow_remote_llm: bool = False,
) -> None:
    if sanitize is not None and harness is not Harness.OPENCODE:
        raise typer.BadParameter(
            "--sanitize and --no-sanitize are supported only with --harness opencode"
        )
    if no_llm and allow_remote_llm:
        raise typer.BadParameter(
            "--no-llm and --allow-remote-llm cannot be used together"
        )


def _effective_sanitize(
    settings: AppSettings,
    harness: Harness,
    override: bool | None,
) -> bool:
    if harness is not Harness.OPENCODE:
        return False
    return settings.harnesses.opencode.cli.sanitize if override is None else override
```

- [ ] **Step 5: Add tri-state options to `scan` and `report`**

```python
sanitize: bool | None = typer.Option(
    None,
    "--sanitize/--no-sanitize",
    help=(
        "Ask OpenCode to redact exported session content. "
        "Disabled by default. OpenCode only."
    ),
),
```

Each command must validate before scanning, compute `effective_sanitize`, and pass it to its service builder.

- [ ] **Step 6: Thread the resolved boolean into OpenCode source**

Add `sanitize: bool = False` as a keyword-only parameter to `_build_scan_service` and `_build_report_service`; then:

```python
source = OpenCodeCliSource(
    runner=CommandRunner(timeout_seconds=cli_settings.timeout_seconds),
    executable=cli_settings.executable,
    root_only=root_only,
    sanitize=sanitize,
)
```

Update every monkeypatched builder in `tests/integration/test_cli.py` with explicit `sanitize=False` parameters so argument propagation remains test-visible.

- [ ] **Step 7: Add override flow test**

Capture the `sanitize` keyword in a stub `_build_scan_service`, invoke:

```python
result = runner.invoke(
    cli.app,
    ["scan", "--days", "7", "--no-sanitize"],
    env={"AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__SANITIZE": "true"},
)
```

Assert exit 0 and captured value `False`.

- [ ] **Step 8: Verify pass**

```bash
uv run pytest tests/unit/test_cli.py tests/integration/test_cli.py -v
```

- [ ] **Step 9: Commit**

```bash
git add src/agent_worklog/cli.py tests/unit/test_cli.py tests/integration/test_cli.py
git commit -m "feat: add OpenCode sanitize CLI controls"
```

---

### Task 4: Require explicit remote-LLM authorization

**Files:**
- Modify: `src/agent_worklog/cli.py`
- Modify: `src/agent_worklog/services/report.py`
- Modify: `tests/unit/test_cli.py`
- Modify: `tests/unit/services/test_report.py`
- Modify: `tests/integration/test_cli.py`

**Interfaces:**
- Produces: `_remote_llm_selection(...) -> tuple[bool, list[str]]`
- Changes: `ReportService(..., initial_warnings: list[str] | None = None)`
- Changes: `_build_report_service(..., allow_remote_llm: bool = False)`

- [ ] **Step 1: Add failing selection tests**

Cover these exact cases in `tests/unit/test_cli.py`:

```python
assert cli._remote_llm_selection(
    settings=cli.AppSettings(),
    api_key="secret",
    no_llm=False,
    allow_remote_llm=False,
) == (False, [])
```

```python
assert cli._remote_llm_selection(
    settings=cli.AppSettings(),
    api_key="secret",
    no_llm=False,
    allow_remote_llm=True,
) == (True, [])
```

```python
assert cli._remote_llm_selection(
    settings=cli.AppSettings(),
    api_key=None,
    no_llm=False,
    allow_remote_llm=True,
) == (
    False,
    ["remote LLM requested but OPENAI_API_KEY is not set; used deterministic fallback"],
)
```

Set `settings.llm.enabled = False` and assert the corresponding disabled-setting warning.

- [ ] **Step 2: Add failing conflict test**

```python
def test_report_rejects_no_llm_with_remote_authorization() -> None:
    result = runner.invoke(
        cli.app,
        [
            "report",
            "--days", "7",
            "--no-llm",
            "--allow-remote-llm",
            "--dry-run",
        ],
    )

    assert result.exit_code == 2
    assert "cannot be used together" in result.stdout
```

- [ ] **Step 3: Add failing initial-warning test**

In `tests/unit/services/test_report.py`, extend an existing non-empty service fixture:

```python
service = ReportService(
    scan_service=scan_service,
    summarizer=RuleBasedSummarizer(),
    renderer=MarkdownRenderer(),
    period=period,
    output_path=tmp_path / "report.md",
    now_factory=lambda: period.until,
    initial_warnings=["remote LLM unavailable"],
)
result = service.generate(dry_run=True)
assert "remote LLM unavailable" in result.report.warnings
```

- [ ] **Step 4: Verify failure**

```bash
uv run pytest tests/unit/test_cli.py tests/unit/services/test_report.py tests/integration/test_cli.py -v
```

- [ ] **Step 5: Implement selection helper**

```python
def _remote_llm_selection(
    *,
    settings: AppSettings,
    api_key: str | None,
    no_llm: bool,
    allow_remote_llm: bool,
) -> tuple[bool, list[str]]:
    if no_llm or not allow_remote_llm:
        return False, []
    if not settings.llm.enabled:
        return False, [
            "remote LLM requested but LLM support is disabled; "
            "used deterministic fallback"
        ]
    if not api_key:
        return False, [
            f"remote LLM requested but {settings.llm.api_key_env} is not set; "
            "used deterministic fallback"
        ]
    return True, []
```

- [ ] **Step 6: Add initial warnings to `ReportService`**

Add constructor parameter and storage:

```python
initial_warnings: list[str] | None = None
self._initial_warnings = list(initial_warnings or [])
```

Start generation warnings with:

```python
warnings = [*self._initial_warnings, *scan.warnings]
```

Existing `redact_text` processing remains unchanged.

- [ ] **Step 7: Add report option and builder logic**

```python
allow_remote_llm: bool = typer.Option(
    False,
    "--allow-remote-llm",
    help=(
        "Allow extracted work evidence to be sent to the configured "
        "OpenAI-compatible endpoint for this invocation."
    ),
),
```

Use `_remote_llm_selection`; construct `OpenAICompatibleSummarizer` only when enabled, otherwise keep `RuleBasedSummarizer`. Pass returned warnings into `ReportService(initial_warnings=...)`.

Update all report builder stubs with explicit `allow_remote_llm=False`.

- [ ] **Step 8: Add constructor-selection tests**

Keep the existing `--no-llm` test. Add one test where an API key exists but `allow_remote_llm=False`; monkeypatch the remote summarizer constructor to raise and assert service construction succeeds. Add one positive test with `allow_remote_llm=True` that captures `api_key="secret-key"` without making HTTP calls.

- [ ] **Step 9: Verify pass**

```bash
uv run pytest tests/unit/test_cli.py tests/unit/services/test_report.py tests/integration/test_cli.py -v
```

- [ ] **Step 10: Commit**

```bash
git add src/agent_worklog/cli.py src/agent_worklog/services/report.py tests/unit/test_cli.py tests/unit/services/test_report.py tests/integration/test_cli.py
git commit -m "feat: require remote LLM opt-in"
```

---

### Task 5: Prove both privacy modes end to end

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/integration/test_end_to_end.py`
- Create: `tests/fixtures/opencode/export-sanitized.json`

**Interfaces:**
- Consumes: `AcceptanceCommandRunner.export_calls`
- Produces: deterministic raw and sanitized acceptance coverage

- [ ] **Step 1: Add the sanitized fixture**

```json
{
  "info": {
    "title": "[redacted:session-title:sanitized-session]",
    "directory": "[redacted:session-directory:sanitized-session]"
  },
  "messages": [
    {
      "info": {"id": "m-sanitized", "role": "user"},
      "parts": [
        {"type": "text", "text": "[redacted:text:p-sanitized]"}
      ]
    }
  ]
}
```

- [ ] **Step 2: Extend `AcceptanceCommandRunner`**

Add this row:

```python
{
    "id": "sanitized-session",
    "project_id": "project-agent",
    "parent_id": None,
    "directory": "/worktrees/agent-main",
    "title": "Database sanitized title",
    "time_created": _millis(datetime(2026, 7, 26, tzinfo=_ACCEPTANCE_TZ)),
    "time_updated": _millis(datetime(2026, 7, 26, 3, tzinfo=_ACCEPTANCE_TZ)),
}
```

Add mapping:

```python
"sanitized-session": "export-sanitized.json",
```

- [ ] **Step 3: Update the existing raw-default acceptance assertion**

In `tests/integration/test_end_to_end.py`, replace:

```python
assert all(call[-1] == "--sanitize" for call in mocked_opencode.export_calls)
```

with:

```python
assert all("--sanitize" not in call for call in mocked_opencode.export_calls)
assert "[redacted:" not in content
```

Keep the existing repository, security, session, directory, export-failure, and usage assertions.

- [ ] **Step 4: Add sanitized end-to-end coverage**

Invoke the CLI with `--sanitize`, then assert:

```python
assert all(call[-1] == "--sanitize" for call in mocked_opencode.export_calls)
assert "Database sanitized title" in content
assert "[redacted:" not in content
```

Also assert the redacted user text does not appear under goals or in-progress work.

- [ ] **Step 5: Verify default-local behavior with API key present**

Set `OPENAI_API_KEY=secret-key`, omit both `--no-llm` and `--allow-remote-llm`, monkeypatch `OpenAICompatibleSummarizer` to raise if constructed, and assert the end-to-end report still succeeds.

- [ ] **Step 6: Run integration tests**

```bash
uv run pytest tests/integration -v
```

- [ ] **Step 7: Commit**

```bash
git add tests/conftest.py tests/integration/test_end_to_end.py tests/fixtures/opencode/export-sanitized.json
git commit -m "test: cover OpenCode privacy modes end to end"
```

---

### Task 6: Document and release v0.6.0

**Files:**
- Modify: `README.md`
- Modify: `README.zh-TW.md`
- Modify: `docs/configuration.md`
- Modify: `docs/guides.md`
- Modify: `docs/privacy.md`
- Modify: `docs/limitations.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/unit/test_documentation.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Produces: documented CLI contract and package version `0.6.0`

- [ ] **Step 1: Add failing documentation tests**

```python
def test_readmes_document_privacy_controls() -> None:
    for path in (Path("README.md"), Path("README.zh-TW.md")):
        text = path.read_text(encoding="utf-8")
        assert "--sanitize" in text
        assert "--allow-remote-llm" in text


def test_configuration_documents_opencode_sanitize_setting() -> None:
    text = Path("docs/configuration.md").read_text(encoding="utf-8")
    assert "AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__SANITIZE" in text


def test_privacy_doc_warns_about_raw_export_and_dry_run() -> None:
    text = Path("docs/privacy.md").read_text(encoding="utf-8").casefold()
    assert "raw" in text
    assert "--dry-run" in text
    assert "--allow-remote-llm" in text
```

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/unit/test_documentation.py -v
```

- [ ] **Step 3: Update user documentation**

Include these examples in both READMEs:

```bash
agent-worklog report --days 7
agent-worklog report --days 7 --sanitize
agent-worklog report --days 7 --allow-remote-llm
```

Document:

- raw OpenCode export is default;
- remote summarization is off unless explicitly allowed;
- sanitized mode removes most work evidence;
- `--dry-run` may expose report content in terminal or CI logs;
- setting precedence is CLI, environment/application setting, default false.

Add `AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__SANITIZE=true` to `docs/configuration.md`. Describe limitations in `docs/limitations.md` and data boundaries in `docs/privacy.md`.

- [ ] **Step 4: Add v0.6.0 changelog entry**

Include:

```markdown
- OpenCode exports are raw by default.
- `--sanitize/--no-sanitize` and the nested environment setting control OpenCode redaction.
- Remote LLM summaries require `--allow-remote-llm` per invocation.
- `--no-llm` and `--allow-remote-llm` are mutually exclusive.
```

- [ ] **Step 5: Bump and lock version**

Change:

```toml
version = "0.6.0"
```

Run:

```bash
uv lock
```

- [ ] **Step 6: Run focused documentation checks**

```bash
uv run pytest tests/unit/test_documentation.py -v
uv run python -c 'from importlib.metadata import version; print(version("agent-worklog"))'
```

Expected version: `0.6.0`.

- [ ] **Step 7: Run full verification**

```bash
uv run ruff check .
uv run pyright
uv run pytest
uv run agent-worklog scan --help
uv run agent-worklog report --help
```

Verify both commands show `--sanitize/--no-sanitize`, only report shows `--allow-remote-llm`, and all automated checks pass.

- [ ] **Step 8: Commit**

```bash
git add README.md README.zh-TW.md docs/configuration.md docs/guides.md docs/privacy.md docs/limitations.md CHANGELOG.md tests/unit/test_documentation.py pyproject.toml uv.lock
git commit -m "release: prepare 0.6.0 privacy defaults"
```

---

## Final Review Checklist

- [ ] Raw OpenCode export is default and sanitized mode is explicit.
- [ ] CLI override precedence is tested in both directions.
- [ ] Claude Code and Codex reject explicit sanitize flags before scanning.
- [ ] API key presence alone never creates the remote summarizer.
- [ ] Missing/disabled remote configuration produces a redacted report warning.
- [ ] Raw export JSON is neither persisted nor logged.
- [ ] Sanitized placeholders never enter activities, evidence, or Markdown.
- [ ] Existing local redaction remains active.
- [ ] English and Traditional Chinese documentation matches CLI behavior.
- [ ] `pyproject.toml` and `uv.lock` report `0.6.0`.
- [ ] Ruff, Pyright, and the complete pytest suite pass.
