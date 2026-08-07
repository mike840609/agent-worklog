from __future__ import annotations


def _escape_workflow_command(value: object) -> str:
    return (
        str(value)
        .replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
    )


def pytest_runtest_logreport(report) -> None:
    if not report.failed:
        return
    message = _escape_workflow_command(report.longrepr)
    nodeid = _escape_workflow_command(report.nodeid)
    print(f"::error title=pytest {nodeid}::{message}")
