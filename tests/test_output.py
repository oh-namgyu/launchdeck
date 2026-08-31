"""Output tests: table rendering, color gating and the v1 JSON contract."""

import json

from launchdeck import merge, output
from launchdeck.model import JobRecord

from .conftest import SAMPLE_LIST_OUTPUT, fake_runner

JOB_KEYS = {
    "label",
    "loaded",
    "pid",
    "last_exit",
    "schedule",
    "plist_path",
    "stdout_path",
    "stderr_path",
    "state",
}


def _records(agents):
    return merge.collect(str(agents), fake_runner(SAMPLE_LIST_OUTPUT))


def test_json_contract_shape(agents):
    payload = json.loads(output.render_json(_records(agents)))
    assert set(payload) == {"schema", "jobs"}
    assert payload["schema"] == 1
    assert len(payload["jobs"]) == 4
    for job in payload["jobs"]:
        assert set(job) == JOB_KEYS


def test_json_values_are_typed(agents):
    jobs = {j["label"]: j for j in json.loads(output.render_json(_records(agents)))["jobs"]}
    running = jobs["com.example.running"]
    assert running["pid"] == 4242
    assert running["loaded"] is True
    assert running["state"] == "running"
    assert jobs["com.example.unloaded"]["pid"] is None


def test_table_renders_without_crash(agents):
    text = output.render_table(_records(agents))
    lines = text.splitlines()
    assert lines[0].split() == list(output.HEADERS)
    assert len(lines) == 5
    assert "com.example.failing" in text
    assert "every 2h" in text
    assert "keepalive" in text


def test_table_columns_are_aligned(agents):
    lines = output.render_table(_records(agents)).splitlines()
    label_column = lines[0].index("LABEL")
    for line in lines[1:]:
        assert line[label_column:].startswith("com.example.")


def test_table_handles_empty_input():
    assert output.render_table([]) == "No LaunchAgents found."


def test_table_renders_unknown_record():
    record = JobRecord(label="com.example.broken", schedule="?", state="unknown")
    assert "?" in output.render_table([record])


def test_color_output_wraps_rows(agents):
    plain = output.render_table(_records(agents), color=False)
    colored = output.render_table(_records(agents), color=True)
    assert "\033[" not in plain
    assert "\033[32m" in colored and "\033[0m" in colored


def test_color_disabled_when_no_color_env(monkeypatch):
    class TTY:
        def isatty(self):
            return True

    monkeypatch.setenv("NO_COLOR", "1")
    assert output.use_color(TTY()) is False
    monkeypatch.delenv("NO_COLOR")
    assert output.use_color(TTY()) is True


def test_color_disabled_when_not_a_tty(monkeypatch):
    class Pipe:
        def isatty(self):
            return False

    monkeypatch.delenv("NO_COLOR", raising=False)
    assert output.use_color(Pipe()) is False


def test_shorten_path_uses_tilde(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert output.shorten_path(str(tmp_path / "a" / "b.plist")) == "~/a/b.plist"
    assert output.shorten_path(None) == "-"
