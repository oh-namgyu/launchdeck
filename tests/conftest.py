"""Shared fixtures. No test in this suite touches launchctl or the real home."""

import os
import plistlib
from typing import Any, Dict, List, Sequence, Tuple

import pytest

SAMPLE_LIST_OUTPUT = "\n".join(
    [
        "PID\tStatus\tLabel",
        "4242\t0\tcom.example.running",
        "-\t0\tcom.example.idle",
        "-\t28\tcom.example.failing",
        "-\t0\tcom.example.ghost",
    ]
)


# Shape of `launchctl print gui/<uid>/<label>` on macOS 15 (Darwin 24).
SAMPLE_PRINT_OUTPUT = """gui/501/com.example.running = {
\tactive count = 0
\tpath = /Users/someone/Library/LaunchAgents/com.example.running.plist
\ttype = LaunchAgent
\tstate = not running

\tprogram = /bin/sh
\targuments = {
\t\t/bin/sh
\t\t/tmp/run.sh
\t}

\truns = 5
\tlast exit code = 0
\trun interval = 7200 seconds
}
"""


def write_plist(directory: Any, filename: str, data: Dict[str, Any]) -> str:
    """Write an XML plist into ``directory`` and return its path."""
    path = os.path.join(str(directory), filename)
    with open(str(path), "wb") as handle:
        plistlib.dump(data, handle, fmt=plistlib.FMT_XML)
    return str(path)


def write_binary_plist(directory: Any, filename: str, data: Dict[str, Any]) -> str:
    """Write a binary plist into ``directory`` and return its path."""
    path = os.path.join(str(directory), filename)
    with open(str(path), "wb") as handle:
        plistlib.dump(data, handle, fmt=plistlib.FMT_BINARY)
    return str(path)


def listing_text(loaded: Dict[str, Tuple[Any, int]]) -> str:
    """Render a ``launchctl list`` table from ``{label: (pid, last_exit)}``."""
    rows = ["PID\tStatus\tLabel"]
    rows += [
        "{0}\t{1}\t{2}".format(pid if pid else "-", code, label)
        for label, (pid, code) in sorted(loaded.items())
    ]
    return "\n".join(rows) + "\n"


def fake_runner(stdout: str, code: int = 0):
    """Build a launchctl runner that returns canned output."""

    def run(argv: Sequence[str]) -> Tuple[int, str, str]:
        return code, stdout, ""

    return run


def spy_runner(code: int = 0, stdout: str = "", stderr: str = ""):
    """Runner that records each argv it receives and returns a canned result.

    The recorded calls hang off ``run.calls`` so a test can assert the exact
    launchctl command line without any process ever being spawned.
    """
    calls: List[List[str]] = []

    def run(argv: Sequence[str]) -> Tuple[int, str, str]:
        calls.append(list(argv))
        return code, stdout, stderr

    run.calls = calls
    return run


def fake_launchctl(print_output: str = SAMPLE_PRINT_OUTPUT, print_code: int = 0):
    """Build a runner answering both ``launchctl list`` and ``launchctl print``."""

    def run(argv: Sequence[str]) -> Tuple[int, str, str]:
        if len(argv) > 1 and argv[1] == "print":
            return print_code, print_output, ""
        return 0, SAMPLE_LIST_OUTPUT, ""

    return run


def label_of(path: str) -> str:
    """The Label inside a plist file, falling back to its file name."""
    fallback = os.path.basename(path)
    fallback = fallback[: -len(".plist")] if fallback.endswith(".plist") else fallback
    try:
        with open(path, "rb") as handle:
            data = plistlib.load(handle)
        return data.get("Label") or fallback
    except Exception:
        return fallback


class FakeLaunchd:
    """A stand-in for launchctl and plutil that remembers what is loaded.

    ``bootstrap``/``bootout``/``list`` stay consistent with each other, which
    is what the transaction tests need: a rollback can be asserted on the
    load state, not just on the files.
    """

    def __init__(self, loaded=(), disabled=(), lint_code=0, bootstrap_code=0, bootout_code=0):
        self.loaded: Dict[str, Tuple[Any, int]] = {label: (None, 0) for label in loaded}
        self.disabled = set(disabled)
        self.lint_code = lint_code
        self.bootstrap_code = bootstrap_code
        self.bootout_code = bootout_code
        self.calls: List[List[str]] = []

    def __call__(self, argv: Sequence[str]) -> Tuple[int, str, str]:
        self.calls.append(list(argv))
        if argv[0].endswith("plutil"):
            # plutil reports lint failures on stdout, like the real one.
            said = "" if not self.lint_code else "{0}: garbage".format(argv[-1])
            return self.lint_code, said, ""
        verb = argv[1]
        if verb == "list":
            return 0, self.listing(), ""
        if verb == "print-disabled":
            rows = "".join('\t\t"{0}" => disabled\n'.format(l) for l in self.disabled)
            return 0, "disabled services = {\n" + rows + "}\n", ""
        if verb == "bootstrap":
            return self._bootstrap(argv[3])
        if verb == "bootout":
            return self._bootout(argv[2].rsplit("/", 1)[-1])
        return 0, "", ""

    def listing(self) -> str:
        return listing_text(self.loaded)

    def _bootstrap(self, path: str) -> Tuple[int, str, str]:
        if not os.path.isfile(path):
            return 113, "", "Bootstrap failed: 113: Could not find specified service"
        if self.bootstrap_code:
            return self.bootstrap_code, "", "Bootstrap failed: 5: Input/output error"
        self.loaded[label_of(path)] = (None, 0)
        return 0, "", ""

    def _bootout(self, label: str) -> Tuple[int, str, str]:
        if self.bootout_code:
            return self.bootout_code, "", "Boot-out failed: 5: Input/output error"
        self.loaded.pop(label, None)
        return 0, "", ""


@pytest.fixture
def agents(tmp_path):
    """A temporary LaunchAgents directory holding four representative jobs."""
    write_plist(
        tmp_path,
        "com.example.running.plist",
        {
            "Label": "com.example.running",
            "ProgramArguments": ["/bin/sh", "/tmp/run.sh"],
            "KeepAlive": True,
            "StandardOutPath": "/tmp/run.out",
            "StandardErrorPath": "/tmp/run.err",
        },
    )
    write_plist(
        tmp_path,
        "com.example.idle.plist",
        {
            "Label": "com.example.idle",
            "ProgramArguments": ["/bin/sh", "/tmp/idle.sh"],
            "StartInterval": 7200,
        },
    )
    write_plist(
        tmp_path,
        "com.example.failing.plist",
        {
            "Label": "com.example.failing",
            "Program": "/tmp/fail.sh",
            "StartCalendarInterval": {"Hour": 9, "Minute": 40},
        },
    )
    write_plist(
        tmp_path,
        "com.example.unloaded.plist",
        {"Label": "com.example.unloaded", "ProgramArguments": ["/bin/true"]},
    )
    # Leftovers the scanner must ignore.
    (tmp_path / "com.example.idle.plist.bak").write_text("stale backup")
    (tmp_path / "notes.txt").write_text("not a plist")
    return tmp_path
