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
