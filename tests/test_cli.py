"""CLI tests. launchctl is monkeypatched away, so no real launchd is touched."""

import json

import pytest

from launchdeck import adapter, cli

from .conftest import SAMPLE_LIST_OUTPUT, fake_runner


@pytest.fixture(autouse=True)
def no_launchctl(monkeypatch):
    """Guarantee that no test in this module can spawn launchctl."""
    monkeypatch.setattr(adapter, "subprocess_runner", fake_runner(SAMPLE_LIST_OUTPUT))


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


def test_error_returns_exit_code_one(agents, monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise RuntimeError("scan exploded")

    monkeypatch.setattr(cli.merge, "collect", boom)
    assert cli.main(["status", "--dir", str(agents)]) == 1
    assert "scan exploded" in capsys.readouterr().err
