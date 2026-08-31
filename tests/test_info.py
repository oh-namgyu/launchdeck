"""Detail view tests: label lookup, log stats and rendering. No launchctl."""

import json

import pytest

from launchdeck import info, merge, output, scanner
from launchdeck.model import STATE_RUNNING, JobRecord

from .conftest import SAMPLE_LIST_OUTPUT, SAMPLE_PRINT_OUTPUT, fake_runner


@pytest.fixture
def records(agents):
    """Merged records for the sample LaunchAgents directory."""
    return merge.collect(str(agents), fake_runner(SAMPLE_LIST_OUTPUT))


def test_find_job_returns_the_matching_record(records):
    assert info.find_job(records, "com.example.idle").label == "com.example.idle"


def test_find_job_suggests_close_matches(records):
    with pytest.raises(LookupError) as excinfo:
        info.find_job(records, "com.example.faling")
    message = str(excinfo.value)
    assert "unknown label" in message
    assert "com.example.failing" in message


def test_find_job_suggests_substring_matches(records):
    with pytest.raises(LookupError) as excinfo:
        info.find_job(records, "idle")
    assert "com.example.idle" in str(excinfo.value)


def test_find_job_without_any_match_says_so(records):
    with pytest.raises(LookupError) as excinfo:
        info.find_job(records, "zzzzzzzzzz")
    assert "no similar LaunchAgent found" in str(excinfo.value)


def test_suggest_is_capped(records):
    assert len(info.suggest("com", [r.label for r in records])) <= info.MAX_SUGGESTIONS


def test_log_file_info_reports_existing_file(tmp_path):
    log = tmp_path / "job.out"
    log.write_text("hello\n")
    entry = info.log_file_info(str(log))
    assert entry == {"path": str(log), "exists": True, "size": 6}


def test_log_file_info_handles_missing_and_unset_paths(tmp_path):
    missing = info.log_file_info(str(tmp_path / "nope.out"))
    assert missing["exists"] is False and missing["size"] is None
    assert info.log_file_info(None)["path"] is None


def test_scanner_records_raw_schedule_keys(agents):
    by_label = {record.label: record for record in scanner.scan(str(agents))}
    assert by_label["com.example.running"].raw_schedule_keys == ["KeepAlive"]
    assert by_label["com.example.idle"].raw_schedule_keys == ["StartInterval"]
    assert by_label["com.example.unloaded"].raw_schedule_keys == []


def test_describe_extends_the_job_dict(records):
    record = info.find_job(records, "com.example.running")
    detail = info.describe(record, fake_runner(SAMPLE_PRINT_OUTPUT), uid=501)
    assert detail["label"] == "com.example.running"
    assert detail["program_arguments"] == ["/bin/sh", "/tmp/run.sh"]
    assert detail["raw_schedule_keys"] == ["KeepAlive"]
    assert set(detail["log_files"]) == {"stdout", "stderr"}
    assert detail["log_files"]["stdout"]["path"] == "/tmp/run.out"
    assert detail["launchctl_print"]["state"] == "not running"


def test_describe_survives_launchctl_failure(records):
    record = info.find_job(records, "com.example.idle")
    detail = info.describe(record, fake_runner("", code=113), uid=501)
    assert detail["launchctl_print"] == {}


def test_render_info_shows_the_detail_block(records):
    detail = info.describe(
        info.find_job(records, "com.example.running"),
        fake_runner(SAMPLE_PRINT_OUTPUT),
        uid=501,
    )
    text = output.render_info(detail)
    assert "label" in text and "com.example.running" in text
    assert "running" in text
    assert "/bin/sh /tmp/run.sh" in text
    assert "keepalive  [KeepAlive]" in text
    assert "launchctl print:" in text
    assert "last exit code" in text


def test_render_info_marks_unavailable_launchctl_output():
    detail = info.describe(JobRecord(label="com.example.x"), fake_runner("", code=1))
    text = output.render_info(detail)
    assert "not available" in text
    assert "(not set in plist)" in text


def test_render_info_quotes_arguments_with_spaces():
    record = JobRecord(label="com.example.x", program=["/bin/sh", "-c", "echo hi"])
    text = output.render_info(info.describe(record, fake_runner("", code=1)))
    assert "'echo hi'" in text


def test_render_info_json_shape(records):
    detail = info.describe(
        info.find_job(records, "com.example.failing"), fake_runner("", code=1)
    )
    payload = json.loads(output.render_info(detail, as_json=True))
    assert payload["schema"] == 1
    job = payload["job"]
    assert job["label"] == "com.example.failing"
    assert job["program_arguments"] == ["/tmp/fail.sh"]
    assert job["raw_schedule_keys"] == ["StartCalendarInterval"]
    assert job["log_files"]["stderr"] == {"path": None, "exists": False, "size": None}
    assert job["state"] == "failing"


def test_render_info_reports_running_state_symbol():
    record = JobRecord(label="com.example.up", pid=4242, state=STATE_RUNNING)
    text = output.render_info(info.describe(record, fake_runner("", code=1)))
    assert "● running" in text
    assert "4242" in text


def test_format_size_scales():
    assert output.format_size(0) == "0 B"
    assert output.format_size(6) == "6 B"
    assert output.format_size(2048) == "2.0 KB"
    assert output.format_size(5 * 1024 * 1024) == "5.0 MB"
