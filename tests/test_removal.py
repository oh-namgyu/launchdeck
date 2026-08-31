"""Uninstall transaction tests: backup first, then bootout, then delete."""

import os

import pytest

from launchdeck import adapter, backups, removal, transaction
from launchdeck.model import JobRecord

from .conftest import FakeLaunchd, write_plist
from .test_provision import LABEL, UID, area  # noqa: F401  (the area fixture)


def record(area, launchd, label=LABEL, command="/bin/true"):
    """Install a plist by hand and return its merged JobRecord."""
    path = write_plist(
        area.agents,
        "{0}.plist".format(label),
        {"Label": label, "ProgramArguments": [command]},
    )
    return transaction.installed(label, path, area.agents, launchd)


def uninstall(area, launchd, job):
    return removal.uninstall(job, launchd, UID, area.store)


def test_backs_up_unloads_and_removes(area):
    launchd = FakeLaunchd(loaded=[LABEL])
    job = record(area, launchd)
    original = open(job.plist_path, "rb").read()

    result = uninstall(area, launchd, job)

    assert result.ok
    assert not os.path.exists(job.plist_path)
    assert LABEL not in launchd.loaded
    assert open(result.details["backup_path"], "rb").read() == original
    assert "backup:" in "\n".join(result.lines)


def test_backup_lands_in_the_configured_store(area):
    launchd = FakeLaunchd(loaded=[LABEL])
    result = uninstall(area, launchd, record(area, launchd))
    assert result.details["backup_path"].startswith(area.store + os.sep)


def test_an_unloaded_job_is_removed_without_a_bootout(area):
    launchd = FakeLaunchd()
    job = record(area, launchd)
    result = uninstall(area, launchd, job)

    assert result.ok
    assert not os.path.exists(job.plist_path)
    assert [c for c in launchd.calls if c[1:2] == ["bootout"]] == []


def test_the_backup_exists_before_the_bootout(area):
    launchd = FakeLaunchd(loaded=[LABEL])
    job = record(area, launchd)
    seen = {}
    booted_out = launchd._bootout

    def watch(label):
        seen["backups"] = backups.find(LABEL, area.store)
        return booted_out(label)

    launchd._bootout = watch
    assert uninstall(area, launchd, job).ok
    # The copy was already on disk when launchd was asked to let go.
    assert len(seen["backups"]) == 1


def test_a_bootout_failure_changes_nothing(area):
    launchd = FakeLaunchd(loaded=[LABEL], bootout_code=5)
    job = record(area, launchd)
    result = uninstall(area, launchd, job)

    assert not result.ok
    assert os.path.exists(job.plist_path)
    assert LABEL in launchd.loaded
    text = "\n".join(result.lines)
    assert "Boot-out failed" in text and "nothing was removed" in text
    assert result.details["backup_path"]


def test_a_job_still_listed_after_bootout_is_a_failure(area, monkeypatch):
    launchd = FakeLaunchd(loaded=[LABEL])
    job = record(area, launchd)
    # launchd claims success but keeps listing the job.
    monkeypatch.setattr(launchd, "_bootout", lambda label: (0, "", ""))
    result = uninstall(area, launchd, job)

    assert not result.ok
    assert "still lists" in result.lines[0]
    assert os.path.exists(job.plist_path)


def test_a_failed_delete_restores_the_load_state(area, monkeypatch):
    launchd = FakeLaunchd(loaded=[LABEL])
    job = record(area, launchd)

    def refuse(path):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(removal.os, "remove", refuse)
    result = uninstall(area, launchd, job)

    assert not result.ok
    assert os.path.exists(job.plist_path)
    assert LABEL in launchd.loaded  # booted out, then bootstrapped again
    assert "rolled back: loaded" in "\n".join(result.lines)


def test_a_failed_delete_puts_the_file_back_from_the_backup(area, monkeypatch):
    launchd = FakeLaunchd(loaded=[LABEL])
    job = record(area, launchd)
    path = job.plist_path

    def remove_then_fail(target):
        os.unlink(target)
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(removal.os, "remove", remove_then_fail)
    result = uninstall(area, launchd, job)

    assert not result.ok
    assert os.path.exists(path)
    assert "restored {0}".format(path) in "\n".join(result.lines)


def test_a_disabled_label_is_documented_in_the_output(area):
    launchd = FakeLaunchd(loaded=[LABEL], disabled=[LABEL])
    result = uninstall(area, launchd, record(area, launchd))

    assert result.ok
    text = "\n".join(result.lines)
    assert "override database - uninstall cannot delete it" in text
    assert "ldm enable {0}".format(LABEL) in text


def test_an_enabled_label_gets_no_disabled_note(area):
    launchd = FakeLaunchd(loaded=[LABEL])
    result = uninstall(area, launchd, record(area, launchd))
    assert "override database" not in "\n".join(result.lines)


def test_a_missing_plist_is_an_error(area):
    result = uninstall(area, FakeLaunchd(), JobRecord(label=LABEL))
    assert not result.ok
    assert "no plist file found" in result.lines[0]


def test_a_backup_failure_stops_before_anything_changes(area, monkeypatch):
    launchd = FakeLaunchd(loaded=[LABEL])
    job = record(area, launchd)
    monkeypatch.setattr(
        removal.backups, "save", lambda *a, **k: (_ for _ in ()).throw(OSError("full"))
    )
    result = uninstall(area, launchd, job)

    assert not result.ok
    assert "nothing was changed" in result.lines[0]
    assert os.path.exists(job.plist_path)
    assert LABEL in launchd.loaded


def test_uninstall_only_ever_talks_to_launchctl_through_the_adapter(area):
    launchd = FakeLaunchd(loaded=[LABEL])
    uninstall(area, launchd, record(area, launchd))
    assert all(call[0] == adapter.LAUNCHCTL for call in launchd.calls)
