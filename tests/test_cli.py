"""CLI tests. launchctl is monkeypatched away, so no real launchd is touched."""

import json

import pytest

from launchdeck import adapter, cli, logs

from .conftest import fake_launchctl, write_plist


@pytest.fixture(autouse=True)
def no_launchctl(monkeypatch):
    """Guarantee that no test in this module can spawn launchctl."""
    monkeypatch.setattr(adapter, "subprocess_runner", fake_launchctl())


def _failing_launchctl(stderr: str, code: int = 1):
    """A runner that still answers `list` but fails every lifecycle call."""
    listing = fake_launchctl()

    def run(argv):
        if len(argv) > 1 and argv[1] in ("list", "print"):
            return listing(argv)
        return code, "", stderr

    return run


@pytest.fixture
def log_agents(tmp_path):
    """A LaunchAgents directory whose jobs point at temporary log files."""
    out = tmp_path / "job.out"
    out.write_text("".join("out {0}\n".format(i) for i in range(1, 31)))
    err = tmp_path / "job.err"
    err.write_text("boom\n")
    directory = tmp_path / "agents"
    directory.mkdir()
    write_plist(
        directory,
        "com.example.logs.plist",
        {
            "Label": "com.example.logs",
            "ProgramArguments": ["/bin/sh", "-c", "echo hi"],
            "StandardOutPath": str(out),
            "StandardErrorPath": str(err),
        },
    )
    write_plist(
        directory,
        "com.example.halflogs.plist",
        {
            "Label": "com.example.halflogs",
            "ProgramArguments": ["/bin/true"],
            "StandardOutPath": str(tmp_path / "never-written.out"),
        },
    )
    write_plist(
        directory,
        "com.example.nologs.plist",
        {"Label": "com.example.nologs", "ProgramArguments": ["/bin/true"]},
    )
    return directory


def test_status_prints_table(agents, capsys):
    assert cli.main(["status", "--dir", str(agents)]) == 0
    out = capsys.readouterr().out
    assert "LABEL" in out
    assert "com.example.running" in out


def test_bare_invocation_defaults_to_status(agents, capsys):
    assert cli.main(["--dir", str(agents)]) == 0
    assert "com.example.running" in capsys.readouterr().out


def test_no_arguments_defaults_to_status(monkeypatch, agents, capsys):
    monkeypatch.setenv("HOME", str(agents.parent))
    assert cli.main([]) == 0
    capsys.readouterr()


def test_json_flag_emits_valid_contract(agents, capsys):
    assert cli.main(["status", "--json", "--dir", str(agents)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == 1
    assert len(payload["jobs"]) == 4


def test_json_flag_before_subcommand_is_accepted(agents, capsys):
    assert cli.main(["--json", "--dir", str(agents)]) == 0
    assert json.loads(capsys.readouterr().out)["schema"] == 1


def test_unknown_command_exits_nonzero(agents):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["bogus"])
    assert excinfo.value.code != 0


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0
    assert "launchdeck" in capsys.readouterr().out


def test_info_prints_a_detail_block(agents, capsys):
    assert cli.main(["info", "com.example.running", "--dir", str(agents)]) == 0
    out = capsys.readouterr().out
    assert "com.example.running" in out
    assert "/bin/sh /tmp/run.sh" in out
    assert "launchctl print:" in out
    assert "last exit code" in out


def test_info_json_matches_the_contract(agents, capsys):
    assert cli.main(["info", "com.example.idle", "--json", "--dir", str(agents)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == 1
    job = payload["job"]
    assert job["label"] == "com.example.idle"
    assert job["program_arguments"] == ["/bin/sh", "/tmp/idle.sh"]
    assert job["raw_schedule_keys"] == ["StartInterval"]
    assert set(job["log_files"]["stdout"]) == {"path", "exists", "size"}


def test_info_unknown_label_suggests_and_exits_one(agents, capsys):
    assert cli.main(["info", "com.example.idl", "--dir", str(agents)]) == 1
    err = capsys.readouterr().err
    assert "unknown label" in err
    assert "com.example.idle" in err


def test_logs_prints_both_sections(log_agents, capsys):
    assert cli.main(["logs", "com.example.logs", "--dir", str(log_agents)]) == 0
    out = capsys.readouterr().out
    assert "== stdout: " in out and "== stderr: " in out
    assert "out 30" in out and "boom" in out
    # The default tail is 20 lines, so the first ten are not shown.
    assert "out 10\n" not in out


def test_logs_line_count_flag(log_agents, capsys):
    assert cli.main(["logs", "com.example.logs", "-n", "2", "--dir", str(log_agents)]) == 0
    out = capsys.readouterr().out
    assert "out 29" in out and "out 30" in out
    assert "out 28" not in out


def test_logs_reports_unset_and_missing_paths(log_agents, capsys):
    assert cli.main(["logs", "com.example.halflogs", "--dir", str(log_agents)]) == 0
    out = capsys.readouterr().out
    assert "(file does not exist yet)" in out
    assert "== stderr: (not set in plist) ==" in out


def test_logs_without_any_path_exits_one(log_agents, capsys):
    assert cli.main(["logs", "com.example.nologs", "--dir", str(log_agents)]) == 1
    err = capsys.readouterr().err
    assert "defines no log paths" in err
    assert "StandardOutPath" in err


def test_logs_unknown_label_exits_one(log_agents, capsys):
    assert cli.main(["logs", "com.example.log", "--dir", str(log_agents)]) == 1
    assert "com.example.logs" in capsys.readouterr().err


def test_logs_follow_exits_cleanly_on_interrupt(log_agents, monkeypatch, capsys):
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(logs, "follow", interrupt)
    code = cli.main(["logs", "com.example.logs", "-f", "--dir", str(log_agents)])
    assert code == 0
    assert "following" in capsys.readouterr().out


def test_start_reports_success(agents, capsys):
    assert cli.main(["start", "com.example.idle", "--dir", str(agents)]) == 0
    assert "started com.example.idle" in capsys.readouterr().out


def test_start_on_an_unloaded_job_exits_one(agents, capsys):
    assert cli.main(["start", "com.example.unloaded", "--dir", str(agents)]) == 1
    err = capsys.readouterr().err
    assert "is not loaded" in err
    assert "ldm load com.example.unloaded" in err


def test_stop_of_an_idle_job_is_a_zero_exit_noop(agents, capsys):
    assert cli.main(["stop", "com.example.idle", "--dir", str(agents)]) == 0
    assert "nothing to stop" in capsys.readouterr().out


def test_stop_of_a_keepalive_job_warns(agents, capsys):
    assert cli.main(["stop", "com.example.running", "--dir", str(agents)]) == 0
    assert "KeepAlive" in capsys.readouterr().out


def test_load_of_a_loaded_job_is_a_zero_exit_noop(agents, capsys):
    assert cli.main(["load", "com.example.idle", "--dir", str(agents)]) == 0
    assert "already loaded" in capsys.readouterr().out


def test_unload_uses_bootout_and_succeeds(agents, capsys):
    assert cli.main(["unload", "com.example.idle", "--dir", str(agents)]) == 0
    assert "unloaded com.example.idle" in capsys.readouterr().out


def test_disable_explains_what_it_controls(agents, capsys):
    assert cli.main(["disable", "com.example.idle", "--dir", str(agents)]) == 0
    assert "refuse to bootstrap" in capsys.readouterr().out


def test_lifecycle_json_output(agents, capsys):
    code = cli.main(["restart", "com.example.idle", "--json", "--dir", str(agents)])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == 1
    assert payload["result"]["action"] == "restart"
    assert payload["result"]["ok"] is True


def test_lifecycle_json_still_goes_to_stdout_on_failure(agents, capsys):
    code = cli.main(["start", "com.example.unloaded", "--json", "--dir", str(agents)])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["ok"] is False


def test_lifecycle_unknown_label_suggests_and_exits_one(agents, capsys):
    assert cli.main(["restart", "com.example.idl", "--dir", str(agents)]) == 1
    assert "com.example.idle" in capsys.readouterr().err


def test_lifecycle_reports_a_launchctl_failure(agents, monkeypatch, capsys):
    monkeypatch.setattr(
        adapter,
        "subprocess_runner",
        _failing_launchctl("Boot-out failed: 5: Input/output error"),
    )
    assert cli.main(["unload", "com.example.idle", "--dir", str(agents)]) == 1
    err = capsys.readouterr().err
    assert "Boot-out failed: 5: Input/output error" in err
    assert "already in that state" in err


def test_error_returns_exit_code_one(agents, monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise RuntimeError("scan exploded")

    monkeypatch.setattr(cli.merge, "collect", boom)
    assert cli.main(["status", "--dir", str(agents)]) == 1
    assert "scan exploded" in capsys.readouterr().err
