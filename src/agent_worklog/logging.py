"""Rich console helpers for already-redacted user-facing messages."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from rich.console import Console
from rich.padding import Padding
from rich.status import Status
from rich.table import Table
from rich.text import Text

from agent_worklog.progress import (
    NullProgressReporter,
    ProgressReporter,
    ProgressStage,
)
from agent_worklog.security.redactor import redact_text
from agent_worklog.services.scan import ScanResult


def _collapse_whitespace(value: str) -> str:
    """Collapse whitespace so a free-text title stays on one console line."""

    return " ".join(value.split())


_STAGE_LABELS = {
    ProgressStage.DISCOVERING_SESSIONS: "Finding sessions",
    ProgressStage.EXPORTING_SESSIONS: "Exporting sessions",
    ProgressStage.PREPARING_EVIDENCE: "Preparing repository evidence",
    ProgressStage.SUMMARIZING_REPOSITORIES: "Summarizing repositories",
    ProgressStage.COLLECTING_USAGE: "Collecting usage statistics",
    ProgressStage.RENDERING_REPORT: "Rendering report",
    ProgressStage.WRITING_REPORT: "Writing report",
}


class RichProgressReporter:
    """Render one transient, continuously animated Rich status line."""

    def __init__(self, console: Console) -> None:
        self._console = console
        self._status: Status | None = None
        self._stage: ProgressStage | None = None
        self._total: int | None = None
        self._completed = 0

    def _description(self) -> Padding:
        assert self._stage is not None
        label = _STAGE_LABELS[self._stage]
        description = label
        if self._total is not None:
            description = f"{label} {self._completed}/{self._total}"
        text = Text(description, overflow="ellipsis", no_wrap=True)
        return Padding(text, (0, 0))

    def start(
        self,
        stage: ProgressStage,
        *,
        total: int | None = None,
    ) -> None:
        self._stage = stage
        self._total = total
        self._completed = 0
        description = self._description()
        if self._status is None:
            self._status = self._console.status(description, spinner="dots")
            self._status.start()
        else:
            self._status.update(description)

    def advance(self, completed: int) -> None:
        self._completed = completed
        if self._status is not None:
            self._status.update(self._description())

    def finish(self) -> None:
        status = self._status
        self._status = None
        self._stage = None
        if status is not None:
            status.stop()


class ConsoleReporter:
    """Render concise CLI output; callers must pass redacted strings."""

    def __init__(
        self,
        *,
        quiet: bool = False,
        verbose: bool = False,
        console: Console | None = None,
        progress_console: Console | None = None,
    ) -> None:
        self.quiet = quiet
        self.verbose = verbose
        self.console = console or Console()
        self.progress_console = progress_console or Console(stderr=True)

    @contextmanager
    def progress(self) -> Iterator[ProgressReporter]:
        progress: ProgressReporter
        if self.quiet:
            progress = NullProgressReporter()
        else:
            progress = RichProgressReporter(self.progress_console)
        try:
            yield progress
        finally:
            progress.finish()

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
            for repository_id, sessions in result.sessions_by_repository.items():
                name = sessions[0].repository.display_name if sessions else repository_id
                self.console.print(f"\n{name}", markup=False, highlight=False)
                for resolved in sessions:
                    session = resolved.session
                    title = _collapse_whitespace(session.title) if session.title else None
                    label = redact_text(title or session.session_id)
                    directory = session.working_directory
                    location = f" — {redact_text(directory)}" if directory else ""
                    self.console.print(
                        f"  • {label}{location}",
                        markup=False,
                        highlight=False,
                    )
