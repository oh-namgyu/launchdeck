"""Backup store tests: where copies go, and which one ``restore`` picks."""

import os

from launchdeck import backups


def _plist(tmp_path, name="com.example.job.plist", body=b"first"):
    path = tmp_path / name
    path.write_bytes(body)
    return str(path)


def test_root_prefers_the_environment_override(monkeypatch, tmp_path):
    monkeypatch.setenv(backups.ENV_VAR, str(tmp_path / "store"))
    assert backups.root() == str(tmp_path / "store")
    assert backups.root(str(tmp_path / "other")) == str(tmp_path / "other")


def test_root_falls_back_to_the_default(monkeypatch):
    monkeypatch.delenv(backups.ENV_VAR, raising=False)
    assert backups.root().endswith("/.local/share/ldm/backups")


def test_save_copies_the_bytes_into_a_timestamped_slot(tmp_path):
    source = _plist(tmp_path, body=b"<plist/>")
    store = str(tmp_path / "store")
    backup = backups.save("com.example.job", source, store)

    assert backup.startswith(store + os.sep)
    assert os.path.basename(backup) == "com.example.job.plist"
    assert open(backup, "rb").read() == b"<plist/>"
    slot = os.path.basename(os.path.dirname(backup))
    assert slot.endswith("Z") and len(slot) == 16


def test_two_saves_in_the_same_second_do_not_collide(tmp_path):
    source = _plist(tmp_path)
    store = str(tmp_path / "store")
    first = backups.save("com.example.job", source, store)
    second = backups.save("com.example.job", source, store)
    assert first != second
    assert len(backups.find("com.example.job", store)) == 2


def test_newest_returns_the_latest_slot(tmp_path):
    store = tmp_path / "store"
    for index, stamp in enumerate(("20260101T000000Z", "20260830T235959Z")):
        slot = store / stamp
        slot.mkdir(parents=True)
        (slot / "com.example.job.plist").write_bytes(str(index).encode())

    newest = backups.newest("com.example.job", str(store))
    assert newest == str(store / "20260830T235959Z" / "com.example.job.plist")
    assert open(newest, "rb").read() == b"1"


def test_newest_ignores_other_labels(tmp_path):
    store = tmp_path / "store"
    slot = store / "20260101T000000Z"
    slot.mkdir(parents=True)
    (slot / "com.other.job.plist").write_bytes(b"x")
    assert backups.newest("com.example.job", str(store)) is None


def test_newest_of_an_empty_store_is_none(tmp_path):
    assert backups.newest("com.example.job", str(tmp_path / "missing")) is None
    assert backups.find("com.example.job", str(tmp_path / "missing")) == []
