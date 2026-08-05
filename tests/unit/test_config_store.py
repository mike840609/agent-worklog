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
