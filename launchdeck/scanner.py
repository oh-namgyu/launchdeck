"""Scan a LaunchAgents directory and turn each plist into a JobRecord.

This module never runs `launchctl`; it only reads plist files from disk. The
runtime overlay lives in ``merge.py``.
"""

import os
import plistlib
from typing import Any, Dict, List, Optional, Sequence

from .model import STATE_UNKNOWN, STATE_UNLOADED, JobRecord

DEFAULT_AGENTS_DIR = "~/Library/LaunchAgents"

_WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")

# Scheduling keys reported verbatim by ``ldm info``, in the order shown.
SCHEDULE_KEYS = ("StartInterval", "StartCalendarInterval", "KeepAlive", "RunAtLoad")


def agents_dir(path: Optional[str] = None) -> str:
    """Resolve the LaunchAgents directory, expanding ``~``."""
    return os.path.abspath(os.path.expanduser(path or DEFAULT_AGENTS_DIR))


def _format_interval(seconds: int) -> str:
    """Render a StartInterval in seconds as a compact human summary."""
    if seconds <= 0:
        return "on-demand"
    if seconds % 86400 == 0:
        return "every {0}d".format(seconds // 86400)
    if seconds % 3600 == 0:
        return "every {0}h".format(seconds // 3600)
    if seconds % 60 == 0:
        return "every {0}m".format(seconds // 60)
    return "every {0}s".format(seconds)


def _format_calendar_entry(entry: Dict[str, Any]) -> str:
    """Render one StartCalendarInterval dict, e.g. ``daily 09:40``."""
    hour = entry.get("Hour")
    minute = entry.get("Minute")
    weekday = entry.get("Weekday")
    day = entry.get("Day")
    month = entry.get("Month")

    if hour is None and minute is not None:
        return "hourly :{0:02d}".format(int(minute))
    if hour is None:
        return "calendar"

    clock = "{0:02d}:{1:02d}".format(int(hour), int(minute or 0))
    if weekday is not None:
        return "{0} {1}".format(_WEEKDAYS[int(weekday) % 7], clock)
    if day is not None and month is not None:
        return "{0}/{1} {2}".format(int(month), int(day), clock)
    if day is not None:
        return "monthly {0} {1}".format(int(day), clock)
    return "daily {0}".format(clock)


def _format_calendar(value: Any) -> str:
    """Render StartCalendarInterval which may be a dict or a list of dicts."""
    entries = value if isinstance(value, list) else [value]
    entries = [e for e in entries if isinstance(e, dict)]
    if not entries:
        return "calendar"
    first = _format_calendar_entry(entries[0])
    if len(entries) > 1:
        return "{0} +{1}".format(first, len(entries) - 1)
    return first


def summarize_schedule(data: Dict[str, Any]) -> str:
    """Summarize a plist's scheduling keys into one short phrase."""
    if data.get("KeepAlive"):
        return "keepalive"
    interval = data.get("StartInterval")
    if isinstance(interval, int) and not isinstance(interval, bool):
        return _format_interval(interval)
    if "StartCalendarInterval" in data:
        return _format_calendar(data["StartCalendarInterval"])
    if data.get("RunAtLoad"):
        return "at-load"
    return "on-demand"


def _program(data: Dict[str, Any]) -> List[str]:
    """Extract the command line from ProgramArguments or Program."""
    args = data.get("ProgramArguments")
    if isinstance(args, list):
        return [str(a) for a in args]
    program = data.get("Program")
    if isinstance(program, str):
        return [program]
    return []


def _label_from_filename(path: str) -> str:
    """Fall back to the file name (minus ``.plist``) when Label is missing."""
    base = os.path.basename(path)
    return base[: -len(".plist")] if base.endswith(".plist") else base


def read_plist(path: str) -> JobRecord:
    """Parse a single plist file into a JobRecord.

    Never raises: an unreadable or malformed plist degrades to a record with
    ``state="unknown"`` so one bad file cannot break the whole inventory.
    """
    try:
        with open(path, "rb") as handle:
            data = plistlib.load(handle)
        if not isinstance(data, dict):
            raise ValueError("plist root is not a dictionary")
    except Exception:
        return JobRecord(
            label=_label_from_filename(path),
            plist_path=path,
            schedule="?",
            state=STATE_UNKNOWN,
        )

    label = data.get("Label")
    if not isinstance(label, str) or not label:
        label = _label_from_filename(path)

    stdout_path = data.get("StandardOutPath")
    stderr_path = data.get("StandardErrorPath")
    return JobRecord(
        label=label,
        plist_path=path,
        schedule=summarize_schedule(data),
        stdout_path=stdout_path if isinstance(stdout_path, str) else None,
        stderr_path=stderr_path if isinstance(stderr_path, str) else None,
        state=STATE_UNLOADED,
        program=_program(data),
        raw_schedule_keys=[key for key in SCHEDULE_KEYS if key in data],
    )


def plist_files(directory: Optional[str] = None) -> List[str]:
    """List ``*.plist`` files in the directory, sorted. Other files are ignored."""
    root = agents_dir(directory)
    try:
        names = os.listdir(root)
    except OSError:
        return []
    found = [
        os.path.join(root, name)
        for name in names
        if name.endswith(".plist") and os.path.isfile(os.path.join(root, name))
    ]
    return sorted(found)


def scan(directory: Optional[str] = None) -> List[JobRecord]:
    """Scan a LaunchAgents directory into JobRecords, sorted by label."""
    records = [read_plist(path) for path in plist_files(directory)]
    records.sort(key=lambda record: record.label.lower())
    return records


def non_plist_files(directory: Optional[str] = None) -> Sequence[str]:
    """List leftover non-plist files (e.g. ``.bak``). Used by ``doctor`` later."""
    root = agents_dir(directory)
    try:
        names = os.listdir(root)
    except OSError:
        return []
    return sorted(
        os.path.join(root, name)
        for name in names
        if not name.endswith(".plist")
        and not name.startswith(".")
        and os.path.isfile(os.path.join(root, name))
    )
