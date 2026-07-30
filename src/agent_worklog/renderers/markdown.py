"""Markdown rendering for worklog reports."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from agent_worklog.models.report import WorklogReport

# The renderer is the report's only truncation point. Both summarizers now emit
# complete lists, so the omitted-item count below is always the real remainder.
_FULL_SECTION_LIMIT = 20


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

    def render(self, report: WorklogReport) -> str:
        tzinfo = report.period.since.tzinfo
        timezone = getattr(tzinfo, "key", str(tzinfo))
        output = self._template.render(
            report=report,
            timezone=timezone,
            section_limit=_FULL_SECTION_LIMIT,
        )
        return f"{output.rstrip()}\n"
