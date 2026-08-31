"""The only module that talks to ``launchctl``.

launchctl output differs between macOS releases, so every invocation and every
parser lives here. The command runner is injectable so tests never touch the
real launchd.
"""

import os
import subprocess
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# A runner takes an argv list and returns (returncode, stdout, stderr).
Runner = Callable[[Sequence[str]], Tuple[int, str, str]]

LAUNCHCTL = "/bin/launchctl"

# The handful of ``launchctl print`` fields worth surfacing in ``ldm info``.
PRINT_FIELDS = (
    "state",
    "last exit code",
    "last exit reason",
    "runs",
    "run interval",
    "path",
)


class LaunchctlError(RuntimeError):
    """Raised when launchctl cannot be executed at all."""


def subprocess_runner(argv: Sequence[str]) -> Tuple[int, str, str]:
    """Default runner: execute argv and capture its output."""
    try:
        proc = subprocess.run(
            list(argv),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise LaunchctlError("cannot execute {0}: {1}".format(argv[0], exc))
    return (
        proc.returncode,
        proc.stdout.decode("utf-8", "replace"),
        proc.stderr.decode("utf-8", "replace"),
    )


def _to_int(token: str) -> Optional[int]:
    """Parse a launchctl numeric column; ``-`` and junk become None."""
    token = token.strip()
    if not token or token == "-":
        return None
    try:
        return int(token)
    except ValueError:
        return None


def parse_list_output(text: str) -> Dict[str, Tuple[Optional[int], Optional[int]]]:
    """Parse ``launchctl list`` output into ``{label: (pid, last_exit)}``.

    The output is a header line followed by tab-separated ``PID Status Label``
    rows. A ``-`` in the PID column means the job is loaded but not running.
    Unparsable lines are skipped rather than raising.
    """
    jobs: Dict[str, Tuple[Optional[int], Optional[int]]] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t") if "\t" in line else line.split()
        if len(parts) < 3:
            continue
        pid_token, status_token, label = parts[0], parts[1], parts[2].strip()
        if not label or label == "Label":
            continue
        jobs[label] = (_to_int(pid_token), _to_int(status_token))
    return jobs


def launchctl_list(
    runner: Optional[Runner] = None,
) -> Dict[str, Tuple[Optional[int], Optional[int]]]:
    """Run ``launchctl list`` and return ``{label: (pid, last_exit)}``.

    A non-zero exit or an unavailable launchctl yields an empty mapping so the
    caller still gets the disk inventory instead of crashing.
    """
    run: Runner = runner or subprocess_runner
    try:
        code, out, _err = run([LAUNCHCTL, "list"])
    except LaunchctlError:
        return {}
    if code != 0:
        return {}
    return parse_list_output(out)


def build_argv(*args: str) -> List[str]:
    """Build a launchctl argv. Kept here so no other module names the binary."""
    return [LAUNCHCTL] + [str(a) for a in args]


def gui_target(label: str, uid: Optional[int] = None) -> str:
    """Build the ``gui/<uid>/<label>`` service target for the current user."""
    return "gui/{0}/{1}".format(os.getuid() if uid is None else uid, label)


def parse_print_output(text: str) -> Dict[str, str]:
    """Pull the ``PRINT_FIELDS`` out of ``launchctl print`` output.

    The output is a nested brace dump of ``key = value`` lines whose exact
    shape varies between macOS releases, so anything unrecognized is ignored
    and only the first occurrence of each known key is kept.
    """
    found: Dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if "=" not in stripped or stripped.endswith("{"):
            continue
        key, _, value = stripped.partition("=")
        key = key.strip().lower()
        if key in PRINT_FIELDS and key not in found:
            found[key] = value.strip()
    return found


def launchctl_print(
    label: str,
    runner: Optional[Runner] = None,
    uid: Optional[int] = None,
) -> Dict[str, str]:
    """Run ``launchctl print gui/<uid>/<label>`` and return a small summary.

    Read-only. An unloaded job, a missing launchctl or an unexpected output
    format all yield an empty mapping instead of raising.
    """
    run: Runner = runner or subprocess_runner
    try:
        code, out, _err = run(build_argv("print", gui_target(label, uid)))
    except LaunchctlError:
        return {}
    if code != 0:
        return {}
    try:
        return parse_print_output(out)
    except Exception:
        return {}
