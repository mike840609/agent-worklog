from pathlib import Path


def test_readme_documents_release_gate_commands() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "pipx install agent-worklog" in readme
    assert "agent-worklog doctor" in readme
    assert "agent-worklog scan --period last-week" in readme
    assert "agent-worklog report --period last-week" in readme


def test_readmes_document_interactive_progress() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh_tw = Path("README.zh-TW.md").read_text(encoding="utf-8")

    assert "transient progress status" in readme
    assert "`--quiet` hides the progress status" in readme
    assert "暫時性的進度狀態" in readme_zh_tw
    assert "`--quiet` 會隱藏進度狀態" in readme_zh_tw
