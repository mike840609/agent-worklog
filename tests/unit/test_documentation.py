from pathlib import Path


def test_readme_documents_release_gate_commands() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "pipx install agent-worklog" in readme
    assert "agent-worklog doctor" in readme
    assert "agent-worklog scan --period last-week" in readme
    assert "agent-worklog report --period last-week" in readme
