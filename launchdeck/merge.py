"""Merge disk plists (the job list) with launchd runtime state (pid / exit)."""

from typing import Dict, List, Optional, Tuple

from . import adapter, scanner
from .model import STATE_UNKNOWN, JobRecord, derive_state

RuntimeMap = Dict[str, Tuple[Optional[int], Optional[int]]]


def merge(records: List[JobRecord], runtime: RuntimeMap) -> List[JobRecord]:
    """Overlay ``launchctl list`` state onto scanned plist records.

    Disk plists are the source of truth for which jobs exist. Labels present in
    launchctl but absent from disk ("ghosts") are intentionally not added here:
    detecting them is the job of ``doctor``, not ``status``.
    """
    for record in records:
        if record.state == STATE_UNKNOWN:
            # A plist we could not parse: we have no trustworthy label to match.
            continue
        entry = runtime.get(record.label)
        record.loaded = entry is not None
        record.pid = entry[0] if entry else None
        record.last_exit = entry[1] if entry else None
        record.state = derive_state(entry is not None, record.pid, record.last_exit)
    return records


def collect(
    directory: Optional[str] = None,
    runner: Optional[adapter.Runner] = None,
) -> List[JobRecord]:
    """Scan the LaunchAgents directory and merge in current runtime state."""
    return merge(scanner.scan(directory), adapter.launchctl_list(runner))
