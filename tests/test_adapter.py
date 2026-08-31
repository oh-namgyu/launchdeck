"""Adapter tests: `launchctl list` parsing against canned output only."""

from launchdeck import adapter

from .conftest import SAMPLE_LIST_OUTPUT, fake_runner


def test_parse_list_output():
    jobs = adapter.parse_list_output(SAMPLE_LIST_OUTPUT)
    assert jobs["com.example.running"] == (4242, 0)
    assert jobs["com.example.idle"] == (None, 0)
    assert jobs["com.example.failing"] == (None, 28)
    assert "Label" not in jobs


def test_parse_handles_negative_exit_codes():
    jobs = adapter.parse_list_output("PID\tStatus\tLabel\n-\t-9\tcom.example.signal")
    assert jobs["com.example.signal"] == (None, -9)


def test_parse_skips_malformed_lines():
    text = "PID\tStatus\tLabel\ngarbage\n\n-\t0\tcom.example.ok\n"
    jobs = adapter.parse_list_output(text)
    assert list(jobs) == ["com.example.ok"]


def test_parse_accepts_space_separated_output():
    jobs = adapter.parse_list_output("PID Status Label\n7 0 com.example.spaced")
    assert jobs["com.example.spaced"] == (7, 0)


def test_launchctl_list_uses_injected_runner():
    jobs = adapter.launchctl_list(fake_runner(SAMPLE_LIST_OUTPUT))
    assert len(jobs) == 4


def test_launchctl_list_returns_empty_on_failure():
    assert adapter.launchctl_list(fake_runner("", code=1)) == {}


def test_launchctl_list_returns_empty_when_binary_missing():
    def broken(argv):
        raise adapter.LaunchctlError("no such file")

    assert adapter.launchctl_list(broken) == {}


def test_build_argv_names_the_binary_once():
    assert adapter.build_argv("list") == [adapter.LAUNCHCTL, "list"]
