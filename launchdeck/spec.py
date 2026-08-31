"""Turn ``ldm install`` flags into a validated LaunchAgent plist dictionary.

Nothing here touches the disk or launchd: this is pure validation and
translation, which is what makes the friendly schedule syntax cheap to test.
The command string is **data** - it is split with ``shlex`` and handed to
launchd as ProgramArguments, so no shell ever sees it.
"""

import os
import re
import shlex
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

# A Label must start alphanumeric and may then contain dots and hyphens; this
# is stricter than launchd, on purpose - it is also the plist's file name.
LABEL_PATTERN = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9.-]*\Z")

# Apple's own namespace: refused so a typo cannot shadow a system agent.
RESERVED_PREFIX = "com.apple."

DEFAULT_LOG_ROOT = "~/Library/Logs"
STDOUT_NAME = "out.log"
STDERR_NAME = "err.log"

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_INTERVAL = re.compile(r"^(\d+)\s*([smhd])?$")
_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})$")

_WEEKDAY_NAMES = (
    "sunday",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
)
# Both "mon" and "monday" are accepted; launchd counts Sunday as 0.
WEEKDAYS = {
    key: index
    for index, name in enumerate(_WEEKDAY_NAMES)
    for key in (name, name[:3])
}


@dataclass
class JobSpec:
    """Everything ``ldm install`` was asked to put into a new plist."""

    label: str
    command: str
    interval: Optional[str] = None
    calendar: Optional[str] = None
    log_dir: Optional[str] = None
    run_at_load: bool = False
    keep_alive: bool = False


def validate_label(label: str) -> str:
    """Return the label unchanged, or explain why it cannot be used."""
    if not label or not LABEL_PATTERN.match(label):
        raise ValueError(
            "invalid label {0!r}: it must start with a letter or digit and "
            "contain only letters, digits, dots and hyphens".format(label)
        )
    if label.startswith(RESERVED_PREFIX):
        raise ValueError(
            "refusing to use {0!r}: the {1}* namespace belongs to "
            "macOS".format(label, RESERVED_PREFIX)
        )
    return label


def parse_interval(text: str) -> int:
    """Parse ``45s`` / ``30m`` / ``2h`` / ``1d`` (or bare seconds) into seconds."""
    match = _INTERVAL.match((text or "").strip())
    if not match:
        raise ValueError(
            "invalid --interval {0!r}: use a number with an optional unit, "
            "e.g. 45s, 30m, 2h, 1d".format(text)
        )
    seconds = int(match.group(1)) * _UNITS[match.group(2) or "s"]
    if seconds <= 0:
        raise ValueError("invalid --interval {0!r}: it must be positive".format(text))
    return seconds


def _clock(text: str) -> Tuple[int, int]:
    """Parse ``HH:MM`` into (hour, minute), rejecting impossible times."""
    match = _CLOCK.match(text)
    if not match:
        raise ValueError("expected a HH:MM time, got {0!r}".format(text))
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValueError("{0!r} is not a real time of day".format(text))
    return hour, minute


def parse_calendar(text: str) -> Dict[str, int]:
    """Parse ``HH:MM`` / ``daily HH:MM`` / ``Mon HH:MM`` into launchd's dict."""
    parts = (text or "").split()
    try:
        if len(parts) == 1:
            hour, minute = _clock(parts[0])
            return {"Hour": hour, "Minute": minute}
        if len(parts) == 2:
            hour, minute = _clock(parts[1])
            day = parts[0].lower()
            if day == "daily":
                return {"Hour": hour, "Minute": minute}
            if day in WEEKDAYS:
                return {"Weekday": WEEKDAYS[day], "Hour": hour, "Minute": minute}
            raise ValueError("unknown day {0!r}".format(parts[0]))
        raise ValueError("expected one or two words")
    except ValueError as exc:
        raise ValueError(
            "invalid --calendar {0!r}: {1} - use \"09:30\", \"daily 09:30\" "
            "or \"Mon 09:30\"".format(text, exc)
        )


def log_paths(label: str, log_dir: Optional[str] = None) -> Tuple[str, str]:
    """Return the (stdout, stderr) log paths for a job."""
    root = log_dir or os.path.join(DEFAULT_LOG_ROOT, label)
    root = os.path.abspath(os.path.expanduser(root))
    return os.path.join(root, STDOUT_NAME), os.path.join(root, STDERR_NAME)


def _arguments(command: str) -> list:
    """Split the command string into ProgramArguments. It is never shell-run."""
    try:
        arguments = shlex.split(command or "")
    except ValueError as exc:
        raise ValueError("cannot parse --cmd {0!r}: {1}".format(command, exc))
    if not arguments:
        raise ValueError("--cmd is empty: there is no command to run")
    return arguments


def build(job: JobSpec) -> Dict[str, Any]:
    """Build the plist dictionary for a JobSpec, or raise ValueError."""
    validate_label(job.label)
    if job.interval and job.calendar:
        raise ValueError("--interval and --calendar cannot be used together")

    data: Dict[str, Any] = {
        "Label": job.label,
        "ProgramArguments": _arguments(job.command),
    }
    if job.interval:
        data["StartInterval"] = parse_interval(job.interval)
    elif job.calendar:
        data["StartCalendarInterval"] = parse_calendar(job.calendar)
    if job.run_at_load:
        data["RunAtLoad"] = True
    if job.keep_alive:
        data["KeepAlive"] = True

    stdout_path, stderr_path = log_paths(job.label, job.log_dir)
    data["StandardOutPath"] = stdout_path
    data["StandardErrorPath"] = stderr_path
    return data
