"""CLI tests for the writing commands: install, uninstall, restore."""

import json
import os
import types

import pytest

from launchdeck import adapter, cli

from .conftest import FakeLaunchd

INSTALL_LABEL = "com.ldm.test.cli"


@pytest.fixture
def installable(tmp_path, monkeypatch):
    """An empty LaunchAgents dir, a backup store via LDM_BACKUP_DIR, a fake launchd."""
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    monkeypatch.setenv("LDM_BACKUP_DIR", str(tmp_path / "backups"))
    launchd = FakeLaunchd()
    monkeypatch.setattr(adapter, "subprocess_runner", launchd)
    return types.SimpleNamespace(
        dir=str(agents),
        logs=str(tmp_path / "logs"),
        store=str(tmp_path / "backups"),
        plist=str(agents / "{0}.plist".format(INSTALL_LABEL)),
        launchd=launchd,
    )


def _install(area, *extra):
    """Run ``ldm install`` for the test label inside the temporary area."""
    return cli.main(
        [
            "install",
            "--label",
            INSTALL_LABEL,
            "--cmd",
            "/bin/echo hello",
            "--interval",
            "30m",
            "--log-dir",
            area.logs,
            "--dir",
            area.dir,
        ]
        + list(extra)
    )


def test_install_writes_the_plist_and_loads_it(installable, capsys):
    assert _install(installable) == 0
    out = capsys.readouterr().out
    assert "installed {0}".format(INSTALL_LABEL) in out
    assert os.path.isfile(installable.plist)
    assert INSTALL_LABEL in installable.launchd.loaded


def test_install_json_carries_the_paths(installable, capsys):
    assert _install(installable, "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == 1
    assert payload["result"]["action"] == "install"
    assert payload["result"]["plist_path"] == installable.plist


def test_install_twice_is_refused(installable, capsys):
    assert _install(installable) == 0
    capsys.readouterr()
    assert _install(installable) == 1
    assert "--force" in capsys.readouterr().err


def test_install_with_a_bad_calendar_writes_nothing(installable, capsys):
    code = cli.main(
        [
            "install",
            "--label",
            INSTALL_LABEL,
            "--cmd",
            "/bin/echo hello",
            "--calendar",
            "25:99",
            "--dir",
            installable.dir,
            "--json",
        ]
    )
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["ok"] is False
    assert os.listdir(installable.dir) == []


def test_install_refuses_two_schedules(installable):
    with pytest.raises(SystemExit) as excinfo:
        _install(installable, "--calendar", "09:30")
    assert excinfo.value.code == 2


def test_uninstall_backs_up_and_removes(installable, capsys):
    assert _install(installable) == 0
    capsys.readouterr()

    assert cli.main(["uninstall", INSTALL_LABEL, "--json", "--dir", installable.dir]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert os.path.isfile(payload["result"]["backup_path"])
    assert payload["result"]["backup_path"].startswith(installable.store + os.sep)
    assert not os.path.exists(installable.plist)
    assert INSTALL_LABEL not in installable.launchd.loaded


def test_restore_brings_the_job_back(installable, capsys):
    assert _install(installable) == 0
    assert cli.main(["uninstall", INSTALL_LABEL, "--dir", installable.dir]) == 0
    capsys.readouterr()

    assert cli.main(["restore", INSTALL_LABEL, "--dir", installable.dir]) == 0
    out = capsys.readouterr().out
    assert "restored {0}".format(INSTALL_LABEL) in out
    assert os.path.isfile(installable.plist)
    assert INSTALL_LABEL in installable.launchd.loaded


def test_restore_without_a_backup_exits_one(installable, capsys):
    assert cli.main(["restore", INSTALL_LABEL, "--dir", installable.dir]) == 1
    assert "no backup" in capsys.readouterr().err


def test_restore_over_an_existing_plist_is_refused(installable, capsys):
    assert _install(installable) == 0
    assert cli.main(["uninstall", INSTALL_LABEL, "--dir", installable.dir]) == 0
    assert _install(installable) == 0
    capsys.readouterr()

    assert cli.main(["restore", INSTALL_LABEL, "--dir", installable.dir]) == 1
    assert "--force" in capsys.readouterr().err


def test_uninstall_of_an_unknown_label_exits_one(installable, capsys):
    assert cli.main(["uninstall", "com.ldm.test.nope", "--dir", installable.dir]) == 1
    assert "unknown label" in capsys.readouterr().err
