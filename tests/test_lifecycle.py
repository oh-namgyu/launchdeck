"""Lifecycle tests. Every launchctl call is a spy runner - launchd is never hit."""

import os

import pytest

from launchdeck import adapter, lifecycle, merge
from launchdeck.model import JobRecord

from .conftest import spy_runner

UID = 501
LABEL = "com.example.job"
PLIST = "/tmp/agents/com.example.job.plist"


def job(**overrides) -> JobRecord:
    """A loaded, running job record; override any field per test."""
    fields = {
        "label": LABEL,
        "loaded": True,
        "pid": 4242,
        "plist_path": PLIST,
        "state": "running",
    }
    fields.update(overrides)
    return JobRecord(**fields)


def target(label: str = LABEL) -> str:
    return "gui/{0}/{1}".format(UID, label)


# `launchctl print-disabled gui/501` output naming our test job.
DISABLED_OUTPUT = 'disabled services = {\n\t\t"com.example.job" => disabled\n}\n'


def _unloaded(tmp_path) -> JobRecord:
    """An unloaded record whose plist really exists, ready for ``load``."""
    path = str(tmp_path / "job.plist")
    open(path, "w").close()
    return job(loaded=False, pid=None, plist_path=path, state="unloaded")


def _bootstrap_failure(disabled_output: str):
    """Runner that fails bootstrap and answers print-disabled with a listing."""
    run = spy_runner()

    def dispatch(argv):
        run.calls.append(list(argv))
        if argv[1] == "print-disabled":
            return 0, disabled_output, ""
        return 5, "", "Bootstrap failed: 5: Input/output error"

    dispatch.calls = run.calls
    return dispatch


class TestStart:
    def test_uses_kickstart(self):
        run = spy_runner()
        lifecycle.start(job(), run, uid=UID)
        assert run.calls == [[adapter.LAUNCHCTL, "kickstart", target()]]

    def test_message_says_the_schedule_is_untouched(self):
        result = lifecycle.start(job(), spy_runner(), uid=UID)
        assert result.ok and result.changed
        assert "schedule is unchanged" in result.lines[0]

    def test_unloaded_job_is_refused_with_a_load_hint(self):
        run = spy_runner()
        result = lifecycle.start(job(loaded=False, pid=None), run, uid=UID)
        assert not result.ok
        assert run.calls == []
        assert "ldm load {0}".format(LABEL) in "\n".join(result.lines)

    def test_failure_is_reported_readably(self):
        run = spy_runner(code=113, stderr='Could not find service "x" in domain\n')
        result = lifecycle.start(job(), run, uid=UID)
        assert not result.ok
        assert result.lines == ['start failed: Could not find service "x" in domain']


class TestStop:
    def test_uses_kill_sigterm(self):
        run = spy_runner()
        lifecycle.stop(job(), run, uid=UID)
        assert run.calls == [[adapter.LAUNCHCTL, "kill", "SIGTERM", target()]]

    def test_not_running_is_a_successful_noop(self):
        run = spy_runner()
        result = lifecycle.stop(job(pid=None, state="idle"), run, uid=UID)
        assert result.ok and not result.changed
        assert run.calls == []
        assert "nothing to stop" in result.lines[0]

    def test_keepalive_job_warns_about_the_restart(self):
        result = lifecycle.stop(job(keep_alive=True), spy_runner(), uid=UID)
        text = "\n".join(result.lines)
        assert "KeepAlive" in text and "start it again" in text
        assert "ldm unload" in text

    def test_plain_job_gets_no_keepalive_warning(self):
        result = lifecycle.stop(job(), spy_runner(), uid=UID)
        assert len(result.lines) == 1
        assert "KeepAlive" not in result.lines[0]

    def test_no_such_process_is_treated_as_a_noop(self):
        run = spy_runner(code=3, stderr="Could not signal service: 3: No such process")
        result = lifecycle.stop(job(), run, uid=UID)
        assert result.ok and not result.changed

    def test_other_failures_are_errors(self):
        run = spy_runner(code=1, stderr="Kill failed: 150: Operation not permitted")
        result = lifecycle.stop(job(), run, uid=UID)
        assert not result.ok
        assert "Operation not permitted" in result.lines[0]


class TestRestart:
    def test_uses_kickstart_dash_k(self):
        run = spy_runner()
        lifecycle.restart(job(), run, uid=UID)
        assert run.calls == [[adapter.LAUNCHCTL, "kickstart", "-k", target()]]

    def test_unloaded_job_is_refused(self):
        result = lifecycle.restart(job(loaded=False, pid=None), spy_runner(), uid=UID)
        assert not result.ok
        assert "ldm load" in "\n".join(result.lines)


class TestLoad:
    def test_uses_bootstrap_with_the_domain_and_plist(self, tmp_path):
        path = str(tmp_path / "job.plist")
        open(path, "w").close()
        run = spy_runner()
        lifecycle.load(job(loaded=False, pid=None, plist_path=path), run, uid=UID)
        assert run.calls == [[adapter.LAUNCHCTL, "bootstrap", "gui/501", path]]

    def test_already_loaded_is_a_successful_noop(self):
        run = spy_runner()
        result = lifecycle.load(job(), run, uid=UID)
        assert result.ok and not result.changed
        assert run.calls == []
        assert "already loaded" in result.lines[0]

    def test_disabled_job_gets_an_enable_hint(self, tmp_path):
        # macOS 15 answers a disabled bootstrap with a plain I/O error, so the
        # hint has to come from print-disabled, not from the message.
        run = _bootstrap_failure(DISABLED_OUTPUT)
        result = lifecycle.load(_unloaded(tmp_path), run, uid=UID)
        assert not result.ok
        text = "\n".join(result.lines)
        assert "Bootstrap failed: 5: Input/output error" in text
        assert "ldm enable {0}".format(LABEL) in text
        assert run.calls[-1] == [adapter.LAUNCHCTL, "print-disabled", "gui/501"]

    def test_an_enabled_job_gets_no_enable_hint(self, tmp_path):
        run = _bootstrap_failure('\t\t"com.other.job" => disabled\n')
        result = lifecycle.load(_unloaded(tmp_path), run, uid=UID)
        assert not result.ok
        assert "Bootstrap failed: 5: Input/output error" in result.lines[0]
        assert "ldm enable" not in "\n".join(result.lines)

    def test_an_explicit_disabled_message_is_enough(self, tmp_path):
        run = spy_runner(code=133, stderr="Bootstrap failed: 133: Service is disabled")
        result = lifecycle.load(_unloaded(tmp_path), run, uid=UID)
        assert "ldm enable {0}".format(LABEL) in "\n".join(result.lines)

    def test_missing_plist_file_is_an_error(self):
        run = spy_runner()
        result = lifecycle.load(job(loaded=False, pid=None), run, uid=UID)
        assert not result.ok
        assert run.calls == []
        assert "no plist file" in result.lines[0]


class TestUnload:
    def test_uses_bootout(self):
        run = spy_runner()
        lifecycle.unload(job(), run, uid=UID)
        assert run.calls == [[adapter.LAUNCHCTL, "bootout", target()]]

    def test_not_loaded_is_a_successful_noop(self):
        run = spy_runner()
        result = lifecycle.unload(job(loaded=False, pid=None), run, uid=UID)
        assert result.ok and not result.changed
        assert run.calls == []

    def test_failure_explains_the_errno(self):
        run = spy_runner(code=5, stderr="Boot-out failed: 5: Input/output error")
        result = lifecycle.unload(job(), run, uid=UID)
        assert not result.ok
        assert "Boot-out failed: 5: Input/output error" in result.lines[0]
        assert "already in that state" in result.lines[0]


class TestEnableDisable:
    def test_enable_argv(self):
        run = spy_runner()
        lifecycle.enable(job(), run, uid=UID)
        assert run.calls == [[adapter.LAUNCHCTL, "enable", target()]]

    def test_disable_argv(self):
        run = spy_runner()
        lifecycle.disable(job(), run, uid=UID)
        assert run.calls == [[adapter.LAUNCHCTL, "disable", target()]]

    def test_disable_explains_loadability_not_autostart(self):
        result = lifecycle.disable(job(), spy_runner(), uid=UID)
        text = "\n".join(result.lines)
        assert "refuse to bootstrap" in text
        assert "ldm load" in text
        assert "already loaded" in text
        # It controls loadability, never "start at boot".
        assert "autostart" not in text and "at boot" not in text

    def test_enable_explains_loadability(self):
        result = lifecycle.enable(job(), spy_runner(), uid=UID)
        assert "can bootstrap it" in "\n".join(result.lines)

    def test_failure_is_reported(self):
        run = spy_runner(code=112, stderr="Enable failed: 112: Could not find domain")
        result = lifecycle.enable(job(), run, uid=UID)
        assert not result.ok
        assert "no such domain" in result.lines[0]


class TestResolve:
    def test_returns_the_matching_record(self, agents):
        records = merge.collect(str(agents), lambda argv: (0, "", ""))
        record = lifecycle.resolve(records, "com.example.idle", str(agents))
        assert record.label == "com.example.idle"

    def test_unknown_label_raises_with_suggestions(self, agents):
        records = merge.collect(str(agents), lambda argv: (0, "", ""))
        with pytest.raises(LookupError) as excinfo:
            lifecycle.resolve(records, "com.example.idl", str(agents))
        assert "com.example.idle" in str(excinfo.value)

    def test_plist_resolving_outside_the_directory_is_refused(self, tmp_path):
        outside = tmp_path / "outside.plist"
        outside.write_text("")
        directory = tmp_path / "agents"
        directory.mkdir()
        link = directory / "com.example.link.plist"
        os.symlink(str(outside), str(link))
        record = JobRecord(label="com.example.link", plist_path=str(link))
        with pytest.raises(ValueError) as excinfo:
            lifecycle.resolve([record], "com.example.link", str(directory))
        assert "refusing to operate" in str(excinfo.value)

    def test_a_record_without_a_plist_path_is_refused(self, tmp_path):
        record = JobRecord(label="com.example.ghost")
        with pytest.raises(ValueError):
            lifecycle.resolve([record], "com.example.ghost", str(tmp_path))

    def test_within_managed_dir_accepts_a_real_child(self, tmp_path):
        path = tmp_path / "com.example.ok.plist"
        path.write_text("")
        assert lifecycle.within_managed_dir(str(path), str(tmp_path))
