"""Rendering: a fixed-width table for humans and the v1 JSON contract."""

import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, TextIO

from .model import (
    STATE_FAILING,
    STATE_GHOST,
    STATE_IDLE,
    STATE_RUNNING,
    STATE_UNKNOWN,
    STATE_UNLOADED,
    JobRecord,
)

SCHEMA_VERSION = 1

STATE_SYMBOL = {
    STATE_RUNNING: "●",  # filled circle
    STATE_IDLE: "○",  # hollow circle
    STATE_FAILING: "✗",  # ballot x
    STATE_UNLOADED: "–",  # en dash
    STATE_GHOST: "?",
    STATE_UNKNOWN: "?",
}

_COLORS = {
    STATE_RUNNING: "\033[32m",
    STATE_IDLE: "\033[90m",
    STATE_FAILING: "\033[31m",
    STATE_UNLOADED: "\033[90m",
    STATE_GHOST: "\033[33m",
    STATE_UNKNOWN: "\033[33m",
}
_RESET = "\033[0m"
_BOLD = "\033[1m"

HEADERS = ("STATE", "LABEL", "PID", "EXIT", "SCHEDULE", "PLIST")


def use_color(stream: Optional[TextIO] = None) -> bool:
    """Colors are enabled only for a TTY, and never when NO_COLOR is set."""
    if os.environ.get("NO_COLOR") is not None:
        return False
    stream = stream or sys.stdout
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def shorten_path(path: Optional[str]) -> str:
    """Replace the user's home directory with ``~`` for compact output."""
    if not path:
        return "-"
    home = os.path.expanduser("~")
    if home and path.startswith(home + os.sep):
        return "~" + path[len(home) :]
    return path


def _row(record: JobRecord) -> Sequence[str]:
    """Render one record as raw (uncolored) table cells."""
    symbol = STATE_SYMBOL.get(record.state, "?")
    return (
        "{0} {1}".format(symbol, record.state),
        record.label,
        str(record.pid) if record.pid is not None else "-",
        str(record.last_exit) if record.last_exit is not None else "-",
        record.schedule,
        shorten_path(record.plist_path),
    )


def render_table(records: Sequence[JobRecord], color: bool = False) -> str:
    """Render records as a fixed-width aligned table."""
    if not records:
        return "No LaunchAgents found."

    rows = [_row(record) for record in records]
    widths = [
        max(len(header), *(len(row[index]) for row in rows))
        for index, header in enumerate(HEADERS)
    ]

    def line(cells: Sequence[str], prefix: str = "", suffix: str = "") -> str:
        padded = [
            cells[index].ljust(widths[index]) for index in range(len(HEADERS) - 1)
        ]
        padded.append(cells[-1])
        return prefix + "  ".join(padded).rstrip() + suffix

    out: List[str] = []
    out.append(line(HEADERS, _BOLD if color else "", _RESET if color else ""))
    for record, cells in zip(records, rows):
        prefix = _COLORS.get(record.state, "") if color else ""
        out.append(line(cells, prefix, _RESET if prefix else ""))
    return "\n".join(out)


def to_json_payload(records: Sequence[JobRecord]) -> Dict[str, Any]:
    """Build the ``{"schema": 1, "jobs": [...]}`` contract payload."""
    return {"schema": SCHEMA_VERSION, "jobs": [r.to_dict() for r in records]}


def render_json(records: Sequence[JobRecord]) -> str:
    """Serialize the v1 JSON contract."""
    return json.dumps(to_json_payload(records), indent=2, ensure_ascii=False)


def render_status(
    records: Sequence[JobRecord],
    as_json: bool = False,
    stream: Optional[TextIO] = None,
) -> str:
    """Render the status view in the requested format."""
    if as_json:
        return render_json(records)
    return render_table(records, color=use_color(stream))
