"""Adapter tests: `launchctl list` parsing against canned output only."""

from launchdeck import adapter

from .conftest import SAMPLE_LIST_OUTPUT, SAMPLE_PRINT_OUTPUT, fake_runner


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


def test_gui_target_uses_the_given_uid():
    assert adapter.gui_target("com.example.x", uid=501) == "gui/501/com.example.x"


def test_parse_print_output_extracts_known_fields():
    fields = adapter.parse_print_output(SAMPLE_PRINT_OUTPUT)
    assert fields["state"] == "not running"
    assert fields["last exit code"] == "0"
    assert fields["runs"] == "5"
    assert fields["path"].endswith("com.example.running.plist")
    # Nested block openers and unknown keys are dropped.
    assert "arguments" not in fields
    assert "type" not in fields


def test_parse_print_output_ignores_unexpected_format():
    assert adapter.parse_print_output("not a launchctl dump at all") == {}


def test_launchctl_print_uses_injected_runner():
    fields = adapter.launchctl_print(
        "com.example.running", fake_runner(SAMPLE_PRINT_OUTPUT), uid=501
    )
    assert fields["state"] == "not running"


def test_launchctl_print_returns_empty_on_failure():
    assert adapter.launchctl_print("nope", fake_runner("", code=113), uid=501) == {}


def test_launchctl_print_returns_empty_when_binary_missing():
    def broken(argv):
        raise adapter.LaunchctlError("no such file")

    assert adapter.launchctl_print("com.example.x", broken, uid=501) == {}


def test_launchctl_print_targets_the_right_service():
    seen = []

    def spy(argv):
        seen.append(list(argv))
        return 0, SAMPLE_PRINT_OUTPUT, ""

    adapter.launchctl_print("com.example.running", spy, uid=501)
    assert seen == [[adapter.LAUNCHCTL, "print", "gui/501/com.example.running"]]
