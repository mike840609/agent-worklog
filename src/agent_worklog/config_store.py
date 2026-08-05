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
