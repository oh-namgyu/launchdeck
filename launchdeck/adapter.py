"""The only module that talks to ``launchctl``.

launchctl output differs between macOS releases, so every invocation and every
parser lives here. The command runner is injectable so tests never touch the
real launchd.
"""

import subprocess
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# A runner takes an argv list and returns (returncode, stdout, stderr).
Runner = Callable[[Sequence[str]], Tuple[int, str, str]]

LAUNCHCTL = "/bin/launchctl"


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
