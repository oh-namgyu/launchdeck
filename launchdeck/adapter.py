"""The only module that runs ``launchctl``.

launchctl output differs between macOS releases, so every invocation lives
here and every parser lives in ``parsing`` next door (re-exported below, so
callers only ever import ``adapter``). The command runner is injectable, which
is how tests cover all of this without touching the real launchd.
"""

import os
import subprocess
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .parsing import (  # noqa: F401  (re-exported as the boundary's API)
    ERROR_HINTS,
    PRINT_FIELDS,
    error_code,
    parse_disabled_output,
    parse_error,
    parse_list_output,
    parse_print_output,
    says_disabled,
)

# A runner takes an argv list and returns (returncode, stdout, stderr).
Runner = Callable[[Sequence[str]], Tuple[int, str, str]]

# The (returncode, stdout, stderr) triple every lifecycle call returns.
Completed = Tuple[int, str, str]

LAUNCHCTL = "/bin/launchctl"

TERM_SIGNAL = "SIGTERM"


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


def gui_domain(uid: Optional[int] = None) -> str:
    """Build the ``gui/<uid>`` domain target for the current user."""
    return "gui/{0}".format(os.getuid() if uid is None else uid)


def gui_target(label: str, uid: Optional[int] = None) -> str:
    """Build the ``gui/<uid>/<label>`` service target for the current user."""
    return "{0}/{1}".format(gui_domain(uid), label)


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


def invoke(args: Sequence[str], runner: Optional[Runner] = None) -> Completed:
    """Run one launchctl subcommand and return (code, stdout, stderr).

    Unlike the read-only helpers above this does not swallow failures: the
    lifecycle layer turns them into messages via ``parse_error``.
    """
    run: Runner = runner or subprocess_runner
    return run(build_argv(*args))


def is_disabled(
    label: str,
    runner: Optional[Runner] = None,
    uid: Optional[int] = None,
) -> bool:
    """Ask launchd whether ``label`` sits in the per-user disabled list.

    Read-only, and false whenever launchctl cannot answer: this only decides
    whether an extra hint is printed.
    """
    try:
        code, out, _err = invoke(["print-disabled", gui_domain(uid)], runner)
    except LaunchctlError:
        return False
    return label in parse_disabled_output(out) if code == 0 else False


def kickstart(
    label: str,
    runner: Optional[Runner] = None,
    uid: Optional[int] = None,
    restart: bool = False,
) -> Completed:
    """``launchctl kickstart [-k] gui/<uid>/<label>`` - run the job now."""
    flags = ["-k"] if restart else []
    return invoke(["kickstart"] + flags + [gui_target(label, uid)], runner)


def send_signal(
    label: str,
    signal: str = TERM_SIGNAL,
    runner: Optional[Runner] = None,
    uid: Optional[int] = None,
) -> Completed:
    """``launchctl kill <signal> gui/<uid>/<label>`` - signal the process."""
    return invoke(["kill", signal, gui_target(label, uid)], runner)


def bootstrap(
    plist_path: str,
    runner: Optional[Runner] = None,
    uid: Optional[int] = None,
) -> Completed:
    """``launchctl bootstrap gui/<uid> <plist>`` - load the job."""
    return invoke(["bootstrap", gui_domain(uid), plist_path], runner)


def bootout(
    label: str,
    runner: Optional[Runner] = None,
    uid: Optional[int] = None,
) -> Completed:
    """``launchctl bootout gui/<uid>/<label>`` - unload the job."""
    return invoke(["bootout", gui_target(label, uid)], runner)


def set_enabled(
    label: str,
    enabled: bool,
    runner: Optional[Runner] = None,
    uid: Optional[int] = None,
) -> Completed:
    """``launchctl enable|disable gui/<uid>/<label>`` - toggle loadability."""
    verb = "enable" if enabled else "disable"
    return invoke([verb, gui_target(label, uid)], runner)
