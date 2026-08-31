"""Adapter tests: `launchctl list` parsing against canned output only."""

from launchdeck import adapter

from .conftest import (
    SAMPLE_LIST_OUTPUT,
    SAMPLE_PRINT_OUTPUT,
    fake_runner,
    spy_runner,
)


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


def test_gui_domain_uses_the_given_uid():
    assert adapter.gui_domain(uid=501) == "gui/501"


def test_error_code_reads_the_launchd_errno():
    assert adapter.error_code("Boot-out failed: 5: Input/output error") == 5
    assert adapter.error_code("Load failed: 133: Service is disabled") == 133


def test_error_code_is_none_without_an_errno():
    assert adapter.error_code('Could not find service "com.x" in domain') is None


def test_parse_error_explains_a_known_errno():
    text = adapter.parse_error("Boot-out failed: 5: Input/output error\n", 5)
    assert text.startswith("Boot-out failed: 5: Input/output error")
    assert "already in that state" in text


def test_parse_error_keeps_unknown_messages_verbatim_on_one_line():
    text = adapter.parse_error('Could not find service\n  "com.x"\n', 113)
    assert text == 'Could not find service "com.x"'


def test_parse_error_falls_back_to_the_exit_status():
    assert adapter.parse_error("", 64) == "launchctl exited with status 64"


def test_says_disabled_matches_word_or_errno():
    assert adapter.says_disabled("Load failed: 133: whatever")
    assert adapter.says_disabled("Bootstrap failed: Service is disabled")
    assert not adapter.says_disabled("Boot-out failed: 5: Input/output error")


def test_parse_disabled_output_reads_both_wordings():
    text = (
        'disabled services = {\n'
        '\t\t"com.example.off" => disabled\n'
        '\t\t"com.example.old" => true\n'
        '\t\t"com.example.on" => enabled\n'
        '}\n'
    )
    assert adapter.parse_disabled_output(text) == {
        "com.example.off",
        "com.example.old",
    }


def test_is_disabled_queries_the_domain():
    run = spy_runner(stdout='\t\t"com.example.off" => disabled\n')
    assert adapter.is_disabled("com.example.off", run, uid=501) is True
    assert run.calls == [[adapter.LAUNCHCTL, "print-disabled", "gui/501"]]


def test_is_disabled_is_false_for_an_enabled_job():
    run = spy_runner(stdout='\t\t"com.example.off" => disabled\n')
    assert adapter.is_disabled("com.example.on", run, uid=501) is False


def test_is_disabled_is_false_when_launchctl_fails():
    assert adapter.is_disabled("com.example.x", spy_runner(code=1), uid=501) is False


def test_invoke_passes_the_subcommand_through():
    run = spy_runner()
    assert adapter.invoke(["list"], run) == (0, "", "")
    assert run.calls == [[adapter.LAUNCHCTL, "list"]]
