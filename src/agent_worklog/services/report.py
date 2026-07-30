"""Repository worklog generation orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol, cast

from agent_worklog.errors import HarnessSourceError
from agent_worklog.extraction.pipeline import extract_evidence
from agent_worklog.models.evidence import RepositoryEvidence, SessionEvidence
from agent_worklog.models.report import RepositorySummary, WorklogReport
from agent_worklog.models.time_range import DateRange
from agent_worklog.progress import NullProgressReporter, ProgressReporter, ProgressStage
from agent_worklog.renderers.markdown import DetailLevel, MarkdownRenderer
from agent_worklog.security.redactor import redact_text, redact_value
from agent_worklog.security.secure_files import atomic_secure_write
from agent_worklog.services.scan import ScanResult, ScanService
from agent_worklog.sessions.hierarchy import count_child_sessions_by_repository
from agent_worklog.summarizers.base import RepositorySummarizer


class Renderer(Protocol):
    def render(
        self,
        report: WorklogReport,
        *,
        detail: DetailLevel = DetailLevel.FULL,
    ) -> str: ...


@dataclass(frozen=True)
class ReportGenerationResult:
    report: WorklogReport
    content: str
    output_path: Path
    scan: ScanResult

    @property
    def warnings(self) -> list[str]:
        """Return report warnings for CLI and integration consumers."""

        return self.report.warnings


class ReportService:
    """Generate a redacted repository-based Markdown worklog."""

    def __init__(
        self,
        *,
        scan_service: ScanService,
        summarizer: RepositorySummarizer,
        renderer: Renderer | MarkdownRenderer,
        period: DateRange,
        output_path: Path,
        now_factory: Callable[[], datetime],
        usage_provider: Callable[[ScanResult], str] | None = None,
        usage_days: int | None = None,
        detail: DetailLevel = DetailLevel.FULL,
        progress: ProgressReporter | None = None,
    ) -> None:
        self._scan_service = scan_service
        self._summarizer = summarizer
        self._renderer = renderer
        self._period = period
        self._output_path = output_path
        self._now_factory = now_factory
        self._usage_provider = usage_provider
        self._usage_days = usage_days
        self._detail = detail
        self._progress = progress if progress is not None else NullProgressReporter()

    def _repository_evidence(self, scan: ScanResult) -> list[RepositoryEvidence]:
        child_counts = count_child_sessions_by_repository(scan.resolved_sessions)
        repositories: list[RepositoryEvidence] = []
        self._progress.start(
            ProgressStage.PREPARING_EVIDENCE,
            total=len(scan.sessions_by_repository),
        )
        for completed, (repository_id, resolved_items) in enumerate(
            scan.sessions_by_repository.items(),
            start=1,
        ):
            first = resolved_items[0].repository
            sessions: list[SessionEvidence] = []
            branches: list[str] = []
            for resolved in resolved_items:
                extracted = extract_evidence(resolved)
                redacted = redact_value(extracted.model_dump(mode="json"))
                sessions.append(SessionEvidence.model_validate(redacted))
                branch = resolved.repository.branch
                if branch and branch not in branches:
                    branches.append(branch)
            repositories.append(
                RepositoryEvidence(
                    repository_id=repository_id,
                    display_name=first.display_name,
                    normalized_remote=first.normalized_remote,
                    branches=branches,
                    sessions=sessions,
                    child_session_count=child_counts.get(repository_id, 0),
                )
            )
            self._progress.advance(completed)
        return repositories

    def generate(
        self,
        *,
        force: bool = False,
        dry_run: bool = False,
    ) -> ReportGenerationResult:
        scan = self._scan_service.scan()
        warnings = list(scan.warnings)
        evidence_items = self._repository_evidence(scan)
        summaries: list[RepositorySummary] = []
        self._progress.start(
            ProgressStage.SUMMARIZING_REPOSITORIES,
            total=len(evidence_items),
        )
        for completed, evidence in enumerate(evidence_items, start=1):
            summaries.append(self._summarizer.summarize(evidence))
            drain_warnings = getattr(self._summarizer, "drain_warnings", None)
            if callable(drain_warnings):
                warnings.extend(cast(list[str], drain_warnings()))
            self._progress.advance(completed)
        summaries.sort(key=lambda item: item.display_name.casefold())
        usage_text: str | None = None
        if self._usage_provider is not None:
            self._progress.start(ProgressStage.COLLECTING_USAGE)
            try:
                usage_text = redact_text(self._usage_provider(scan))
            except HarnessSourceError as exc:
                warnings.append(f"usage statistics unavailable: {exc}")
        report = WorklogReport(
            generated_at=self._now_factory(),
            period=self._period,
            repositories=summaries,
            usage_text=usage_text,
            usage_days=self._usage_days if usage_text else None,
            warnings=[redact_text(warning) for warning in warnings],
        )
        self._progress.start(ProgressStage.RENDERING_REPORT)
        content = redact_text(self._renderer.render(report, detail=self._detail))
        if not dry_run:
            self._progress.start(ProgressStage.WRITING_REPORT)
            atomic_secure_write(self._output_path, content, force=force)
        return ReportGenerationResult(
            report=report,
            content=content,
            output_path=self._output_path,
            scan=scan,
        )
