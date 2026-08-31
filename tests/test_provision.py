"""install / restore transaction tests. launchctl and plutil are both fakes."""

import os
import plistlib
import types

import pytest

from launchdeck import provision, spec

from .conftest import FakeLaunchd, write_plist

UID = 501
LABEL = "com.ldm.test.unit"
FILENAME = "{0}.plist".format(LABEL)


@pytest.fixture
def area(tmp_path):
    """A temporary LaunchAgents directory, backup store and log directory."""
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    return types.SimpleNamespace(
        agents=str(agents),
        store=str(tmp_path / "backups"),
        logs=str(tmp_path / "logs"),
        target=str(agents / FILENAME),
    )


def install(area, launchd, force=False, **fields):
    """Run ``provision.install`` against the temporary area."""
    fields.setdefault("label", LABEL)
    fields.setdefault("command", "/bin/echo hi")
    fields.setdefault("log_dir", area.logs)
    return provision.install(
        spec.JobSpec(**fields),
        runner=launchd,
        uid=UID,
        directory=area.agents,
        force=force,
        backup_root=area.store,
    )


def existing(area, label=LABEL, command="/bin/true"):
    """Put a plist for ``label`` in the area and return its path."""
    return write_plist(
        area.agents,
        "{0}.plist".format(label),
        {"Label": label, "ProgramArguments": [command]},
    )


def read(path):
    with open(path, "rb") as handle:
        return plistlib.load(handle)


class TestInstall:
    def test_writes_the_plist_and_loads_it(self, area):
        launchd = FakeLaunchd()
        result = install(area, launchd, interval="2h")

        assert result.ok
        assert read(area.target)["StartInterval"] == 7200
        assert read(area.target)["ProgramArguments"] == ["/bin/echo", "hi"]
        assert LABEL in launchd.loaded
        assert result.details["plist_path"] == area.target

    def test_the_temp_file_is_linted_then_replaced(self, area):
        launchd = FakeLaunchd()
        install(area, launchd)

        linted = [c for c in launchd.calls if c[0].endswith("plutil")]
        assert len(linted) == 1
        temp = linted[0][-1]
        assert os.path.dirname(temp) == area.agents
        assert os.path.basename(temp).startswith(".ldm-")
        # The temp file is gone; only the final plist is left.
        assert os.listdir(area.agents) == [FILENAME]

    def test_the_log_directory_is_created(self, area):
        install(area, FakeLaunchd())
        assert os.path.isdir(area.logs)
        assert read(area.target)["StandardOutPath"] == os.path.join(area.logs, "out.log")

    def test_calendar_and_flags_reach_the_file(self, area):
        install(area, FakeLaunchd(), calendar="Mon 09:30", run_at_load=True, keep_alive=True)
        data = read(area.target)
        assert data["StartCalendarInterval"] == {"Weekday": 1, "Hour": 9, "Minute": 30}
        assert data["RunAtLoad"] is True and data["KeepAlive"] is True

    def test_an_existing_label_is_refused_without_force(self, area):
        path = existing(area)
        launchd = FakeLaunchd(loaded=[LABEL])
        result = install(area, launchd)

        assert not result.ok
        assert "--force" in "\n".join(result.lines)
        # Untouched: same file, still loaded, no bootstrap or bootout attempted.
        assert read(path)["ProgramArguments"] == ["/bin/true"]
        assert LABEL in launchd.loaded
        assert [c for c in launchd.calls if c[1:2] in (["bootstrap"], ["bootout"])] == []

    def test_force_backs_up_and_replaces_the_old_job(self, area):
        existing(area)
        launchd = FakeLaunchd(loaded=[LABEL])
        result = install(area, launchd, force=True)

        assert result.ok
        assert read(area.target)["ProgramArguments"] == ["/bin/echo", "hi"]
        assert read(result.details["backup_path"])["ProgramArguments"] == ["/bin/true"]
        assert LABEL in launchd.loaded

    def test_a_lint_failure_leaves_nothing_behind(self, area):
        launchd = FakeLaunchd(lint_code=1)
        result = install(area, launchd)

        assert not result.ok
        assert "plutil -lint" in result.lines[0]
        assert os.listdir(area.agents) == []
        assert LABEL not in launchd.loaded

    def test_a_lint_failure_restores_what_force_replaced(self, area):
        path = existing(area)
        launchd = FakeLaunchd(loaded=[LABEL], lint_code=1)
        result = install(area, launchd, force=True)

        assert not result.ok
        assert read(path)["ProgramArguments"] == ["/bin/true"]
        assert LABEL in launchd.loaded
        assert "rolled back" in "\n".join(result.lines)

    def test_a_bootstrap_failure_removes_the_new_plist(self, area):
        launchd = FakeLaunchd(bootstrap_code=5)
        result = install(area, launchd)

        assert not result.ok
        assert "launchd refused to load" in result.lines[0]
        assert not os.path.exists(area.target)
        assert LABEL not in launchd.loaded

    def test_a_bootstrap_failure_restores_and_reloads_what_force_replaced(self, area):
        path = existing(area)
        launchd = FakeLaunchd(loaded=[LABEL], bootstrap_code=5)
        result = install(area, launchd, force=True)

        assert not result.ok
        assert read(path)["ProgramArguments"] == ["/bin/true"]
        text = "\n".join(result.lines)
        assert "rolled back: restored" in text
        # The bootstrap of the old plist failed too, so say so rather than lie.
        assert "could not load" in text

    def test_a_disabled_label_gets_an_enable_hint(self, area):
        launchd = FakeLaunchd(bootstrap_code=5, disabled=[LABEL])
        result = install(area, launchd)
        assert "ldm enable {0}".format(LABEL) in "\n".join(result.lines)

    def test_an_invalid_label_writes_nothing(self, area):
        launchd = FakeLaunchd()
        result = install(area, launchd, label="com.apple.evil")

        assert not result.ok
        assert "belongs to macOS" in result.lines[0]
        assert os.listdir(area.agents) == []
        assert launchd.calls == []

    def test_an_invalid_calendar_is_rejected_before_any_file(self, area):
        launchd = FakeLaunchd()
        result = install(area, launchd, calendar="25:99")

        assert not result.ok
        assert "--calendar" in result.lines[0]
        assert os.listdir(area.agents) == []
        assert launchd.calls == []

    def test_a_symlinked_target_outside_the_directory_is_refused(self, area, tmp_path):
        outside = tmp_path / "outside.plist"
        outside.write_text("")
        os.symlink(str(outside), area.target)
        result = install(area, FakeLaunchd())

        assert not result.ok
        assert "does not resolve inside" in result.lines[0]
        assert outside.read_text() == ""

    def test_json_details_carry_the_paths(self, area):
        payload = install(area, FakeLaunchd(), force=True).to_dict()
        assert payload["action"] == "install"
        assert payload["plist_path"] == area.target
        assert payload["ok"] is True


def _backup(area, label=LABEL, command="/bin/true"):
    """Uninstall a freshly installed job so a backup exists to restore."""
    from launchdeck import removal, transaction

    path = existing(area, label, command)
    record = transaction.installed(label, path, area.agents, FakeLaunchd())
    return removal.uninstall(record, FakeLaunchd(), UID, area.store).details["backup_path"]


class TestRestore:
    def test_puts_the_newest_backup_back_and_loads_it(self, area):
        backup = _backup(area, command="/bin/original")
        launchd = FakeLaunchd()
        result = provision.restore(
            LABEL, launchd, UID, area.agents, backup_root=area.store
        )

        assert result.ok
        assert read(area.target)["ProgramArguments"] == ["/bin/original"]
        assert LABEL in launchd.loaded
        assert result.details["plist_path"] == area.target
        assert backup in "\n".join(result.lines)

    def test_without_a_backup_it_refuses(self, area):
        result = provision.restore(
            LABEL, FakeLaunchd(), UID, area.agents, backup_root=area.store
        )
        assert not result.ok
        assert "no backup" in result.lines[0]

    def test_an_existing_plist_is_refused_without_force(self, area):
        _backup(area, command="/bin/original")
        current = existing(area, command="/bin/newer")
        result = provision.restore(
            LABEL, FakeLaunchd(), UID, area.agents, backup_root=area.store
        )

        assert not result.ok
        assert "--force" in "\n".join(result.lines)
        assert read(current)["ProgramArguments"] == ["/bin/newer"]

    def test_force_backs_the_current_plist_up_before_restoring(self, area):
        _backup(area, command="/bin/original")
        existing(area, command="/bin/newer")
        launchd = FakeLaunchd(loaded=[LABEL])
        result = provision.restore(
            LABEL, launchd, UID, area.agents, force=True, backup_root=area.store
        )

        assert result.ok
        assert read(area.target)["ProgramArguments"] == ["/bin/original"]
        assert read(result.details["backup_path"])["ProgramArguments"] == ["/bin/newer"]

    def test_a_bootstrap_failure_removes_the_restored_file(self, area):
        _backup(area)
        launchd = FakeLaunchd(bootstrap_code=5)
        result = provision.restore(
            LABEL, launchd, UID, area.agents, backup_root=area.store
        )

        assert not result.ok
        assert not os.path.exists(area.target)
        assert LABEL not in launchd.loaded

    def test_an_invalid_label_is_refused(self, area):
        result = provision.restore(
            "com.apple.evil", FakeLaunchd(), UID, area.agents, backup_root=area.store
        )
        assert not result.ok
        assert "belongs to macOS" in result.lines[0]
