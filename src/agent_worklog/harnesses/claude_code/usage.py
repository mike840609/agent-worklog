"""Aggregate Claude Code token usage from mapped session activities."""

from __future__ import annotations

from agent_worklog.errors import HarnessSourceError
from agent_worklog.services.scan import ScanResult

_COLUMNS = (
    ("Input", "input_tokens"),
    ("Output", "output_tokens"),
    ("Cache read", "cache_read_tokens"),
    ("Cache write", "cache_write_tokens"),
)


def _totals_by_model(scan: ScanResult) -> dict[str, dict[str, int]]:
    totals: dict[str, dict[str, int]] = {}
    for resolved in scan.resolved_sessions:
        for activity in resolved.session.activities:
            model = activity.metadata.get("model")
            usage = activity.metadata.get("usage")
            if not isinstance(model, str) or not isinstance(usage, dict):
                continue
            row = totals.setdefault(model, {})
            for _, key in _COLUMNS:
                value = usage.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    row[key] = row.get(key, 0) + value
    return totals


def render_claude_code_usage(scan: ScanResult) -> str:
    """Return an aligned per-model token table for the scanned sessions.

    Unlike `opencode stats`, this covers exactly the report period: usage rides
    on the activities that `filter_session_to_period` already narrowed.
    """

    totals = _totals_by_model(scan)
    if not totals:
        raise HarnessSourceError("Claude Code sessions carried no token usage")

    ordered = sorted(
        totals.items(),
        key=lambda item: (-item[1].get("output_tokens", 0), item[0]),
    )
    grand_total = {
        key: sum(row.get(key, 0) for _, row in ordered) for _, key in _COLUMNS
    }

    headers = ["Model", *(label for label, _ in _COLUMNS)]
    rows = [
        [model, *(f"{row.get(key, 0):,}" for _, key in _COLUMNS)]
        for model, row in ordered
    ]
    rows.append(["Total", *(f"{grand_total[key]:,}" for _, key in _COLUMNS)])

    widths = [
        max(len(cell) for cell in column) for column in zip(headers, *rows, strict=True)
    ]
    lines = [_format_row(headers, widths)]
    lines.extend(_format_row(row, widths) for row in rows)
    return "\n".join(lines)


def _format_row(cells: list[str], widths: list[int]) -> str:
    first = cells[0].ljust(widths[0])
    rest = "".join(
        f"  {cell.rjust(width)}" for cell, width in zip(cells[1:], widths[1:], strict=True)
    )
    return first + rest
