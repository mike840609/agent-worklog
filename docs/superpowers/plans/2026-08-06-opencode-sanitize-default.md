# OpenCode Raw Export Default Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make OpenCode raw export the default, preserve explicit `--sanitize/--no-sanitize` control, and require per-invocation authorization before any extracted evidence is sent to a remote LLM.

**Architecture:** Resolve privacy choices in the CLI, inject the effective `sanitize: bool` into `OpenCodeCliSource`, and keep the source independent of global settings. Filter OpenCode `[redacted:...]` placeholders in the mapper, then centralize remote-LLM selection in the CLI while reusing the existing local evidence redaction in `ReportService`.

**Tech Stack:** Python 3.11+, Typer, Pydantic Settings, pytest, httpx test doubles, Ruff, Pyright, uv.

## Global Constraints

- Python remains `>=3.11`; do not add a new runtime dependency.
- OpenCode export is raw by default: `opencode export <session-id>`.
- `--sanitize/--no-sanitize` is supported only by `scan` and `report` when `--harness opencode` is selected.
- CLI sanitization flags override `AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__SANITIZE`; the setting defaults to `false`.
- Remote LLM use requires `--allow-remote-llm` on every `report` invocation.
- `--no-llm` and `--allow-remote-llm` are mutually exclusive.
- Raw OpenCode JSON stays in subprocess stdout and Python memory; never persist it or include it in logs or exception messages.
- Continue using the existing `ReportService` redaction of extracted evidence and rendered Markdown; do not build another general-purpose secret scanner.
- Sanitized placeholders must not become activities, evidence, or rendered report text.
- Release the behavior as `v0.6.0` and update `uv.lock` after changing the project version.

---

## File Structure

- `src/agent_worklog/config.py` — owns the persistent OpenCode `sanitize` setting.
- `src/agent_worklog/harnesses/opencode/source.py` — owns construction of the OpenCode export command.
- `src/agent_worklog/harnesses/opencode/mapper.py` — owns placeholder detection, metadata fallback, and activity omission.
- `src/agent_worklog/cli.py` — owns CLI flags, validation, setting precedence, and remote-LLM authorization.
- `src/agent_worklog/services/report.py` — owns report-level warning aggregation; receives initial warnings from CLI decisions.
- `tests/unit/test_config.py` — verifies nested environment settings.
- `tests/unit/harnesses/opencode/test_mapper.py` — verifies export command construction and mapper behavior.
- `tests/unit/test_cli.py` — verifies helper-level source selection, precedence, and option validation.
- `tests/unit/services/test_report.py` — verifies initial warning propagation.
- `tests/integration/test_cli.py` — verifies CLI-to-service argument flow and remote-LLM selection.
- `tests/conftest.py` — acceptance runner records raw and sanitized export command shapes.
- `tests/integration/test_acceptance.py` — verifies the end-to-end OpenCode report behavior using existing fixtures; if the current acceptance filename differs, extend the file that consumes `mocked_opencode` rather than creating a duplicate fixture pipeline.
- `README.md`, `README.zh-TW.md`, `docs/configuration.md`, `docs/guides.md`, `docs/privacy.md`, `docs/limitations.md`, `CHANGELOG.md` — document new defaults and safety behavior.
- `pyproject.toml`, `uv.lock` — release version metadata.

---

### Task 1: Make raw OpenCode export configurable and default

**Files:**
- Modify: `src/agent_worklog/config.py`
- Modify: `src/agent_worklog/harnesses/opencode/source.py`
- Modify: `tests/unit/test_config.py`
- Modify: `tests/unit/harnesses/opencode/test_mapper.py`

**Interfaces:**
- Produces: `OpenCodeCliSettings.sanitize: bool = False`
- Produces: `OpenCodeCliSource(..., sanitize: bool = False)`
- Consumes: existing `Runner.run(args: list[str]) -> CommandResult`

- [ ] **Step 1: Add failing configuration tests**

Append to `tests/unit/test_config.py`:

```python
from agent_worklog.config import AppSettings


def test_opencode_sanitize_defaults_to_false(monkeypatch) -> None:
    monkeypatch.delenv(
        "AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__SANITIZE",
        raising=False,
    )

    settings = AppSettings()

    assert settings.harnesses.opencode.cli.sanitize is False


def test_opencode_sanitize_can_be_enabled_from_environment(monkeypatch) -> None:
    monkeypatch.setenv(
        "AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__SANITIZE",
        "true",
    )

    settings = AppSettings()

    assert settings.harnesses.opencode.cli.sanitize is True
```

- [ ] **Step 2: Replace the current source-command test with raw-default and sanitized-mode tests**

In `tests/unit/harnesses/opencode/test_mapper.py`, replace `test_load_uses_sanitize_flag` with:

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

Also update the existing export-failure test so its fake result matches the new default command suffix:

```python
fake_runner.set_result(
    "export s1",
    CommandResult(returncode=1, stdout="", stderr="session missing"),
)
```

- [ ] **Step 3: Run the focused tests and confirm they fail**

Run:

```bash
uv run pytest \
  tests/unit/test_config.py \
  tests/unit/harnesses/opencode/test_mapper.py \
  -v
```

Expected: failures because `OpenCodeCliSettings` and `OpenCodeCliSource` do not yet expose `sanitize`, and the default command still contains `--sanitize`.

- [ ] **Step 4: Add the configuration field**

Modify `OpenCodeCliSettings` in `src/agent_worklog/config.py`:

```python
class OpenCodeCliSettings(BaseModel):
    """OpenCode executable invocation settings."""

    executable: str = "opencode"
    timeout_seconds: float = 30.0
    sanitize: bool = False
```

- [ ] **Step 5: Make source command construction conditional**

Modify `OpenCodeCliSource.__init__` and `load()` in `src/agent_worklog/harnesses/opencode/source.py`:

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
def load(self, descriptor: SessionDescriptor) -> AgentSession:
    args = [self._executable, "export", descriptor.session_id]
    if self._sanitize:
        args.append("--sanitize")
    result = self._runner.run(args)
    if result.returncode != 0:
        detail = result.stderr.strip() or f"OpenCode export failed for {descriptor.session_id}"
        raise SessionParseError(detail)
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise SessionParseError(
            f"OpenCode export returned invalid JSON for {descriptor.session_id}"
        ) from exc
    return OpenCodeExportMapper().map(payload, descriptor)
```

Do not add stdout to errors or logs.

- [ ] **Step 6: Run the focused tests**

Run:

```bash
uv run pytest \
  tests/unit/test_config.py \
  tests/unit/harnesses/opencode/test_mapper.py \
  -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add \
  src/agent_worklog/config.py \
  src/agent_worklog/harnesses/opencode/source.py \
  tests/unit/test_config.py \
  tests/unit/harnesses/opencode/test_mapper.py
git commit -m "fix: make OpenCode raw export the default"
```

---

### Task 2: Filter sanitized placeholders in the OpenCode mapper

**Files:**
- Modify: `src/agent_worklog/harnesses/opencode/mapper.py`
- Modify: `tests/unit/harnesses/opencode/test_mapper.py`

**Interfaces:**
- Produces: `_is_redacted_placeholder(value: object) -> bool`
- Produces: `_usable_export_string(value: object) -> str | None`
- Consumes: `SessionDescriptor` discovery metadata as fallback

- [ ] **Step 1: Add failing mapper tests for metadata fallback**

Append to `tests/unit/harnesses/opencode/test_mapper.py`:

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

- [ ] **Step 2: Add failing tests for redacted text and tool activities**

```python
def test_mapper_omits_redacted_message_and_tool_content() -> None:
    descriptor = SessionDescriptor(harness="opencode", session_id="s1")
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

    session = OpenCodeExportMapper().map(payload, descriptor)

    assert session.activities == []


def test_mapper_keeps_non_redacted_text_and_tool_content() -> None:
    descriptor = SessionDescriptor(harness="opencode", session_id="s1")
    payload = {
        "info": {},
        "messages": [
            {
                "info": {"id": "m1", "role": "user"},
                "parts": [
                    {"type": "text", "text": "Fix the export report"},
                    {
                        "type": "tool",
                        "tool": "bash",
                        "callID": "call-1",
                        "state": {"input": {"command": "pytest -q"}},
                    },
                ],
            }
        ],
    }

    session = OpenCodeExportMapper().map(payload, descriptor)

    assert [activity.content for activity in session.activities] == [
        "Fix the export report",
        "pytest -q",
    ]
```

- [ ] **Step 3: Run mapper tests and confirm failures**

Run:

```bash
uv run pytest tests/unit/harnesses/opencode/test_mapper.py -v
```

Expected: redacted metadata overrides descriptor values and redacted parts create activities.

- [ ] **Step 4: Add focused placeholder helpers**

In `src/agent_worklog/harnesses/opencode/mapper.py`, add:

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

- [ ] **Step 5: Apply helpers to text, tool content, title, and directory**

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

For final metadata selection:

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

Pass `title` and `directory` directly into `AgentSession` rather than rechecking only `isinstance(value, str)`.

- [ ] **Step 6: Run mapper and extraction tests**

Run:

```bash
uv run pytest \
  tests/unit/harnesses/opencode/test_mapper.py \
  tests/unit/extraction \
  -v
```

Expected: PASS and no existing raw-content extraction regression.

- [ ] **Step 7: Commit**

```bash
git add \
  src/agent_worklog/harnesses/opencode/mapper.py \
  tests/unit/harnesses/opencode/test_mapper.py
git commit -m "fix: ignore OpenCode redaction placeholders"
```

---

### Task 3: Add CLI sanitization flags and precedence

**Files:**
- Modify: `src/agent_worklog/cli.py`
- Modify: `tests/unit/test_cli.py`
- Modify: `tests/integration/test_cli.py`

**Interfaces:**
- Produces: `_validate_privacy_options(..., sanitize: bool | None, no_llm: bool = False, allow_remote_llm: bool = False) -> None`
- Produces: `_effective_sanitize(settings: AppSettings, harness: Harness, override: bool | None) -> bool`
- Changes: `_build_scan_service(..., sanitize: bool = False)`
- Changes: `_build_report_service(..., sanitize: bool = False, ...)`

- [ ] **Step 1: Add failing pure-helper tests**

Append to `tests/unit/test_cli.py`:

```python
import pytest
import typer


def test_effective_sanitize_uses_setting_without_cli_override(monkeypatch) -> None:
    import agent_worklog.cli as cli

    monkeypatch.setenv(
        "AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__SANITIZE",
        "true",
    )
    settings = cli.AppSettings()

    assert cli._effective_sanitize(settings, cli.Harness.OPENCODE, None) is True


def test_effective_sanitize_allows_cli_to_disable_setting(monkeypatch) -> None:
    import agent_worklog.cli as cli

    monkeypatch.setenv(
        "AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__SANITIZE",
        "true",
    )
    settings = cli.AppSettings()

    assert cli._effective_sanitize(settings, cli.Harness.OPENCODE, False) is False


@pytest.mark.parametrize("harness", ["claude-code", "codex"])
def test_sanitize_flags_are_rejected_for_other_harnesses(harness: str) -> None:
    import agent_worklog.cli as cli

    with pytest.raises(typer.BadParameter, match="supported only"):
        cli._validate_privacy_options(
            harness=cli.Harness(harness),
            sanitize=True,
        )
```

- [ ] **Step 2: Add failing CLI flow tests**

In `tests/integration/test_cli.py`, add a `scan` test that captures the resolved boolean:

```python
def test_scan_no_sanitize_overrides_environment_setting(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class StubScanService:
        def scan(self):
            return SimpleNamespace(
                loaded_session_count=1,
                sessions_by_repository={},
                warnings=[],
            )

    def build(
        settings,
        period,
        root_only=False,
        *,
        harness=cli.Harness.OPENCODE,
        progress=None,
        sanitize=False,
    ):
        captured["sanitize"] = sanitize
        return StubScanService()

    monkeypatch.setattr(cli, "_build_scan_service", build)

    result = runner.invoke(
        cli.app,
        ["scan", "--days", "7", "--no-sanitize"],
        env={"AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__SANITIZE": "true"},
    )

    assert result.exit_code == 0, result.stdout
    assert captured["sanitize"] is False
```

Add explicit rejection coverage:

```python
@pytest.mark.parametrize("command", ["scan", "report"])
@pytest.mark.parametrize("harness", ["claude-code", "codex"])
def test_sanitize_rejected_for_non_opencode_commands(command: str, harness: str) -> None:
    args = [command, "--days", "7", "--harness", harness, "--sanitize"]
    if command == "report":
        args.append("--dry-run")

    result = runner.invoke(cli.app, args)

    assert result.exit_code == 2
    assert "supported only with --harness opencode" in result.stdout
```

- [ ] **Step 3: Run focused CLI tests and confirm failures**

Run:

```bash
uv run pytest tests/unit/test_cli.py tests/integration/test_cli.py -v
```

Expected: missing helpers/options/signature propagation.

- [ ] **Step 4: Add validation and precedence helpers**

In `src/agent_worklog/cli.py`:

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
    if override is not None:
        return override
    return settings.harnesses.opencode.cli.sanitize
```

- [ ] **Step 5: Thread `sanitize` through service builders**

Change `_build_scan_service`:

```python
def _build_scan_service(
    settings: AppSettings,
    period: DateRange,
    root_only: bool = False,
    *,
    harness: Harness = Harness.OPENCODE,
    progress: ProgressReporter | None = None,
    sanitize: bool = False,
) -> ScanService:
```

Pass it only to OpenCode:

```python
source = OpenCodeCliSource(
    runner=CommandRunner(timeout_seconds=cli_settings.timeout_seconds),
    executable=cli_settings.executable,
    root_only=root_only,
    sanitize=sanitize,
)
```

Add the same keyword to `_build_report_service` and pass it into `_build_scan_service`.

- [ ] **Step 6: Add tri-state flags to `scan` and `report`**

Add this parameter to both command signatures:

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

Immediately after loading settings:

```python
_validate_privacy_options(harness=harness, sanitize=sanitize)
effective_sanitize = _effective_sanitize(settings, harness, sanitize)
```

Pass `sanitize=effective_sanitize` into `_build_scan_service` or `_build_report_service`.

- [ ] **Step 7: Update existing monkeypatched builder signatures**

Every local `build(...)` stub in `tests/integration/test_cli.py` that replaces `_build_scan_service` must accept keyword `sanitize=False`. Every stub replacing `_build_report_service` must accept keyword `sanitize=False`. Do not absorb arbitrary `**kwargs`; explicit signatures ensure mutations remain visible to tests.

Use this exact pattern:

```python
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
    sanitize=False,
):
    ...
```

- [ ] **Step 8: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_cli.py tests/integration/test_cli.py -v
```

Expected: PASS.

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
- Produces: `_remote_llm_selection(settings: AppSettings, api_key: str | None, no_llm: bool, allow_remote_llm: bool) -> tuple[bool, list[str]]`
- Changes: `ReportService(..., initial_warnings: list[str] | None = None)`
- Changes: `_build_report_service(..., allow_remote_llm: bool = False)`

- [ ] **Step 1: Add failing remote-selection tests**

Append to `tests/unit/test_cli.py`:

```python
def test_remote_llm_is_off_without_explicit_authorization() -> None:
    import agent_worklog.cli as cli

    enabled, warnings = cli._remote_llm_selection(
        settings=cli.AppSettings(),
        api_key="secret",
        no_llm=False,
        allow_remote_llm=False,
    )

    assert enabled is False
    assert warnings == []


def test_remote_llm_is_enabled_with_authorization_and_key() -> None:
    import agent_worklog.cli as cli

    enabled, warnings = cli._remote_llm_selection(
        settings=cli.AppSettings(),
        api_key="secret",
        no_llm=False,
        allow_remote_llm=True,
    )

    assert enabled is True
    assert warnings == []


def test_remote_llm_authorization_without_key_returns_warning() -> None:
    import agent_worklog.cli as cli

    settings = cli.AppSettings()
    enabled, warnings = cli._remote_llm_selection(
        settings=settings,
        api_key=None,
        no_llm=False,
        allow_remote_llm=True,
    )

    assert enabled is False
    assert warnings == [
        "remote LLM requested but OPENAI_API_KEY is not set; used deterministic fallback"
    ]
```

Also add disabled-setting coverage:

```python
def test_remote_llm_authorization_respects_disabled_setting() -> None:
    import agent_worklog.cli as cli

    settings = cli.AppSettings()
    settings.llm.enabled = False

    enabled, warnings = cli._remote_llm_selection(
        settings=settings,
        api_key="secret",
        no_llm=False,
        allow_remote_llm=True,
    )

    assert enabled is False
    assert warnings == [
        "remote LLM requested but LLM support is disabled; used deterministic fallback"
    ]
```

- [ ] **Step 2: Add failing option-conflict test**

In `tests/integration/test_cli.py`:

```python
def test_report_rejects_no_llm_with_remote_authorization() -> None:
    result = runner.invoke(
        cli.app,
        [
            "report",
            "--days",
            "7",
            "--no-llm",
            "--allow-remote-llm",
            "--dry-run",
        ],
    )

    assert result.exit_code == 2
    assert "cannot be used together" in result.stdout
```

- [ ] **Step 3: Add failing warning-propagation test**

In `tests/unit/services/test_report.py`, add a minimal test using existing service test doubles in that file. Construct `ReportService` with:

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

Use an existing non-empty `ScanResult` fixture from the file so report generation reaches rendering; do not duplicate repository-resolution setup.

- [ ] **Step 4: Run focused tests and confirm failures**

Run:

```bash
uv run pytest \
  tests/unit/test_cli.py \
  tests/unit/services/test_report.py \
  tests/integration/test_cli.py \
  -v
```

Expected: missing selection helper, missing option, and missing initial-warning support.

- [ ] **Step 5: Implement centralized remote selection**

In `src/agent_worklog/cli.py`:

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

Modify `src/agent_worklog/services/report.py`:

```python
def __init__(
    self,
    *,
    scan_service: ScanService,
    summarizer: RepositorySummarizer,
    renderer: Renderer | MarkdownRenderer,
    period: DateRange,
    output_path: Path,
    now_factory: Callable[[], datetime],
    usage_provider: Callable[[ScanResult], str] | None = None,
    usage_days: int | None = None,
    detail: DetailLevel = DetailLevel.FULL,
    progress: ProgressReporter | None = None,
    initial_warnings: list[str] | None = None,
) -> None:
    ...
    self._initial_warnings = list(initial_warnings or [])
```

At generation start:

```python
warnings = [*self._initial_warnings, *scan.warnings]
```

All warnings still pass through the existing `redact_text` call before entering `WorklogReport`.

- [ ] **Step 7: Add `--allow-remote-llm` and use the selection helper**

Add to the `report` command:

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

Extend validation:

```python
_validate_privacy_options(
    harness=harness,
    sanitize=sanitize,
    no_llm=no_llm,
    allow_remote_llm=allow_remote_llm,
)
```

Extend `_build_report_service(..., allow_remote_llm: bool = False)` and replace the current implicit API-key decision:

```python
summarizer = RuleBasedSummarizer()
api_key = os.environ.get(settings.llm.api_key_env)
remote_enabled, initial_warnings = _remote_llm_selection(
    settings=settings,
    api_key=api_key,
    no_llm=no_llm,
    allow_remote_llm=allow_remote_llm,
)
if remote_enabled:
    assert api_key is not None
    summarizer = OpenAICompatibleSummarizer(
        model=settings.llm.model,
        api_key=api_key,
        base_url=settings.llm.base_url,
        timeout_seconds=settings.llm.timeout_seconds,
        fallback=RuleBasedSummarizer(),
    )
```

Pass `initial_warnings=initial_warnings` into `ReportService`.

- [ ] **Step 8: Update report builder stubs explicitly**

Every test replacement for `_build_report_service` must accept:

```python
allow_remote_llm=False,
```

The real CLI call must pass `allow_remote_llm=allow_remote_llm`.

- [ ] **Step 9: Add constructor-selection integration tests**

In `tests/integration/test_cli.py`, retain the existing `test_no_llm_never_constructs_http_summarizer` and add:

```python
def test_api_key_alone_does_not_construct_http_summarizer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret-key")
    monkeypatch.setattr(cli, "_build_scan_service", lambda *args, **kwargs: object())

    def fail_constructor(**kwargs):
        raise AssertionError("remote summarizer requires explicit authorization")

    monkeypatch.setattr(cli, "OpenAICompatibleSummarizer", fail_constructor)

    service = cli._build_report_service(
        cli.AppSettings(),
        DateRange.previous_week(now=datetime(2026, 7, 29, 20, 0, tzinfo=TZ)),
        tmp_path / "report.md",
        no_llm=False,
        allow_remote_llm=False,
        now=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )

    assert service is not None
```

Add a positive constructor test using a capturing fake rather than real HTTP:

```python
def test_remote_authorization_constructs_http_summarizer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setenv("OPENAI_API_KEY", "secret-key")
    monkeypatch.setattr(cli, "_build_scan_service", lambda *args, **kwargs: object())

    class StubRemoteSummarizer:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(cli, "OpenAICompatibleSummarizer", StubRemoteSummarizer)

    service = cli._build_report_service(
        cli.AppSettings(),
        DateRange.previous_week(now=datetime(2026, 7, 29, 20, 0, tzinfo=TZ)),
        tmp_path / "report.md",
        no_llm=False,
        allow_remote_llm=True,
        now=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )

    assert service is not None
    assert captured["api_key"] == "secret-key"
```

- [ ] **Step 10: Run focused tests**

Run:

```bash
uv run pytest \
  tests/unit/test_cli.py \
  tests/unit/services/test_report.py \
  tests/integration/test_cli.py \
  -v
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add \
  src/agent_worklog/cli.py \
  src/agent_worklog/services/report.py \
  tests/unit/test_cli.py \
  tests/unit/services/test_report.py \
  tests/integration/test_cli.py
git commit -m "feat: require remote LLM opt-in"
```

---

### Task 5: Prove raw and sanitized behavior end to end

**Files:**
- Modify: `tests/conftest.py`
- Modify: the existing acceptance test file that consumes `mocked_opencode`
- Modify: `tests/fixtures/opencode/` only if a sanitized fixture is not already present

**Interfaces:**
- Consumes: `AcceptanceCommandRunner.export_calls: list[list[str]]`
- Produces: deterministic raw and sanitized export responses for acceptance tests

- [ ] **Step 1: Locate the existing OpenCode acceptance test file**

Run:

```bash
rg -n "mocked_opencode|AcceptanceCommandRunner" tests
```

Expected: one fixture definition in `tests/conftest.py` and one acceptance test module that consumes `mocked_opencode`. Extend that module; do not create a second parallel acceptance pipeline.

- [ ] **Step 2: Add a sanitized export fixture**

Create `tests/fixtures/opencode/export-sanitized.json` with this complete minimal payload:

```json
{
  "info": {
    "title": "[redacted:session-title:sanitized-session]",
    "directory": "[redacted:session-directory:sanitized-session]"
  },
  "messages": [
    {
      "info": {
        "id": "m-sanitized",
        "role": "user"
      },
      "parts": [
        {
          "type": "text",
          "text": "[redacted:text:p-sanitized]"
        }
      ]
    }
  ]
}
```

Extend `AcceptanceCommandRunner` with a dedicated session row whose DB metadata is usable:

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

Map it in `self.exports`:

```python
"sanitized-session": "export-sanitized.json",
```

- [ ] **Step 3: Make the acceptance runner distinguish the command shape**

The runner already records `export_calls`. Keep returning the same fixture for a session regardless of flags, but assert command shape in tests. Do not make the fake silently append or remove `--sanitize`.

- [ ] **Step 4: Add raw-default acceptance assertions**

In the existing OpenCode acceptance test, after report generation:

```python
assert mocked_opencode.export_calls
assert all("--sanitize" not in call for call in mocked_opencode.export_calls)
assert "Build" in result.content or "session" in result.content
assert "[redacted:" not in result.content
```

Use a stable fixture-derived work phrase already asserted elsewhere in that acceptance file rather than adding a broad snapshot.

- [ ] **Step 5: Add sanitized-mode acceptance test**

Construct the real service with `sanitize=True` and a period containing `sanitized-session`. Assert:

```python
assert [
    call for call in mocked_opencode.export_calls if call[2] == "sanitized-session"
] == [["opencode", "export", "sanitized-session", "--sanitize"]]
assert "Database sanitized title" in result.content
assert "[redacted:" not in result.content
```

Also assert the sanitized user message does not appear as a goal or in-progress item.

- [ ] **Step 6: Add default-local LLM acceptance assertion**

Set `OPENAI_API_KEY` in the acceptance test environment, omit `allow_remote_llm`, and monkeypatch `OpenAICompatibleSummarizer` to raise if constructed. Generate the report and assert success. This proves the API key alone no longer causes outbound summarization.

- [ ] **Step 7: Run acceptance tests**

Run:

```bash
uv run pytest tests/integration -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add tests/conftest.py tests/fixtures/opencode tests/integration
git commit -m "test: cover OpenCode privacy modes end to end"
```

---

### Task 6: Update documentation, release metadata, and full verification

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
- Produces: documented CLI contract and environment variable
- Produces: package version `0.6.0`

- [ ] **Step 1: Add failing documentation contract tests**

Append to `tests/unit/test_documentation.py`:

```python
def test_readmes_document_remote_llm_opt_in() -> None:
    for path in (Path("README.md"), Path("README.zh-TW.md")):
        text = path.read_text(encoding="utf-8")
        assert "--allow-remote-llm" in text
        assert "--sanitize" in text


def test_configuration_documents_opencode_sanitize_environment_variable() -> None:
    text = Path("docs/configuration.md").read_text(encoding="utf-8")

    assert "AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__SANITIZE" in text


def test_privacy_document_warns_about_raw_export_and_dry_run() -> None:
    text = Path("docs/privacy.md").read_text(encoding="utf-8").casefold()

    assert "raw" in text
    assert "--dry-run" in text
    assert "--allow-remote-llm" in text
```

Ensure `Path` is imported once at the top of the file.

- [ ] **Step 2: Run documentation tests and confirm failures**

Run:

```bash
uv run pytest tests/unit/test_documentation.py -v
```

Expected: missing flags and environment variable documentation.

- [ ] **Step 3: Update the English and Traditional Chinese landing pages**

Add these three canonical examples to both README files, translated naturally in `README.zh-TW.md`:

```bash
# Complete local report: raw OpenCode export, no remote LLM
agent-worklog report --days 7

# Ask OpenCode to redact exported session content
agent-worklog report --days 7 --sanitize

# Explicitly authorize remote summarization for this invocation
agent-worklog report --days 7 --allow-remote-llm
```

State explicitly:

- raw OpenCode export is the default;
- remote summarization is disabled unless `--allow-remote-llm` is supplied;
- OpenCode sanitization removes most report evidence.

- [ ] **Step 4: Update detailed guides**

`docs/configuration.md` must include:

```bash
AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__SANITIZE=true
```

and the precedence order:

```text
CLI --sanitize/--no-sanitize
> environment/application settings
> default false
```

`docs/guides.md` must explain the local default and one-command remote authorization.

`docs/privacy.md` must explain:

- raw JSON is parsed in memory and not cached;
- extracted evidence and rendered Markdown still pass through the existing local redactor;
- `--dry-run` prints potentially sensitive report content to terminal or CI logs;
- only `--allow-remote-llm` permits sending extracted evidence externally.

`docs/limitations.md` must explain that `--sanitize` deliberately produces a limited report and placeholders are omitted rather than reconstructed.

- [ ] **Step 5: Add the v0.6.0 changelog entry**

At the top of `CHANGELOG.md`, following the repository's existing format, add a `0.6.0` section that prominently states:

```markdown
- OpenCode sessions are exported without `--sanitize` by default so work details remain available.
- `--sanitize/--no-sanitize` and `AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__SANITIZE` control OpenCode redaction.
- Remote LLM summaries now require `--allow-remote-llm` on each invocation.
- `--no-llm` and `--allow-remote-llm` cannot be combined.
```

- [ ] **Step 6: Bump package version and refresh the lockfile**

Change in `pyproject.toml`:

```toml
version = "0.6.0"
```

Run:

```bash
uv lock
```

Verify the root package entry in `uv.lock` reports `version = "0.6.0"`.

- [ ] **Step 7: Run documentation and version tests**

Run:

```bash
uv run pytest tests/unit/test_documentation.py -v
uv run python -c 'from importlib.metadata import version; print(version("agent-worklog"))'
```

Expected: documentation tests PASS and printed version is `0.6.0`.

- [ ] **Step 8: Run the complete verification suite**

Run in this order:

```bash
uv run ruff check .
uv run pyright
uv run pytest
```

Expected:

- Ruff exits 0.
- Pyright reports 0 errors.
- Full pytest suite passes.

- [ ] **Step 9: Inspect CLI help contracts**

Run:

```bash
uv run agent-worklog scan --help
uv run agent-worklog report --help
```

Verify:

- both commands show `--sanitize / --no-sanitize`;
- only `report` shows `--allow-remote-llm`;
- help text states OpenCode-only and per-invocation behavior.

- [ ] **Step 10: Manual no-network smoke test**

With an API key present, run a one-day dry report without remote authorization:

```bash
OPENAI_API_KEY=dummy-not-used \
uv run agent-worklog report \
  --harness opencode \
  --days 1 \
  --no-llm \
  --dry-run >/tmp/agent-worklog-smoke.md
```

Then verify no raw placeholder appears:

```bash
! rg '\[redacted:' /tmp/agent-worklog-smoke.md
rm -f /tmp/agent-worklog-smoke.md
```

The explicit `--no-llm` makes this smoke test independent of network access; automated tests cover the default-local behavior without that flag.

- [ ] **Step 11: Commit**

```bash
git add \
  README.md \
  README.zh-TW.md \
  docs/configuration.md \
  docs/guides.md \
  docs/privacy.md \
  docs/limitations.md \
  CHANGELOG.md \
  tests/unit/test_documentation.py \
  pyproject.toml \
  uv.lock
git commit -m "release: prepare 0.6.0 privacy defaults"
```

---

## Final Review Checklist

- [ ] Every spec requirement maps to a task above.
- [ ] No production path persists or logs raw OpenCode export JSON.
- [ ] Default OpenCode command is exactly `opencode export <session-id>`.
- [ ] Sanitized command is exactly `opencode export <session-id> --sanitize`.
- [ ] CLI setting precedence is covered in unit and integration tests.
- [ ] Claude Code and Codex reject explicit sanitize flags before scanning.
- [ ] API key presence alone never constructs `OpenAICompatibleSummarizer`.
- [ ] Explicit remote authorization without a usable configuration creates a report warning.
- [ ] Existing local evidence redaction remains active for local and remote summarizers.
- [ ] Sanitized placeholders never reach report evidence or Markdown.
- [ ] `README.md` and `README.zh-TW.md` describe both privacy controls.
- [ ] Package and lockfile versions are `0.6.0`.
- [ ] Ruff, Pyright, and the complete pytest suite pass.
