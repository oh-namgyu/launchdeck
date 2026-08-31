"""Shared fixtures. No test in this suite touches launchctl or the real home."""

import plistlib
from typing import Any, Dict, Sequence, Tuple

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


def write_plist(directory: Any, filename: str, data: Dict[str, Any]) -> str:
    """Write an XML plist into ``directory`` and return its path."""
    path = directory / filename
    with open(str(path), "wb") as handle:
        plistlib.dump(data, handle, fmt=plistlib.FMT_XML)
    return str(path)


def write_binary_plist(directory: Any, filename: str, data: Dict[str, Any]) -> str:
    """Write a binary plist into ``directory`` and return its path."""
    path = directory / filename
    with open(str(path), "wb") as handle:
        plistlib.dump(data, handle, fmt=plistlib.FMT_BINARY)
    return str(path)


def fake_runner(stdout: str, code: int = 0):
    """Build a launchctl runner that returns canned output."""

    def run(argv: Sequence[str]) -> Tuple[int, str, str]:
        return code, stdout, ""

    return run


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
