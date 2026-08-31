"""Read-only health check behind ``ldm doctor``.

Each check answers one question about the LaunchAgents directory or about
launchd's current state and yields Findings: a severity, the job or file it is
about, a plain explanation and a suggestion. Nothing here writes anything -
doctor reports, it never repairs, and it never fails a build (see ``--strict``).
"""

import os
import shutil
import signal as signalmodule
from typing import List, Optional, Sequence, Tuple

from . import adapter, info, merge, output, scanner
from .findings import (  # noqa: F401  (re-exported: doctor is the public face)
    CHECK_CLUTTER,
    CHECK_EXIT,
    CHECK_FOREIGN,
    CHECK_LOG_SIZE,
    CHECK_PLIST,
    CHECK_PROGRAM,
    CHECK_TITLES,
    CHECK_UNLOADED,
    SEVERITY_INFO,
    SEVERITY_WARN,
    Finding,
    Report,
)
from .model import STATE_UNKNOWN, JobRecord

# Logs launchd never rotates for you; past this size they are worth a mention.
LOG_SIZE_LIMIT = 10 * 1024 * 1024

# Labels launchd or the login session own: they never have a plist of yours.
SYSTEM_PREFIXES = ("com.apple.", "application.")


def check_clutter(directory: Optional[str] = None) -> List[Finding]:
    """Non-plist files sitting in the LaunchAgents directory (``.bak`` and friends)."""
    return [
        Finding(
            CHECK_CLUTTER,
            SEVERITY_INFO,
            path,
            "not a .plist, so launchd ignores it",
            "delete it, or move it outside the LaunchAgents directory",
        )
        for path in scanner.non_plist_files(directory)
    ]


def _lint(path: str, runner: Optional[adapter.Runner]) -> Tuple[Optional[bool], str]:
    """Ask plutil about a file: ``(accepted, detail)``, or ``(None, "")`` if it cannot run."""
    try:
        code, out, err = adapter.plutil_lint(path, runner)
    except adapter.LaunchctlError:
        return None, ""
    return code == 0, (out or err).strip()


def _plist_finding(path: str, reason: str, accepted: Optional[bool], detail: str) -> Finding:
    """Turn a failed parse plus plutil's verdict into one finding."""
    if accepted:
        return Finding(
            CHECK_PLIST,
            SEVERITY_INFO,
            path,
            "valid for launchd but not strict XML ({0}), so ldm cannot read "
            "its details".format(reason),
            "rewrite it in canonical form: plutil -convert xml1 {0}".format(path),
        )
    if accepted is None:
        return Finding(
            CHECK_PLIST,
            SEVERITY_WARN,
            path,
            "cannot be parsed ({0}) and plutil is not available to confirm".format(reason),
            "check the file by hand, or restore it from a backup",
        )
    return Finding(
        CHECK_PLIST,
        SEVERITY_WARN,
        path,
        "corrupt plist: neither ldm nor plutil can read it ({0})".format(detail or reason),
        "repair it, or restore it from a backup, then run: plutil -lint {0}".format(path),
    )


def check_plists(
    records: Sequence[JobRecord], runner: Optional[adapter.Runner] = None
) -> List[Finding]:
    """Plists the scanner had to degrade to ``unknown``, cross-checked with plutil."""
    findings = []
    for record in records:
        if record.state != STATE_UNKNOWN or not record.plist_path:
            continue
        path = record.plist_path
        reason = scanner.load_plist(path)[1] or "unreadable"
        accepted, detail = _lint(path, runner)
        findings.append(_plist_finding(path, reason, accepted, detail))
    return findings


def _program_problem(command: str) -> Optional[Tuple[str, str]]:
    """Return ``(message, suggestion)`` when a command cannot be found, else None."""
    if os.sep in command:
        if os.path.exists(command):
            return None
        return (
            "program not found on disk: {0}".format(command),
            "fix ProgramArguments in the plist, or put the program back",
        )
    if shutil.which(command):
        return None
    return (
        "command {0!r} is not on your PATH".format(command),
        "use an absolute path: launchd runs jobs with a minimal PATH",
    )


def check_programs(records: Sequence[JobRecord]) -> List[Finding]:
    """Jobs whose executable does not exist: they will fail to launch."""
    findings = []
    for record in records:
        if not record.program:
            continue
        problem = _program_problem(record.program[0])
        if problem:
            message, suggestion = problem
            findings.append(
                Finding(
                    CHECK_PROGRAM,
                    SEVERITY_WARN,
                    record.label,
                    "{0}; the job will fail to launch".format(message),
                    suggestion,
                )
            )
    return findings


def _signal_name(number: int) -> str:
    """Name of a signal number, e.g. ``SIGTERM``, or a plain fallback."""
    try:
        return signalmodule.Signals(number).name
    except ValueError:
        return "signal {0}".format(number)


def _exit_detail(code: int, label: str) -> Tuple[str, str, str]:
    """Return ``(severity, message, suggestion)`` for one non-zero exit status."""
    read_logs = "read its output: ldm logs {0}".format(label)
    if code == -signalmodule.SIGTERM:
        return (
            SEVERITY_INFO,
            "terminated by SIGTERM (possibly a deliberate stop/restart)",
            "nothing to do if you stopped it yourself; otherwise " + read_logs,
        )
    if code < 0:
        return (
            SEVERITY_WARN,
            "terminated by {0} (exit {1})".format(_signal_name(-code), code),
            read_logs,
        )
    return (SEVERITY_WARN, "last run exited with code {0}".format(code), read_logs)


def check_exits(records: Sequence[JobRecord]) -> List[Finding]:
    """Jobs whose last run reported a non-zero status to launchd."""
    findings = []
    for record in records:
        if record.last_exit in (0, None):
            continue
        severity, message, suggestion = _exit_detail(record.last_exit, record.label)
        findings.append(
            Finding(CHECK_EXIT, severity, record.label, message, suggestion)
        )
    return findings


def check_unloaded(records: Sequence[JobRecord]) -> List[Finding]:
    """Plists on disk that launchd does not know about (which may be deliberate)."""
    return [
        Finding(
            CHECK_UNLOADED,
            SEVERITY_INFO,
            record.label,
            "the plist is on disk but launchd has not loaded it",
            "run: ldm load {0} (leave it if it is meant to stay off)".format(record.label),
        )
        for record in records
        if record.state != STATE_UNKNOWN and not record.loaded
    ]


def check_foreign(
    records: Sequence[JobRecord], runtime: merge.RuntimeMap
) -> List[Finding]:
    """Loaded labels with no plist of yours: other folders and other tools load these."""
    known = {record.label for record in records}
    return [
        Finding(
            CHECK_FOREIGN,
            SEVERITY_INFO,
            label,
            "loaded from outside your LaunchAgents folder (fine if you expected it)",
            "no action needed; ldm only manages the plists in your own folder",
        )
        for label in sorted(runtime)
        if label not in known and not label.startswith(SYSTEM_PREFIXES)
    ]


def check_logs(records: Sequence[JobRecord]) -> List[Finding]:
    """Declared log files that have grown past ``LOG_SIZE_LIMIT``."""
    findings = []
    for record in records:
        streams = (("stdout", record.stdout_path), ("stderr", record.stderr_path))
        for name, path in streams:
            details = info.log_file_info(path)
            size = details.get("size") or 0
            if not details.get("exists") or size <= LOG_SIZE_LIMIT:
                continue
            findings.append(
                Finding(
                    CHECK_LOG_SIZE,
                    SEVERITY_INFO,
                    record.label,
                    "{0} log is {1}: {2}".format(
                        name, output.format_size(size), output.shorten_path(path)
                    ),
                    "launchd never rotates logs; truncate or archive it yourself",
                )
            )
    return findings


def run(
    directory: Optional[str] = None, runner: Optional[adapter.Runner] = None
) -> Report:
    """Run every check against one LaunchAgents directory. Read-only throughout."""
    records = scanner.scan(directory)
    runtime = adapter.launchctl_list(runner)
    merge.merge(records, runtime)

    findings: List[Finding] = []
    findings += check_clutter(directory)
    findings += check_plists(records, runner)
    findings += check_programs(records)
    findings += check_exits(records)
    findings += check_unloaded(records)
    findings += check_foreign(records, runtime)
    findings += check_logs(records)
    return Report(findings)
