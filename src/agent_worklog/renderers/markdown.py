"""Markdown rendering for worklog reports."""

from enum import StrEnum
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from agent_worklog.models.report import WorklogReport


class DetailLevel(StrEnum):
    BRIEF = "brief"
    FULL = "full"


# The renderer is the report's only truncation point. Both summarizers now emit
# complete lists, so the omitted-item count is always the real remainder.
_SECTION_LIMITS = {
    DetailLevel.FULL: 20,
    DetailLevel.BRIEF: 5,
}


class MarkdownRenderer:
    """Render a WorklogReport using the bundled safe summary template."""

    def __init__(self) -> None:
        template_directory = Path(__file__).parents[1] / "templates"
        environment = Environment(
            loader=FileSystemLoader(template_directory),
            undefined=StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )
        self._template = environment.get_template("worklog.md.j2")

    def render(
        self,
        report: WorklogReport,
        *,
        detail: DetailLevel = DetailLevel.FULL,
    ) -> str:
        # `detail` may arrive as a plain string from a library caller. StrEnum
        # hashes as `str`, so `_SECTION_LIMITS[detail]` below would already
        # succeed on `"full"`, but `detail is DetailLevel.FULL` would not — an
        # inconsistent state no CLI invocation can produce. Normalizing here
        # makes both checks agree and rejects unknown values outright.
        detail = DetailLevel(detail)
        tzinfo = report.period.since.tzinfo
        timezone = getattr(tzinfo, "key", str(tzinfo))
        output = self._template.render(
            report=report,
            timezone=timezone,
            section_limit=_SECTION_LIMITS[detail],
            full=detail is DetailLevel.FULL,
        )
        return f"{output.rstrip()}\n"
