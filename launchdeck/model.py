"""Data model shared by the scanner, the launchctl adapter and the output layer."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Job lifecycle states used across the CLI.
STATE_RUNNING = "running"
STATE_IDLE = "idle"
STATE_FAILING = "failing"
STATE_UNLOADED = "unloaded"
STATE_GHOST = "ghost"
STATE_UNKNOWN = "unknown"

ALL_STATES = (
    STATE_RUNNING,
    STATE_IDLE,
    STATE_FAILING,
    STATE_UNLOADED,
    STATE_GHOST,
    STATE_UNKNOWN,
)


@dataclass
class JobRecord:
    """A single LaunchAgent job, merged from its plist and launchd runtime state."""

    label: str
    loaded: bool = False
    pid: Optional[int] = None
    last_exit: Optional[int] = None
    schedule: str = "on-demand"
    plist_path: Optional[str] = None
    stdout_path: Optional[str] = None
    stderr_path: Optional[str] = None
    state: str = STATE_UNKNOWN
    program: List[str] = field(default_factory=list)
    raw_schedule_keys: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return the stable JSON contract v1 shape for a single job."""
        return {
            "label": self.label,
            "loaded": self.loaded,
            "pid": self.pid,
            "last_exit": self.last_exit,
            "schedule": self.schedule,
            "plist_path": self.plist_path,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "state": self.state,
        }


def derive_state(
    in_launchctl: bool,
    pid: Optional[int],
    last_exit: Optional[int],
    parse_failed: bool = False,
) -> str:
    """Derive the job state from runtime facts.

    Rules (plan section 4):
      - a plist that could not be parsed degrades to "unknown"
      - pid present                       -> "running"
      - loaded, no pid, last_exit == 0    -> "idle"
      - loaded, no pid, last_exit != 0    -> "failing"
      - absent from `launchctl list`      -> "unloaded"
    """
    if parse_failed:
        return STATE_UNKNOWN
    if not in_launchctl:
        return STATE_UNLOADED
    if pid is not None:
        return STATE_RUNNING
    if last_exit is None:
        return STATE_UNKNOWN
    return STATE_IDLE if last_exit == 0 else STATE_FAILING
