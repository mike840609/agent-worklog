from __future__ import annotations


def _escape(value: object) -> str:
    return str(value).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def pytest_runtest_logreport(report) -> None:
    if report.failed:
        print(f"::error title=pytest {_escape(report.nodeid)}::{_escape(report.longrepr)}")


def pytest_collectreport(report) -> None:
    if report.failed:
        print(f"::error title=pytest collection::{_escape(report.longrepr)}")
