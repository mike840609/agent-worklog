from pathlib import Path


def test_readme_documents_release_gate_commands() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "pipx install agent-worklog" in readme
    assert "agent-worklog doctor" in readme
    assert "agent-worklog scan --period last-week" in readme
    assert "agent-worklog report --period last-week" in readme


def test_readme_documents_the_harness_option() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "--harness" in readme
    assert "claude-code" in readme
    assert "Codex and Claude Code are not currently supported." not in readme


def test_limitations_documents_the_codex_limits() -> None:
    """Pin the three Codex-specific limits, not just that the word appears."""

    limitations = Path("docs/limitations.md").read_text(encoding="utf-8")

    assert "Codex report claims that a command passed or failed" in limitations
    assert "Commands run from inside Codex's `exec` tool are not recorded" in limitations
    assert "session titles are lost" in limitations


def test_privacy_documents_the_codex_limits() -> None:
    """Pin the substance of the Codex privacy boundary, not just the word "Codex"."""

    privacy = Path("docs/privacy.md").read_text(encoding="utf-8")

    assert "Codex report claims a command passed or failed" in privacy
    assert "arbitrary JavaScript program" in privacy
    assert "no `exit_code` and no `stderr_empty` for a Codex command" in privacy


def test_privacy_doc_explains_the_claude_code_sanitize_gap() -> None:
    privacy = Path("docs/privacy.md").read_text(encoding="utf-8")

    assert "claude-code" in privacy or "Claude Code" in privacy
    assert "sanitize" in privacy


def test_configuration_doc_lists_the_claude_code_settings() -> None:
    configuration = Path("docs/configuration.md").read_text(encoding="utf-8")

    assert "AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY" in configuration


def test_readmes_document_interactive_progress() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh_tw = Path("README.zh-TW.md").read_text(encoding="utf-8")

    assert "transient progress status" in readme
    assert "`--quiet` hides the progress status" in readme
    assert "暫時性的進度狀態" in readme_zh_tw
    assert "`--quiet` 會隱藏進度狀態" in readme_zh_tw


def test_readmes_document_the_report_detail_option() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh_tw = Path("README.zh-TW.md").read_text(encoding="utf-8")

    assert "`--detail LEVEL`" in readme
    assert "`--detail brief`" in readme
    assert "`--detail LEVEL`" in readme_zh_tw
    assert "`--detail brief`" in readme_zh_tw


def test_readmes_document_the_verbose_scan_session_listing() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh_tw = Path("README.zh-TW.md").read_text(encoding="utf-8")

    assert "lists each repository's session titles and working folders" in readme
    assert "列出每個 repository 的工作階段標題與工作目錄" in readme_zh_tw


def test_readmes_document_the_config_command() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh_tw = Path("README.zh-TW.md").read_text(encoding="utf-8")

    for text in (readme, readme_zh_tw):
        assert "agent-worklog config set opencode.cli.model deepseek-r1" in text
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


def test_readmes_document_privacy_controls() -> None:
    for path in (Path("README.md"), Path("README.zh-TW.md")):
        text = path.read_text(encoding="utf-8")
        assert "--sanitize" in text
        assert "--no-llm" in text
        assert "--allow-remote-llm" not in text


def test_readmes_document_the_local_opencode_narrative() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh_tw = Path("README.zh-TW.md").read_text(encoding="utf-8")

    assert "opencode run" in readme
    assert "OPENAPI" not in readme
    assert "opencode run" in readme_zh_tw


def test_configuration_documents_opencode_sanitize_setting() -> None:
    configuration = Path("docs/configuration.md").read_text(encoding="utf-8")

    assert "AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__SANITIZE" in configuration


def test_configuration_documents_opencode_run_settings() -> None:
    configuration = Path("docs/configuration.md").read_text(encoding="utf-8")

    assert "AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__RUN_TIMEOUT_SECONDS" in configuration
    assert "AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__MODEL" in configuration


def test_privacy_doc_warns_about_raw_export_and_dry_run() -> None:
    privacy = Path("docs/privacy.md").read_text(encoding="utf-8").casefold()

    assert "raw" in privacy
    assert "--dry-run" in privacy
    assert "opencode run" in privacy


def test_readmes_document_the_interactive_config_commands() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh_tw = Path("README.zh-TW.md").read_text(encoding="utf-8")

    for text in (readme, readme_zh_tw):
        assert "agent-worklog config init" in text
        assert "`path`, `list`, `init`, `set`, `unset`" in text or (
            "`path`、`list`、`init`、`set`、`unset`" in text
        )


def test_readmes_document_the_interactive_run_command() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh_tw = Path("README.zh-TW.md").read_text(encoding="utf-8")

    for text in (readme, readme_zh_tw):
        assert "agent-worklog run" in text
        assert "`run`" in text


def test_configuration_doc_explains_what_an_empty_answer_means() -> None:
    """The prompt's Enter key and `config set <key> ""` mean different things."""

    configuration = Path("docs/configuration.md").read_text(encoding="utf-8")

    assert "agent-worklog config init" in configuration
    assert 'an empty answer means "leave this as it is", not "erase it"' in configuration
    # Prompting in CI must fail rather than read stdin. Asserted without the
    # surrounding line break, so reflowing the paragraph does not break it.
    assert "rather than reading from stdin" in configuration
