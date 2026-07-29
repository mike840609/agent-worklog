"""Rich console helpers for already-redacted user-facing messages."""

from pathlib import Path

from rich.console import Console
from rich.table import Table

from agent_worklog.services.scan import ScanResult


class ConsoleReporter:
    """Render concise CLI output; callers must pass redacted strings."""

    def __init__(
        self,
        *,
        quiet: bool = False,
        verbose: bool = False,
        console: Console | None = None,
    ) -> None:
        self.quiet = quiet
        self.verbose = verbose
        self.console = console or Console()

    def message(self, text: str) -> None:
        if not self.quiet:
            self.console.print(text)

    def output_path(self, path: Path) -> None:
        self.console.print(str(path))

    def doctor_check(self, name: str, ok: bool, detail: str) -> None:
        if self.quiet:
            return
        status = "[green]OK[/green]" if ok else "[red]ERROR[/red]"
        self.console.print(f"[{status}] {name}: {detail}")

    def scan_result(self, result: ScanResult) -> None:
        if self.quiet:
            self.console.print(str(result.loaded_session_count))
            return
        table = Table(title="Agent Worklog Scan")
        table.add_column("Repository")
        table.add_column("Identity")
        table.add_column("Sessions", justify="right")
        for repository_id, sessions in result.sessions_by_repository.items():
            name = sessions[0].repository.display_name if sessions else repository_id
            table.add_row(name, repository_id, str(len(sessions)))
        self.console.print(table)
        if self.verbose:
            for warning in result.warnings:
                self.console.print(f"[yellow]Warning:[/yellow] {warning}")
