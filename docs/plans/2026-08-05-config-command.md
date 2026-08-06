# `agent-worklog config` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user set up Agent Worklog with `agent-worklog config set <key> <value>` instead of hand-writing `export AGENT_WORKLOG_...` lines, and show in `agent-worklog config list` that every setting is optional and falls back to a documented default.

**Architecture:** A new `config_store.py` derives the settable key list from the `AppSettings` model tree, so nothing hand-maintains a key registry. Values are persisted as a dotenv file (`config.env`) in the platformdirs user config directory; `pydantic-settings` already loads dotenv files natively, so `AppSettings(_env_file=...)` is the whole integration and real environment variables keep winning over the file. A `config` Typer sub-app exposes `path`, `list`, `set`, and `unset`.

**Tech Stack:** Python 3.11+, pydantic v2 / pydantic-settings, `python-dotenv` (already installed as a required dependency of pydantic-settings), `platformdirs` (already a declared dependency), Typer, Rich, pytest, `uv`.

## Global Constraints

- **No new dependencies.** `python-dotenv` arrives with `pydantic-settings>=2.7`, and `platformdirs>=4,<5` is already declared in `pyproject.toml` (currently unused in `src/`). Do not add either to `pyproject.toml` — `python-dotenv` is transitive by design, `platformdirs` is already there.
- Precedence is **environment variable > settings file > model default**, in that order. This is what `pydantic-settings` already does with `_env_file`; do not reimplement it.
- Every setting is optional. `config set <key> ""` and `config unset <key>` both mean "remove the file entry and use the model default". No field in `config.py` becomes nullable, and `config.py`'s field definitions are not changed by this plan.
- The settable key list is **derived** from `AppSettings.model_fields`, never hand-written. A key is dotted lowercase (`llm.model`); its variable is `AGENT_WORKLOG_` + uppercase + `__` between parts (`AGENT_WORKLOG_LLM__MODEL`).
- `config set`/`config unset` must never construct `AppSettings`. A single bad value must not make the tool that repairs it unusable.
- Settings-file errors exit with code **3** (`ConfigurationError`), matching every other settings failure. Do not introduce a new exit code.
- The settings file is created mode `0600` on POSIX.
- Every commit keeps `uv run pytest --cov=agent_worklog --cov-fail-under=80`, `uv run ruff check .` and `uv run pyright` green. Line length 100; ruff rules `E,F,I,UP,B,SIM`.
- Comments explain *why*, matching the density of the surrounding modules. American English in code and docs; `README.md` is English, `README.zh-TW.md` is Traditional Chinese.

## File Structure

| File | Responsibility |
|---|---|
| `src/agent_worklog/config_store.py` | **New.** Locate the settings file; derive the key catalog from the model tree; validate, read, write, and remove entries; describe each setting's value and source. |
| `src/agent_worklog/cli.py` | **Modify.** `_load_settings()` layers the file under the environment; a `config` Typer sub-app adds `path`, `list`, `set`, `unset`. |
| `src/agent_worklog/logging.py` | **Modify.** One `settings_table()` method on `ConsoleReporter`, so `cli.py` stays free of Rich imports. |
| `tests/unit/test_config_store.py` | **New.** Catalog, path resolution, validation, file read/write, source reporting. |
| `tests/unit/test_logging.py` | **Modify.** The settings table renders keys, sources, defaults, and the optional-settings footer. |
| `tests/unit/test_cli.py` | **Modify.** `_load_settings()` precedence. |
| `tests/integration/test_cli.py` | **Modify.** The four `config` commands end to end. |
| `tests/unit/test_documentation.py` | **Modify.** Docs pin the command surface; every variable in `docs/configuration.md` is a real key. |
| `docs/configuration.md`, `README.md`, `README.zh-TW.md`, `CHANGELOG.md` | **Modify.** Document the file, the commands, and the precedence order. |

---

### Task 1: The settings key catalog

Derive every settable key from the `AppSettings` model tree, and locate the settings file. No file I/O yet.

**Files:**
- Create: `src/agent_worklog/config_store.py`
- Test: `tests/unit/test_config_store.py` (create)

**Interfaces:**
- Consumes: `agent_worklog.config.AppSettings`, `agent_worklog.errors.ConfigurationError`.
- Produces:
  - `ENV_PREFIX: str = "AGENT_WORKLOG_"`, `CONFIG_FILE_VARIABLE: str = "AGENT_WORKLOG_CONFIG_FILE"`
  - `config_file_path() -> Path`
  - `SettingKey` — frozen dataclass with `key: str`, `variable: str`, `annotation: type`, `default: str`
  - `setting_keys() -> tuple[SettingKey, ...]`
  - `resolve_key(key: str) -> SettingKey` — raises `ConfigurationError` for an unknown key
  - `validate_value(setting: SettingKey, value: str) -> None` — raises `ConfigurationError` for a value the model would reject

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_config_store.py`:

```python
from pathlib import Path

import pytest

from agent_worklog.config_store import (
    config_file_path,
    resolve_key,
    setting_keys,
    validate_value,
)
from agent_worklog.errors import ConfigurationError


def test_setting_keys_cover_the_leaves_of_the_settings_tree() -> None:
    keys = {setting.key: setting for setting in setting_keys()}

    assert keys["llm.model"].variable == "AGENT_WORKLOG_LLM__MODEL"
    assert keys["llm.model"].default == "gpt-5-mini"
    assert keys["harnesses.opencode.cli.executable"].variable == (
        "AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__EXECUTABLE"
    )
    # A container is a path to settings, not a setting.
    assert "harnesses" not in keys
    assert "harnesses.opencode.cli" not in keys


def test_setting_key_defaults_are_rendered_the_way_a_user_types_them() -> None:
    keys = {setting.key: setting for setting in setting_keys()}

    assert keys["harnesses.codex.enabled"].default == "true"
    assert keys["harnesses.claude_code.projects_directory"].default == str(
        Path.home() / ".claude" / "projects"
    )
    assert keys["llm.timeout_seconds"].default == "60.0"


def test_config_file_path_follows_an_explicit_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(tmp_path / "custom.env"))

    assert config_file_path() == tmp_path / "custom.env"


def test_config_file_path_defaults_into_the_user_config_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_WORKLOG_CONFIG_FILE", raising=False)

    path = config_file_path()

    assert path.name == "config.env"
    assert "agent-worklog" in str(path)


def test_resolve_key_suggests_the_closest_key_for_a_typo() -> None:
    with pytest.raises(ConfigurationError) as error:
        resolve_key("llm.mdoel")

    assert "did you mean llm.model" in str(error.value)


def test_resolve_key_rejects_a_key_with_no_close_match() -> None:
    with pytest.raises(ConfigurationError, match="unknown setting: nope.at.all"):
        resolve_key("nope.at.all")


def test_validate_value_rejects_a_timeout_that_is_not_a_number() -> None:
    with pytest.raises(ConfigurationError, match="invalid value for llm.timeout_seconds"):
        validate_value(resolve_key("llm.timeout_seconds"), "abc")


def test_validate_value_accepts_the_boolean_spellings_env_settings_use() -> None:
    validate_value(resolve_key("llm.enabled"), "false")
    validate_value(resolve_key("harnesses.codex.enabled"), "true")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_config_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_worklog.config_store'`.

- [ ] **Step 3: Write the catalog**

Create `src/agent_worklog/config_store.py`:

```python
"""Locate, inspect, and edit the user's settings file."""

from __future__ import annotations

import difflib
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_dir
from pydantic import BaseModel, TypeAdapter, ValidationError

from agent_worklog.config import AppSettings
from agent_worklog.errors import ConfigurationError

ENV_PREFIX = "AGENT_WORKLOG_"
CONFIG_FILE_VARIABLE = "AGENT_WORKLOG_CONFIG_FILE"


def config_file_path() -> Path:
    """Return the settings file, honoring an explicit override.

    The override is what makes the file testable, and it doubles as the escape
    hatch for anyone who wants a per-project file instead of one per machine.
    """

    override = os.environ.get(CONFIG_FILE_VARIABLE)
    if override:
        return Path(override).expanduser()
    return Path(user_config_dir("agent-worklog")) / "config.env"


def _as_text(value: object) -> str:
    """Render a default the way a user would type it into the file."""

    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@dataclass(frozen=True)
class SettingKey:
    """One settable leaf: its dotted name, its variable, and its fallback."""

    key: str
    variable: str
    annotation: type
    default: str


def _walk(model: type[BaseModel], prefix: tuple[str, ...]) -> Iterator[SettingKey]:
    for name, field in model.model_fields.items():
        annotation = field.annotation
        path = (*prefix, name)
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            yield from _walk(annotation, path)
            continue
        default = field.get_default(call_default_factory=True, validated_data={})
        dotted = ".".join(path)
        yield SettingKey(
            key=dotted,
            variable=ENV_PREFIX + dotted.upper().replace(".", "__"),
            annotation=annotation if isinstance(annotation, type) else str,
            default=_as_text(default),
        )


def setting_keys() -> tuple[SettingKey, ...]:
    """Every settable leaf, derived from the model tree, not a hand-kept list.

    A new field in `config.py` becomes settable the moment it exists; neither
    this module nor the CLI has to learn its name.
    """

    return tuple(_walk(AppSettings, ()))


def resolve_key(key: str) -> SettingKey:
    """Reject an unknown key before it can reach the file."""

    index = {setting.key: setting for setting in setting_keys()}
    normalized = key.strip().lower()
    found = index.get(normalized)
    if found is not None:
        return found
    suggestions = difflib.get_close_matches(normalized, index, n=1)
    hint = f"; did you mean {suggestions[0]}?" if suggestions else ""
    raise ConfigurationError(f"unknown setting: {key}{hint}")


def validate_value(setting: SettingKey, value: str) -> None:
    """Reject a value the settings model would reject at load time.

    Environment values arrive as strings, so this is the same parse
    pydantic-settings performs: a bad number fails here, not on the next run.
    """

    try:
        TypeAdapter(setting.annotation).validate_strings(value)
    except ValidationError as exc:
        detail = exc.errors()[0]["msg"]
        raise ConfigurationError(f"invalid value for {setting.key}: {detail}") from exc
```

Note on `get_default(call_default_factory=True, validated_data={})`: pydantic 2.10+ allows a default factory that takes the already-validated data, so pyright requires the second argument. Every factory in `config.py` takes none, and passing `{}` satisfies both.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_config_store.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Run the gates**

Run: `uv run ruff check . && uv run pyright && uv run pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/agent_worklog/config_store.py tests/unit/test_config_store.py
git commit -m "feat: derive the settable key catalog from the settings model"
```

---

### Task 2: Read and write the settings file

Persist values as dotenv entries. `python-dotenv` handles quoting and in-place editing, so nothing here parses or serializes the format.

**Files:**
- Modify: `src/agent_worklog/config_store.py` (append)
- Test: `tests/unit/test_config_store.py` (modify)

**Interfaces:**
- Consumes: `SettingKey`, `config_file_path`, `resolve_key`, `validate_value` from Task 1.
- Produces:
  - `SettingRow` — frozen dataclass with `key: str`, `variable: str`, `value: str`, `source: str`, `default: str`; `source` is one of `"environment"`, `"file"`, `"default"`
  - `stored_values(path: Path | None = None) -> dict[str, str]`
  - `set_value(key: str, value: str, *, path: Path | None = None) -> SettingKey`
  - `unset_value(key: str, *, path: Path | None = None) -> tuple[SettingKey, bool]` — the bool is whether the file actually held the key
  - `describe_settings(path: Path | None = None) -> tuple[SettingRow, ...]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_config_store.py`, and add these imports to the existing import block at the top of the file:

```python
from agent_worklog.config_store import (
    CONFIG_FILE_VARIABLE,
    describe_settings,
    set_value,
    stored_values,
    unset_value,
)
```

```python
@pytest.fixture
def settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the store at a throwaway file for the duration of one test."""

    path = tmp_path / "config.env"
    monkeypatch.setenv(CONFIG_FILE_VARIABLE, str(path))
    return path


def test_set_value_writes_the_environment_variable_form(settings_file: Path) -> None:
    set_value("llm.model", "gpt-5")

    assert stored_values(settings_file) == {"AGENT_WORKLOG_LLM__MODEL": "gpt-5"}


def test_set_value_creates_an_owner_only_file(settings_file: Path) -> None:
    set_value("llm.model", "gpt-5")

    assert settings_file.stat().st_mode & 0o777 == 0o600


def test_set_value_replaces_an_earlier_entry_for_the_same_key(settings_file: Path) -> None:
    set_value("llm.model", "gpt-5")
    set_value("llm.model", "gpt-5-mini")

    assert stored_values(settings_file) == {"AGENT_WORKLOG_LLM__MODEL": "gpt-5-mini"}


def test_set_value_keeps_a_value_containing_spaces_intact(settings_file: Path) -> None:
    set_value("report.output_directory", "/tmp/my reports")

    assert stored_values(settings_file) == {
        "AGENT_WORKLOG_REPORT__OUTPUT_DIRECTORY": "/tmp/my reports"
    }


def test_set_value_refuses_a_bad_value_without_creating_the_file(
    settings_file: Path,
) -> None:
    with pytest.raises(ConfigurationError):
        set_value("llm.timeout_seconds", "abc")

    assert not settings_file.exists()


def test_unset_value_removes_the_entry_and_reports_that_it_did(
    settings_file: Path,
) -> None:
    set_value("llm.model", "gpt-5")

    setting, removed = unset_value("llm.model")

    assert (setting.key, removed) == ("llm.model", True)
    assert stored_values(settings_file) == {}


def test_unset_value_on_a_key_that_was_never_set_is_a_quiet_no_op(
    settings_file: Path,
) -> None:
    setting, removed = unset_value("llm.model")

    assert (setting.key, removed) == ("llm.model", False)


def test_describe_settings_reports_where_each_value_comes_from(
    settings_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_value("llm.model", "gpt-5")
    monkeypatch.setenv("AGENT_WORKLOG_REPORT__TIMEZONE", "UTC")
    monkeypatch.delenv("AGENT_WORKLOG_LLM__MODEL", raising=False)

    rows = {row.key: row for row in describe_settings()}

    assert (rows["llm.model"].value, rows["llm.model"].source) == ("gpt-5", "file")
    assert rows["llm.model"].default == "gpt-5-mini"
    assert (rows["report.timezone"].value, rows["report.timezone"].source) == (
        "UTC",
        "environment",
    )
    assert (rows["llm.provider"].value, rows["llm.provider"].source) == (
        "openai-compatible",
        "default",
    )


def test_describe_settings_lets_the_environment_win_over_the_file(
    settings_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_value("llm.model", "from-file")
    monkeypatch.setenv("AGENT_WORKLOG_LLM__MODEL", "from-environment")

    rows = {row.key: row for row in describe_settings()}

    assert (rows["llm.model"].value, rows["llm.model"].source) == (
        "from-environment",
        "environment",
    )


def test_describe_settings_works_without_a_settings_file(settings_file: Path) -> None:
    rows = {row.key: row for row in describe_settings()}

    assert not settings_file.exists()
    assert rows["llm.model"].source == "default"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_config_store.py -v`
Expected: FAIL — `ImportError: cannot import name 'set_value' from 'agent_worklog.config_store'`.

- [ ] **Step 3: Write the file layer**

Add `dotenv` to the imports at the top of `src/agent_worklog/config_store.py`, immediately above the `platformdirs` import so ruff's import sort (`I`) is satisfied:

```python
from dotenv import dotenv_values, set_key, unset_key
```

Add `SettingRow` directly below the `SettingKey` dataclass:

```python
@dataclass(frozen=True)
class SettingRow:
    """One setting as `config list` shows it."""

    key: str
    variable: str
    value: str
    source: str
    default: str
```

Append to the end of the module:

```python
def _prepare_file(path: Path) -> None:
    """Create the file owner-only before dotenv writes to it.

    dotenv would create a world-readable file, and what is in the user's config
    directory is nobody else's business.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    if os.name == "posix":
        path.chmod(0o600)


def stored_values(path: Path | None = None) -> dict[str, str]:
    """Return the variables the settings file defines, ignoring valueless lines."""

    file_path = path or config_file_path()
    values = dotenv_values(file_path)
    return {name: value for name, value in values.items() if value is not None}


def set_value(key: str, value: str, *, path: Path | None = None) -> SettingKey:
    """Record one setting, replacing any earlier entry for it."""

    setting = resolve_key(key)
    # Validate before touching the disk: a rejected value must not leave a file
    # behind that the user then has to clean up.
    validate_value(setting, value)
    file_path = path or config_file_path()
    _prepare_file(file_path)
    written, _, _ = set_key(str(file_path), setting.variable, value)
    if not written:
        raise ConfigurationError(f"failed to write settings file: {file_path}")
    return setting


def unset_value(key: str, *, path: Path | None = None) -> tuple[SettingKey, bool]:
    """Remove one setting; report whether the file actually held it."""

    setting = resolve_key(key)
    file_path = path or config_file_path()
    if setting.variable not in stored_values(file_path):
        # Asking dotenv to remove an absent key logs a warning to stderr, and a
        # no-op is not a warning: the user asked for the default and has it.
        return setting, False
    unset_key(str(file_path), setting.variable)
    return setting, True


def describe_settings(path: Path | None = None) -> tuple[SettingRow, ...]:
    """Report every setting with the value in force and where it comes from.

    Deliberately built from the file and the environment rather than from a
    loaded `AppSettings`: one bad value must not stop `config list` from showing
    which value is bad, or `config unset` from removing it.
    """

    file_path = path or config_file_path()
    stored = stored_values(file_path)
    rows = []
    for setting in setting_keys():
        environment_value = os.environ.get(setting.variable)
        file_value = stored.get(setting.variable)
        if environment_value is not None:
            value, source = environment_value, "environment"
        elif file_value is not None:
            value, source = file_value, "file"
        else:
            value, source = setting.default, "default"
        rows.append(
            SettingRow(
                key=setting.key,
                variable=setting.variable,
                value=value,
                source=source,
                default=setting.default,
            )
        )
    return tuple(rows)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_config_store.py -v`
Expected: PASS (18 tests)

- [ ] **Step 5: Run the gates**

Run: `uv run ruff check . && uv run pyright && uv run pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/agent_worklog/config_store.py tests/unit/test_config_store.py
git commit -m "feat: read and write settings as a dotenv file"
```

---

### Task 3: Load the settings file under the environment

`AppSettings` gains no new code: `pydantic-settings` already layers a dotenv file below environment variables. The one change is where `cli.py` gets the file from.

**Files:**
- Modify: `src/agent_worklog/cli.py:69-73` (`_load_settings`)
- Test: `tests/unit/test_cli.py` (modify)

**Interfaces:**
- Consumes: `config_store.config_file_path` from Task 1.
- Produces: `_load_settings()` reads `config_file_path()`; environment variables still win.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cli.py`:

```python
def test_load_settings_reads_the_settings_file(monkeypatch, tmp_path) -> None:
    import agent_worklog.cli as cli

    path = tmp_path / "config.env"
    path.write_text("AGENT_WORKLOG_LLM__MODEL='from-file'\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))
    monkeypatch.delenv("AGENT_WORKLOG_LLM__MODEL", raising=False)

    assert cli._load_settings().llm.model == "from-file"


def test_the_environment_beats_the_settings_file(monkeypatch, tmp_path) -> None:
    """The file is a default store, not an override: an exported variable wins."""

    import agent_worklog.cli as cli

    path = tmp_path / "config.env"
    path.write_text("AGENT_WORKLOG_LLM__MODEL='from-file'\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))
    monkeypatch.setenv("AGENT_WORKLOG_LLM__MODEL", "from-environment")

    assert cli._load_settings().llm.model == "from-environment"


def test_load_settings_points_at_the_file_when_it_holds_a_bad_value(
    monkeypatch, tmp_path
) -> None:
    import pytest

    import agent_worklog.cli as cli
    from agent_worklog.errors import ConfigurationError

    path = tmp_path / "config.env"
    path.write_text("AGENT_WORKLOG_LLM__TIMEOUT_SECONDS='abc'\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))

    with pytest.raises(ConfigurationError) as error:
        cli._load_settings()

    assert str(path) in str(error.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_cli.py -k settings_file -v`
Expected: FAIL — the model stays `gpt-5-mini`, because `_load_settings()` reads no file yet.

- [ ] **Step 3: Layer the file under the environment**

In `src/agent_worklog/cli.py`, add to the imports (after `from agent_worklog.config import AppSettings`):

```python
from agent_worklog import config_store
```

Replace `_load_settings`:

```python
def _load_settings() -> AppSettings:
    """Load settings, layering the settings file below the environment.

    pydantic-settings gives environment variables precedence over `_env_file`,
    which is the order `config set` promises: the file holds defaults, an
    exported variable overrides them for one shell.
    """

    path = config_store.config_file_path()
    try:
        return AppSettings(_env_file=path)
    except Exception as exc:  # Pydantic aggregates configuration failures.
        # Name the file when there is one: a parse error otherwise says what is
        # wrong without saying where the value came from.
        hint = f"; check {path}" if path.exists() else ""
        raise ConfigurationError(f"{exc}{hint}") from exc
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Run the gates**

Run: `uv run ruff check . && uv run pyright && uv run pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/agent_worklog/cli.py tests/unit/test_cli.py
git commit -m "feat: load the settings file below environment variables"
```

---

### Task 4: `config path` and `config list`

The read-only half of the command group. `config list` is where the user learns that every setting is optional and what each one falls back to.

**Files:**
- Modify: `src/agent_worklog/logging.py` (add `ConsoleReporter.settings_table`)
- Modify: `src/agent_worklog/cli.py` (append the `config` sub-app with `path` and `list`)
- Test: `tests/unit/test_logging.py` (modify), `tests/integration/test_cli.py` (modify)

**Interfaces:**
- Consumes: `config_store.describe_settings`, `config_store.config_file_path`, `config_store.SettingRow`.
- Produces:
  - `ConsoleReporter.settings_table(rows: Sequence[SettingRow], *, path: Path) -> None`
  - `cli.config_app: typer.Typer` registered on `app` as `config`
  - Commands `config path`, `config list`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_logging.py` (it already defines `forced_console`):

```python
def test_settings_table_shows_values_sources_and_defaults() -> None:
    from pathlib import Path

    from agent_worklog.config_store import SettingRow

    output_stream = StringIO()
    reporter = ConsoleReporter(console=forced_console(output_stream, width=120))

    reporter.settings_table(
        [
            SettingRow(
                key="llm.model",
                variable="AGENT_WORKLOG_LLM__MODEL",
                value="gpt-5",
                source="file",
                default="gpt-5-mini",
            ),
            SettingRow(
                key="report.timezone",
                variable="AGENT_WORKLOG_REPORT__TIMEZONE",
                value="Asia/Taipei",
                source="default",
                default="Asia/Taipei",
            ),
        ],
        path=Path("/home/dev/.config/agent-worklog/config.env"),
    )
    output = output_stream.getvalue()

    assert "llm.model" in output
    assert "gpt-5-mini" in output
    assert "file" in output
    assert "/home/dev/.config/agent-worklog/config.env" in output
    # The point of the footer: nothing here is required.
    assert "Every setting is optional" in output
```

Append to `tests/integration/test_cli.py`, which already imports `agent_worklog.cli as cli`
and `CliRunner` at module level:

```python
def test_config_path_prints_the_settings_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(tmp_path / "config.env"))

    result = CliRunner().invoke(cli.app, ["config", "path"])

    assert result.exit_code == 0
    assert result.stdout.strip() == str(tmp_path / "config.env")


def test_config_list_shows_the_value_in_force_and_its_source(monkeypatch, tmp_path) -> None:
    path = tmp_path / "config.env"
    path.write_text("AGENT_WORKLOG_LLM__MODEL='from-file'\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))
    monkeypatch.delenv("AGENT_WORKLOG_LLM__MODEL", raising=False)
    # Rich wraps to 80 columns when stdout is not a terminal, which would split
    # the longer settings across lines and break these substring assertions.
    monkeypatch.setenv("COLUMNS", "200")

    result = CliRunner().invoke(cli.app, ["config", "list"])

    assert result.exit_code == 0
    assert "llm.model" in result.stdout
    assert "from-file" in result.stdout
    assert "gpt-5-mini" in result.stdout
    assert "Every setting is optional" in result.stdout


def test_help_lists_the_config_command() -> None:
    result = CliRunner().invoke(cli.app, ["--help"])

    assert result.exit_code == 0
    assert "config" in result.stdout
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_logging.py tests/integration/test_cli.py -k "settings_table or config_path or config_list or config_command" -v`
Expected: FAIL — `AttributeError: 'ConsoleReporter' object has no attribute 'settings_table'`, and the CLI exits 2 with "No such command 'config'".

- [ ] **Step 3: Render the table**

In `src/agent_worklog/logging.py`, extend the first import line to bring in `Sequence`:

```python
from collections.abc import Iterator, Sequence
```

Add the store import below the existing `agent_worklog` imports:

```python
from agent_worklog.config_store import SettingRow
```

Add the method to `ConsoleReporter`, after `doctor_check`:

```python
    def settings_table(self, rows: Sequence[SettingRow], *, path: Path) -> None:
        """Render every setting with the value in force and where it came from.

        Values are wrapped in `Text` rather than redacted: these are the user's
        own settings, printed at their own request, and `redact_text` would
        mangle a legitimate value that happens to look like a secret.
        """

        table = Table(title="Agent Worklog Settings")
        table.add_column("Setting")
        table.add_column("Value")
        table.add_column("From")
        table.add_column("Default")
        for row in rows:
            table.add_row(row.key, Text(row.value), row.source, Text(row.default))
        self.console.print(table)
        self.console.print(f"Settings file: {path}")
        self.console.print(
            "Every setting is optional. Leave one out — or set it to an empty "
            "value — to fall back to the default in the last column."
        )
```

- [ ] **Step 4: Add the read-only commands**

Append to the end of `src/agent_worklog/cli.py`:

```python
config_app = typer.Typer(
    no_args_is_help=True,
    help="Show and edit the settings file.",
)
app.add_typer(config_app, name="config")


@config_app.command("path")
def config_path() -> None:
    """Print the settings file location."""

    typer.echo(str(config_store.config_file_path()))


@config_app.command("list")
def config_list() -> None:
    """Show every setting, the value in force, and where it comes from."""

    path = config_store.config_file_path()
    ConsoleReporter().settings_table(config_store.describe_settings(path), path=path)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_logging.py tests/integration/test_cli.py -v`
Expected: PASS

- [ ] **Step 6: Run the gates**

Run: `uv run ruff check . && uv run pyright && uv run pytest -q`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/agent_worklog/logging.py src/agent_worklog/cli.py tests/unit/test_logging.py tests/integration/test_cli.py
git commit -m "feat: add config path and config list"
```

---

### Task 5: `config set` and `config unset`

The write half. An empty value means "use the default", and a setting the environment already overrides says so, because otherwise the write looks like it did nothing.

**Files:**
- Modify: `src/agent_worklog/cli.py` (append to the `config` sub-app)
- Test: `tests/integration/test_cli.py` (modify)

**Interfaces:**
- Consumes: `config_store.set_value`, `config_store.unset_value`, `config_store.SettingKey`.
- Produces: commands `config set <key> <value>` and `config unset <key>`; both exit 3 on an unknown key or a rejected value.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_cli.py`:

```python
def test_config_set_writes_the_value_and_the_next_load_reads_it(monkeypatch, tmp_path) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))
    monkeypatch.delenv("AGENT_WORKLOG_LLM__MODEL", raising=False)

    result = CliRunner().invoke(cli.app, ["config", "set", "llm.model", "gpt-5"])

    assert result.exit_code == 0
    assert cli._load_settings().llm.model == "gpt-5"


def test_config_set_rejects_an_unknown_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(tmp_path / "config.env"))

    result = CliRunner().invoke(cli.app, ["config", "set", "llm.mdoel", "gpt-5"])

    assert result.exit_code == 3
    assert "did you mean llm.model" in result.stdout


def test_config_set_rejects_a_value_the_settings_model_would_reject(
    monkeypatch, tmp_path
) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))

    result = CliRunner().invoke(
        cli.app, ["config", "set", "llm.timeout_seconds", "abc"]
    )

    assert result.exit_code == 3
    assert "invalid value for llm.timeout_seconds" in result.stdout
    assert not path.exists()


def test_config_set_with_an_empty_value_restores_the_default(monkeypatch, tmp_path) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))
    monkeypatch.delenv("AGENT_WORKLOG_LLM__MODEL", raising=False)
    CliRunner().invoke(cli.app, ["config", "set", "llm.model", "gpt-5"])

    result = CliRunner().invoke(cli.app, ["config", "set", "llm.model", ""])

    assert result.exit_code == 0
    assert "gpt-5-mini" in result.stdout
    assert cli._load_settings().llm.model == "gpt-5-mini"


def test_config_unset_restores_the_default(monkeypatch, tmp_path) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(path))
    monkeypatch.delenv("AGENT_WORKLOG_LLM__MODEL", raising=False)
    CliRunner().invoke(cli.app, ["config", "set", "llm.model", "gpt-5"])

    result = CliRunner().invoke(cli.app, ["config", "unset", "llm.model"])

    assert result.exit_code == 0
    assert cli._load_settings().llm.model == "gpt-5-mini"


def test_config_unset_of_an_unset_key_says_the_default_is_already_in_use(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(tmp_path / "config.env"))
    monkeypatch.setenv("COLUMNS", "200")

    result = CliRunner().invoke(cli.app, ["config", "unset", "llm.model"])

    assert result.exit_code == 0
    assert "already using default" in result.stdout


def test_config_set_warns_when_the_environment_overrides_the_write(
    monkeypatch, tmp_path
) -> None:
    """Without this note the write is a silent no-op for the whole shell."""

    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(tmp_path / "config.env"))
    monkeypatch.setenv("AGENT_WORKLOG_LLM__MODEL", "from-environment")
    monkeypatch.setenv("COLUMNS", "200")

    result = CliRunner().invoke(cli.app, ["config", "set", "llm.model", "gpt-5"])

    assert result.exit_code == 0
    assert "AGENT_WORKLOG_LLM__MODEL" in result.stdout
    assert "takes precedence" in result.stdout
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/integration/test_cli.py -k "config_set or config_unset" -v`
Expected: FAIL — exit code 2, "No such command 'set'".

- [ ] **Step 3: Add the write commands**

Append to the end of `src/agent_worklog/cli.py`:

```python
def _default_restored(setting: config_store.SettingKey, removed: bool) -> str:
    if removed:
        return f"Removed {setting.key}; using default: {setting.default}"
    return f"{setting.key} was not set; already using default: {setting.default}"


def _warn_if_shadowed(
    reporter: ConsoleReporter, setting: config_store.SettingKey
) -> None:
    """Say so when an exported variable overrides what was just written.

    The environment wins over the file, so without this the command reports
    success on a change the next run will ignore.
    """

    if os.environ.get(setting.variable) is not None:
        reporter.message(
            f"Note: {setting.variable} is set in the environment "
            "and takes precedence."
        )


@config_app.command("set")
def config_set(key: str, value: str) -> None:
    """Set one setting. An empty value restores its default."""

    reporter = ConsoleReporter()
    path = config_store.config_file_path()
    try:
        if value == "":
            # Every setting is optional, so "no value" is a real answer: drop
            # the entry rather than storing an empty string the model would
            # then have to interpret.
            setting, removed = config_store.unset_value(key, path=path)
            reporter.message(_default_restored(setting, removed))
        else:
            setting = config_store.set_value(key, value, path=path)
            reporter.message(f"{setting.key} = {value} ({path})")
    except ConfigurationError as exc:
        _handle_expected_error(exc, code=3)
        return
    _warn_if_shadowed(reporter, setting)


@config_app.command("unset")
def config_unset(key: str) -> None:
    """Remove one setting so its default applies again."""

    reporter = ConsoleReporter()
    try:
        setting, removed = config_store.unset_value(key)
    except ConfigurationError as exc:
        _handle_expected_error(exc, code=3)
        return
    reporter.message(_default_restored(setting, removed))
    _warn_if_shadowed(reporter, setting)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/integration/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Run the gates**

Run: `uv run ruff check . && uv run pyright && uv run pytest -q`
Expected: all green.

- [ ] **Step 6: Try it by hand**

Run:

```bash
export AGENT_WORKLOG_CONFIG_FILE="$(mktemp -d)/config.env"
uv run agent-worklog config path
uv run agent-worklog config set llm.model gpt-5
uv run agent-worklog config set report.timezone Europe/Berlin
uv run agent-worklog config list
uv run agent-worklog config set llm.model ""
uv run agent-worklog config unset report.timezone
uv run agent-worklog config set llm.timeout_seconds abc; echo "exit: $?"
```

Expected: `list` shows `llm.model` as `gpt-5` from `file`, the empty set and the unset both report the default, and the last command exits 3.

- [ ] **Step 7: Commit**

```bash
git add src/agent_worklog/cli.py tests/integration/test_cli.py
git commit -m "feat: add config set and config unset"
```

---

### Task 6: Document the settings file and the commands

**Files:**
- Modify: `docs/configuration.md`, `README.md`, `README.zh-TW.md`, `CHANGELOG.md`
- Test: `tests/unit/test_documentation.py` (modify)

**Interfaces:**
- Consumes: `config_store.setting_keys` (for the docs/model sync test).
- Produces: nothing the code depends on.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_documentation.py`:

```python
def test_readmes_document_the_config_command() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh_tw = Path("README.zh-TW.md").read_text(encoding="utf-8")

    for text in (readme, readme_zh_tw):
        assert "agent-worklog config set llm.model gpt-5" in text
        assert "agent-worklog config list" in text
        assert "agent-worklog config unset" in text


def test_configuration_doc_explains_the_file_and_its_precedence() -> None:
    configuration = Path("docs/configuration.md").read_text(encoding="utf-8")

    assert "config.env" in configuration
    assert "AGENT_WORKLOG_CONFIG_FILE" in configuration
    assert "agent-worklog config path" in configuration
    # The order is the whole contract of the file.
    assert "environment variable, then the settings file, then the default" in configuration


def test_every_variable_in_the_configuration_doc_is_a_real_setting() -> None:
    """Catch a documented setting the model dropped or renamed."""

    import re

    from agent_worklog.config_store import setting_keys

    configuration = Path("docs/configuration.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"AGENT_WORKLOG_[A-Z0-9_]+", configuration))
    known = {setting.variable for setting in setting_keys()}
    known.add("AGENT_WORKLOG_CONFIG_FILE")

    assert documented <= known, f"documented but not settable: {documented - known}"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_documentation.py -v`
Expected: FAIL on the three new tests — the docs say nothing about `config`.

- [ ] **Step 3: Rewrite the head of `docs/configuration.md`**

Replace lines 1-10 of `docs/configuration.md` (from `# Configuration` through `No YAML configuration file is loaded in the MVP.`) with:

```markdown
# Configuration

Agent Worklog reads every setting from an environment variable, and reads a settings
file for the ones the environment does not set. For each setting it takes the
environment variable, then the settings file, then the default.

- Prefix: `AGENT_WORKLOG_`
- Nested delimiter: `__`
- Boolean values: `true` or `false`

Every setting is optional. Leaving one out — or setting it to an empty value — uses
the default listed in the tables below.

## The settings file

`agent-worklog config` reads and writes a settings file so that a value survives the
shell it was set in:

```bash
agent-worklog config path                        # where the file is
agent-worklog config list                        # every setting, value, and source
agent-worklog config set llm.model gpt-5         # write one setting
agent-worklog config set llm.model ""            # empty value: back to the default
agent-worklog config unset llm.model             # same thing, spelled out
```

Keys are the lowercase, dot-separated form of the variable name, so
`AGENT_WORKLOG_LLM__MODEL` is `llm.model` and
`AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__EXECUTABLE` is
`harnesses.opencode.cli.executable`. `config list` shows both forms of every setting
with its current value, whether that value came from the environment, the file, or the
default, and what the default is.

The file is a `config.env` in the user configuration directory — run
`agent-worklog config path` to see the exact location, which differs by platform. Set
`AGENT_WORKLOG_CONFIG_FILE` to use a different file, such as one checked into a
project. The file is created readable and writable only by its owner.

An exported variable always beats the file, so `AGENT_WORKLOG_LLM__ENABLED=false
agent-worklog report --period last-week` still works with a file that enables the LLM.
`config set` says so when the setting it just wrote is already exported.

`config set` refuses an unknown key and a value the settings would reject, so a typo
fails at the moment you make it rather than on the next report. Both exit with code 3.
```

- [ ] **Step 4: Replace the CLI precedence section of `docs/configuration.md`**

Replace the final `## CLI precedence` section (lines 123-127 of the original file) with:

```markdown
## Precedence

For each setting, Agent Worklog takes the environment variable, then the settings file,
then the default. CLI period and output options apply to the current invocation only and
override the settings that back them.
```

- [ ] **Step 5: Document the command in `README.md`**

In the `## Command reference` table, add a row after `report`:

```markdown
| `config` | Shows and edits the settings file: `path`, `list`, `set`, `unset`. |
```

Replace the body of the `## Configuration` section (the paragraph, the `bash` block, and
the closing link) with:

```markdown
Agent Worklog reads every setting from an environment variable, and reads a settings
file for the ones the environment does not set. For each setting it takes the
environment variable, then the settings file, then the default.

Set a value once, in the settings file:

```bash
agent-worklog config set llm.model gpt-5
agent-worklog config set report.timezone Europe/Berlin
agent-worklog config list
```

`config list` shows every setting with its current value, whether that value came from
the environment, the file, or the default, and what the default is. Every setting is
optional: an empty value restores the default, and so does `unset`.

```bash
agent-worklog config set llm.model ""
agent-worklog config unset report.timezone
```

`agent-worklog config path` prints the file location. Set `AGENT_WORKLOG_CONFIG_FILE`
to use a different file.

Variable names start with `AGENT_WORKLOG_`, with `__` between parts of a setting name.
An exported variable overrides the file for that shell:

```bash
export AGENT_WORKLOG_REPORT__TIMEZONE="Asia/Taipei"
export AGENT_WORKLOG_LLM__ENABLED="false"
```

See the
[configuration guide](https://github.com/mike840609/agent-worklog/blob/main/docs/configuration.md)
for a complete list of settings.
```

- [ ] **Step 6: Document the command in `README.zh-TW.md`**

In the `## 指令參考` table, add a row after `report`:

```markdown
| `config` | 顯示與編輯設定檔：`path`、`list`、`set`、`unset`。 |
```

Replace the body of the `## 設定` section with:

```markdown
Agent Worklog 的每項設定都先讀環境變數，環境變數沒有設定的部分則讀設定檔。每項設定的
順序是：環境變數、設定檔、預設值。

設定一次就會寫進設定檔：

```bash
agent-worklog config set llm.model gpt-5
agent-worklog config set report.timezone Europe/Berlin
agent-worklog config list
```

`config list` 會列出每項設定的目前值、該值來自環境變數、設定檔或預設值，以及預設值本身。
每項設定都是選填的：值留空即回到預設值，`unset` 也是同樣的效果。

```bash
agent-worklog config set llm.model ""
agent-worklog config unset report.timezone
```

`agent-worklog config path` 會印出設定檔位置。設定 `AGENT_WORKLOG_CONFIG_FILE` 可以改用
其他檔案。

變數名稱以 `AGENT_WORKLOG_` 開頭，設定名稱的各層之間用 `__` 分隔。已匯出的環境變數在該
shell 中會覆蓋設定檔：

```bash
export AGENT_WORKLOG_REPORT__TIMEZONE="Asia/Taipei"
export AGENT_WORKLOG_LLM__ENABLED="false"
```

完整設定清單請見
[設定指南](https://github.com/mike840609/agent-worklog/blob/main/docs/configuration.md)。
```

- [ ] **Step 7: Add the changelog entry**

Under `## Unreleased` in `CHANGELOG.md`:

```markdown
- Add `agent-worklog config` with `path`, `list`, `set`, and `unset`, so a setting can be
  recorded once instead of exported from a shell profile. Values go to a `config.env` in
  the user configuration directory, which pydantic-settings loads below the environment:
  an exported variable still wins, and `config set` says so when one already shadows the
  setting it just wrote.
- Report every setting as optional. `config list` shows each setting's value, whether it
  came from the environment, the file, or the default, and what the default is; setting a
  value to the empty string removes the entry and restores the default, as `unset` does.
- Derive the settable key list from the settings model rather than a hand-kept registry,
  so a new field in `config.py` is settable and listed the moment it exists. `config set`
  rejects an unknown key — with the closest match as a hint — and a value the settings
  would reject, both with exit code 3.
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_documentation.py -v`
Expected: PASS

- [ ] **Step 9: Run the gates**

Run: `uv run ruff check . && uv run pyright && uv run pytest --cov=agent_worklog --cov-fail-under=80`
Expected: all green.

- [ ] **Step 10: Commit**

```bash
git add docs/configuration.md README.md README.zh-TW.md CHANGELOG.md tests/unit/test_documentation.py
git commit -m "docs: document the settings file and the config command"
```

---

## Out of scope

Deliberately not built. Each has a trigger for revisiting:

- **An interactive `config init` wizard.** `config list` plus `config set` covers first-time setup in two commands. Add it if users ask what to set rather than how.
- **`config get <key>`.** `config list` already shows every value and its source. Add it when something needs one value for a script.
- **A `doctor` check for the settings file.** `config list` never fails, and `_load_settings` names the file in its error. Add it if a broken file turns out to be a common support question.
- **Project-local file discovery (walking up for `.agent-worklog.env`).** `AGENT_WORKLOG_CONFIG_FILE` covers the per-project case in one variable. Add discovery when someone needs it without setting a variable.
