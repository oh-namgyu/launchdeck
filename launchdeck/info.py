"""Assemble the detail view of a single job for ``ldm info``.

Nothing here touches launchctl directly: the runtime excerpt is fetched through
``adapter``. Log files are only ``stat``-ed, never opened.
"""

import difflib
import os
from typing import Any, Dict, List, Optional, Sequence

from . import adapter
from .model import JobRecord

MAX_SUGGESTIONS = 5
_CUTOFF = 0.6


def suggest(label: str, known: Sequence[str]) -> List[str]:
    """Return the labels closest to ``label``, best match first.

    Fuzzy matching first, then a substring pass so that a short but exact
    fragment (``viral-scout``) still finds its jobs.
    """
    matches = difflib.get_close_matches(
        label, list(known), n=MAX_SUGGESTIONS, cutoff=_CUTOFF
    )
    if len(matches) < MAX_SUGGESTIONS:
        needle = label.lower()
        for candidate in known:
            if needle and needle in candidate.lower() and candidate not in matches:
                matches.append(candidate)
                if len(matches) == MAX_SUGGESTIONS:
                    break
    return matches


def unknown_label_message(label: str, known: Sequence[str]) -> str:
    """Build the error text shown when no job carries ``label``."""
    matches = suggest(label, known)
    if not matches:
        return "unknown label {0!r} (no similar LaunchAgent found)".format(label)
    return "unknown label {0!r}; did you mean: {1}".format(label, ", ".join(matches))


def find_job(records: Sequence[JobRecord], label: str) -> JobRecord:
    """Look up one record by exact label, or raise with close matches listed."""
    for record in records:
        if record.label == label:
            return record
    raise LookupError(unknown_label_message(label, [r.label for r in records]))


def log_file_info(path: Optional[str]) -> Dict[str, Any]:
    """Describe a log path: does it exist, and how big is it (read-only stat)."""
    info: Dict[str, Any] = {"path": path, "exists": False, "size": None}
    if not path:
        return info
    try:
        stat = os.stat(os.path.expanduser(path))
    except OSError:
        return info
    info["exists"] = True
    info["size"] = stat.st_size
    return info


def describe(
    record: JobRecord,
    runner: Optional[adapter.Runner] = None,
    uid: Optional[int] = None,
) -> Dict[str, Any]:
    """Extend the JSON contract job dict with the detail-only fields."""
    detail = record.to_dict()
    detail["program_arguments"] = list(record.program)
    detail["raw_schedule_keys"] = list(record.raw_schedule_keys)
    detail["log_files"] = {
        "stdout": log_file_info(record.stdout_path),
        "stderr": log_file_info(record.stderr_path),
    }
    detail["launchctl_print"] = adapter.launchctl_print(record.label, runner, uid)
    return detail
