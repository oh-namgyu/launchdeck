"""Fixtures for the doctor tests: a directory carrying one of every problem.

Kept out of ``conftest`` because only the two doctor modules need it; they
import the fixtures they use by name.
"""

import os

import pytest

from launchdeck import adapter, merge, scanner

from .conftest import listing_text, write_plist

# A plist Apple's parser accepts but Python's expat rejects: the XML comment
# holds a double hyphen. Hand-written plists hit this in the wild.
LENIENT_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
<dict>
    <!-- renders the --vocal track -->
    <key>Label</key>
    <string>com.example.lenient</string>
    <key>ProgramArguments</key>
    <array><string>/bin/sh</string></array>
</dict>
</plist>
"""

# What launchd has loaded while the clinic directory is being examined.
CLINIC_LOADED = {
    "com.example.ok": (100, 0),
    "com.example.gone": (None, 0),
    "com.example.nocmd": (None, 0),
    "com.example.failing": (None, 28),
    "com.example.stopped": (None, -15),
    "com.example.killed": (None, -9),
    "com.example.lenient": (None, 0),
    "com.example.noisy": (None, 0),
    "com.apple.somethingd": (None, 0),
    "application.com.example.app.1.2": (None, 0),
    "com.other.tool": (None, 0),
}

# Findings the clinic directory is expected to produce, by severity.
CLINIC_WARNINGS = 5
CLINIC_NOTICES = 7


def clinic_runner(loaded=None, plutil_ok=("lenient",), plutil_missing=False):
    """A runner answering ``launchctl list`` and a per-path ``plutil -lint``."""

    def run(argv):
        if argv[0].endswith("plutil"):
            if plutil_missing:
                raise adapter.LaunchctlError("cannot execute plutil")
            path = argv[-1]
            # Match on the file name only: the temporary directory is named
            # after the running test, and would otherwise match too.
            if any(marker in os.path.basename(path) for marker in plutil_ok):
                return 0, "{0}: OK\n".format(path), ""
            return 1, "{0}: Unexpected character x at line 1\n".format(path), ""
        if argv[1] == "list":
            return 0, listing_text(CLINIC_LOADED if loaded is None else loaded), ""
        return 0, "", ""

    return run


def _write_program_jobs(directory, tmp_path) -> None:
    """One healthy job plus the two whose program cannot be found."""
    write_plist(
        directory,
        "com.example.ok.plist",
        {"Label": "com.example.ok", "ProgramArguments": ["/bin/sh", "-c", "true"]},
    )
    write_plist(
        directory,
        "com.example.gone.plist",
        {
            "Label": "com.example.gone",
            "ProgramArguments": [str(tmp_path / "deleted-program.sh")],
        },
    )
    write_plist(
        directory,
        "com.example.nocmd.plist",
        {"Label": "com.example.nocmd", "ProgramArguments": ["ldm-no-such-command"]},
    )


def _write_exit_jobs(directory) -> None:
    """Four identical jobs; only their runtime status differs."""
    for name in ("failing", "stopped", "killed", "sleeping"):
        write_plist(
            directory,
            "com.example.{0}.plist".format(name),
            {"Label": "com.example.{0}".format(name), "Program": "/bin/sh"},
        )


def _write_noisy_job(directory, tmp_path) -> None:
    """A job with one oversized log file and one small one."""
    big = tmp_path / "noisy.out"
    with open(str(big), "wb") as handle:
        handle.truncate(11 * 1024 * 1024)
    small = tmp_path / "noisy.err"
    small.write_text("quiet\n")
    write_plist(
        directory,
        "com.example.noisy.plist",
        {
            "Label": "com.example.noisy",
            "Program": "/bin/sh",
            "StandardOutPath": str(big),
            "StandardErrorPath": str(small),
        },
    )


@pytest.fixture
def clinic(tmp_path):
    """A LaunchAgents directory carrying one instance of every problem."""
    directory = tmp_path / "agents"
    directory.mkdir()
    _write_program_jobs(directory, tmp_path)
    _write_exit_jobs(directory)
    _write_noisy_job(directory, tmp_path)
    (directory / "com.example.lenient.plist").write_text(LENIENT_PLIST)
    (directory / "com.example.corrupt.plist").write_text("not a plist at all")
    (directory / "com.example.ok.plist.bak").write_text("stale backup")
    (directory / "notes.txt").write_text("scratch")
    return directory


@pytest.fixture
def clean(tmp_path):
    """A LaunchAgents directory with nothing wrong with it."""
    directory = tmp_path / "clean"
    directory.mkdir()
    write_plist(
        directory,
        "com.example.ok.plist",
        {"Label": "com.example.ok", "ProgramArguments": ["/bin/sh", "-c", "true"]},
    )
    return directory


@pytest.fixture
def doctor_cli(monkeypatch):
    """Point the whole CLI at the fake runner, so nothing is ever spawned."""
    monkeypatch.setattr(adapter, "subprocess_runner", clinic_runner())


@pytest.fixture
def empty_cli(monkeypatch):
    """The same, for a directory examined while launchd has nothing loaded."""
    monkeypatch.setattr(adapter, "subprocess_runner", clinic_runner(loaded={}))


@pytest.fixture
def clean_cli(monkeypatch):
    """The same, for the ``clean`` directory: its one job is loaded and idle."""
    runner = clinic_runner(loaded={"com.example.ok": (None, 0)})
    monkeypatch.setattr(adapter, "subprocess_runner", runner)


def records_of(directory, loaded=None):
    """Scan and merge a directory the way ``doctor.run`` does."""
    runtime = adapter.launchctl_list(clinic_runner(loaded))
    return merge.merge(scanner.scan(str(directory)), runtime), runtime


def subjects(findings):
    """The subject of every finding, as a set."""
    return {f.subject for f in findings}
