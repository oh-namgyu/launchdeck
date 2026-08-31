"""Rendering: a fixed-width table for humans and the v1 JSON contract."""

import json
import os
import shlex
import sys
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, TextIO

from .model import (
    ActionResult,
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

# Doctor severities get their own two colors.
_SEVERITY_COLORS = {"warn": "\033[33m", "info": "\033[90m"}

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only
    from .findings import Finding, Report

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


def format_size(size: Optional[int]) -> str:
    """Render a byte count compactly, e.g. ``12 B`` / ``3.4 KB``."""
    value = float(size or 0)
    for unit in ("B", "KB", "MB"):
        if value < 1024:
            fmt = "{0:.0f} {1}" if unit == "B" else "{0:.1f} {1}"
            return fmt.format(value, unit)
        value /= 1024.0
    return "{0:.1f} GB".format(value)


def _state_cell(state: str, color: bool) -> str:
    """Render ``symbol state``, colored when the terminal allows it."""
    cell = "{0} {1}".format(STATE_SYMBOL.get(state, "?"), state)
    prefix = _COLORS.get(state, "") if color else ""
    return prefix + cell + (_RESET if prefix else "")


def _describe_log(entry: Dict[str, Any]) -> str:
    """One-line summary of a log file: path plus existence and size."""
    path = entry.get("path")
    if not path:
        return "(not set in plist)"
    if not entry.get("exists"):
        return "{0} (missing)".format(shorten_path(path))
    return "{0} ({1})".format(shorten_path(path), format_size(entry.get("size")))


def _describe_schedule(detail: Dict[str, Any]) -> str:
    """Schedule summary followed by the raw plist keys behind it."""
    summary = detail.get("schedule") or "on-demand"
    keys = detail.get("raw_schedule_keys") or []
    return "{0}  [{1}]".format(summary, ", ".join(keys)) if keys else summary


def _info_rows(detail: Dict[str, Any], color: bool) -> List[Sequence[str]]:
    """Build the (name, value) pairs of the detail block."""
    logs = detail.get("log_files") or {}
    arguments = detail.get("program_arguments") or []
    pid = detail.get("pid")
    last_exit = detail.get("last_exit")
    return [
        ("label", detail.get("label", "-")),
        ("state", _state_cell(detail.get("state", STATE_UNKNOWN), color)),
        ("pid", str(pid) if pid is not None else "-"),
        ("last exit", str(last_exit) if last_exit is not None else "-"),
        ("plist", shorten_path(detail.get("plist_path"))),
        ("command", " ".join(shlex.quote(a) for a in arguments) or "-"),
        ("schedule", _describe_schedule(detail)),
        ("stdout", _describe_log(logs.get("stdout") or {})),
        ("stderr", _describe_log(logs.get("stderr") or {})),
    ]


def render_info(
    detail: Dict[str, Any],
    as_json: bool = False,
    stream: Optional[TextIO] = None,
) -> str:
    """Render one job's detail block, or its ``{"schema": 1, "job": {...}}``."""
    if as_json:
        payload = {"schema": SCHEMA_VERSION, "job": detail}
        return json.dumps(payload, indent=2, ensure_ascii=False)

    rows = _info_rows(detail, use_color(stream))
    width = max(len(name) for name, _value in rows)
    out = ["{0}  {1}".format(name.ljust(width), value) for name, value in rows]

    printed = detail.get("launchctl_print") or {}
    out.append("")
    out.append("launchctl print:")
    if printed:
        key_width = max(len(key) for key in printed)
        out.extend(
            "  {0}  {1}".format(key.ljust(key_width), value)
            for key, value in printed.items()
        )
    else:
        out.append("  (not available - job not loaded, or launchctl said nothing)")
    return "\n".join(out)


def render_action(result: ActionResult, as_json: bool = False) -> str:
    """Render a lifecycle outcome: ``ldm: <line>`` per message, or JSON."""
    if as_json:
        payload = {"schema": SCHEMA_VERSION, "result": result.to_dict()}
        return json.dumps(payload, indent=2, ensure_ascii=False)
    return "\n".join("ldm: {0}".format(line) for line in result.lines)


def summary_line(report: "Report") -> str:
    """The closing count line of a doctor run."""
    return "{0} warning{1}, {2} notice{3} across {4} job{5}".format(
        report.warnings,
        "" if report.warnings == 1 else "s",
        report.notices,
        "" if report.notices == 1 else "s",
        report.subjects,
        "" if report.subjects == 1 else "s",
    )


def _finding_lines(finding: "Finding", color: bool) -> List[str]:
    """Render one finding as its severity line plus its suggestion line."""
    prefix = _SEVERITY_COLORS.get(finding.severity, "") if color else ""
    reset = _RESET if prefix else ""
    return [
        "  {0}{1}{2}  {3} - {4}".format(
            prefix,
            finding.severity.ljust(4),
            reset,
            shorten_path(finding.subject),
            finding.message,
        ),
        "        -> {0}".format(finding.suggestion),
    ]


def render_doctor(
    report: "Report",
    as_json: bool = False,
    stream: Optional[TextIO] = None,
) -> str:
    """Render a doctor report grouped by check, or its JSON contract."""
    if as_json:
        payload = {"schema": SCHEMA_VERSION}
        payload.update(report.to_dict())
        return json.dumps(payload, indent=2, ensure_ascii=False)

    if not report.findings:
        return "No problems found."

    color = use_color(stream)
    out: List[str] = []
    for title, findings in report.grouped():
        out.append("== {0} ({1}) ==".format(title, len(findings)))
        for finding in findings:
            out.extend(_finding_lines(finding, color))
        out.append("")
    out.append(summary_line(report))
    return "\n".join(out)


def render_log_section(name: str, path: Optional[str], body: str) -> str:
    """Render one ``== stdout: <path> ==`` block followed by its lines."""
    shown = shorten_path(path) if path else "(not set in plist)"
    header = "== {0}: {1} ==".format(name, shown)
    return "{0}\n{1}".format(header, body) if body else header
