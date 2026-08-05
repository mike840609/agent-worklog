"""Locate, inspect, and edit the user's settings file."""

from __future__ import annotations

import difflib
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values, set_key, unset_key
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


@dataclass(frozen=True)
class SettingRow:
    """One setting as `config list` shows it."""

    key: str
    variable: str
    value: str
    source: str
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
