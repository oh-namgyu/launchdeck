"""Merge tests: all four states plus the ghost exclusion rule."""

from launchdeck import merge, scanner
from launchdeck.model import (
    STATE_FAILING,
    STATE_IDLE,
    STATE_RUNNING,
    STATE_UNKNOWN,
    STATE_UNLOADED,
    derive_state,
)

from .conftest import SAMPLE_LIST_OUTPUT, fake_runner


def _by_label(agents):
    records = merge.collect(str(agents), fake_runner(SAMPLE_LIST_OUTPUT))
    return {record.label: record for record in records}


def test_running_state(agents):
    record = _by_label(agents)["com.example.running"]
    assert (record.state, record.loaded, record.pid) == (STATE_RUNNING, True, 4242)


def test_idle_state(agents):
    record = _by_label(agents)["com.example.idle"]
    assert (record.state, record.pid, record.last_exit) == (STATE_IDLE, None, 0)


def test_failing_state(agents):
    record = _by_label(agents)["com.example.failing"]
    assert (record.state, record.last_exit) == (STATE_FAILING, 28)


def test_unloaded_state(agents):
    record = _by_label(agents)["com.example.unloaded"]
    assert record.state == STATE_UNLOADED
    assert record.loaded is False
    assert record.pid is None and record.last_exit is None


def test_ghost_is_not_reported_by_status(agents):
    """A label loaded in launchd but absent from disk belongs to `doctor`."""
    assert "com.example.ghost" not in _by_label(agents)


def test_unparsable_plist_stays_unknown(tmp_path):
    (tmp_path / "com.example.running.plist").write_text("broken")
    records = merge.collect(str(tmp_path), fake_runner(SAMPLE_LIST_OUTPUT))
    assert records[0].state == STATE_UNKNOWN
    assert records[0].pid is None


def test_empty_launchctl_marks_everything_unloaded(agents):
    records = merge.merge(scanner.scan(str(agents)), {})
    assert {record.state for record in records} == {STATE_UNLOADED}


class TestDeriveState:
    def test_pid_wins(self):
        assert derive_state(True, 10, 0) == STATE_RUNNING

    def test_zero_exit_is_idle(self):
        assert derive_state(True, None, 0) == STATE_IDLE

    def test_nonzero_exit_is_failing(self):
        assert derive_state(True, None, 1) == STATE_FAILING

    def test_absent_is_unloaded(self):
        assert derive_state(False, None, None) == STATE_UNLOADED

    def test_parse_failure_beats_everything(self):
        assert derive_state(True, 10, 0, parse_failed=True) == STATE_UNKNOWN
