from agent_worklog.config import AppSettings
from agent_worklog.services.doctor import run_doctor


def test_doctor_checks_opencode_version_db_path_and_git(fake_runner) -> None:
    fake_runner.set_output("opencode --version", "1.0.0\n")
    fake_runner.set_output("opencode db path", "/tmp/opencode.db\n")
    fake_runner.set_output("git --version", "git version 2.47\n")

    result = run_doctor(AppSettings(), runner=fake_runner)

    assert result.ok is True
    assert fake_runner.calls == [
        ["opencode", "--version"],
        ["opencode", "db", "path"],
        ["git", "--version"],
    ]
    assert all(check.ok for check in result.checks)
