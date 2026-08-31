"""Log tailing tests against temporary files only - never a real job's logs."""

import io

from launchdeck import logs, output
from launchdeck.model import JobRecord


def make_log(tmp_path, name, lines):
    """Write a numbered log file and return its path."""
    path = tmp_path / name
    path.write_text("".join("line {0}\n".format(i) for i in lines))
    return str(path)


def test_resolve_log_paths_expands_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    record = JobRecord(label="com.example.x", stdout_path="~/job.out")
    streams = logs.resolve_log_paths(record)
    assert streams[0] == ("stdout", str(tmp_path / "job.out"))
    assert streams[1] == ("stderr", None)


def test_declared_drops_unset_streams():
    record = JobRecord(label="com.example.x", stderr_path="/tmp/x.err")
    assert logs.declared(logs.resolve_log_paths(record)) == [("stderr", "/tmp/x.err")]


def test_follow_targets_deduplicates_shared_files():
    record = JobRecord(
        label="com.example.x", stdout_path="/tmp/both.log", stderr_path="/tmp/both.log"
    )
    targets = logs.follow_targets(logs.resolve_log_paths(record))
    assert targets == [("stdout", "/tmp/both.log")]


def test_tail_lines_returns_the_last_lines(tmp_path):
    path = make_log(tmp_path, "job.out", range(1, 101))
    assert logs.tail_lines(path, 3) == ["line 98", "line 99", "line 100"]


def test_tail_lines_handles_files_shorter_than_the_request(tmp_path):
    path = make_log(tmp_path, "job.out", range(1, 3))
    assert logs.tail_lines(path, 20) == ["line 1", "line 2"]


def test_tail_lines_crosses_read_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(logs, "_CHUNK", 16)
    path = make_log(tmp_path, "job.out", range(1, 51))
    assert logs.tail_lines(path, 5)[0] == "line 46"


def test_tail_lines_without_trailing_newline(tmp_path):
    path = tmp_path / "job.out"
    path.write_text("a\nb")
    assert logs.tail_lines(str(path), 2) == ["a", "b"]


def test_tail_lines_with_zero_count(tmp_path):
    assert logs.tail_lines(make_log(tmp_path, "job.out", [1]), 0) == []


def test_tail_text_notes_a_missing_file(tmp_path):
    assert logs.tail_text(str(tmp_path / "nope.out")) == "(file does not exist yet)"


def test_tail_text_notes_an_empty_file(tmp_path):
    path = tmp_path / "job.out"
    path.write_text("")
    assert logs.tail_text(str(path)) == "(empty)"


def test_tail_text_joins_lines(tmp_path):
    path = make_log(tmp_path, "job.out", range(1, 4))
    assert logs.tail_text(path, 2) == "line 2\nline 3"


def test_tail_text_reads_undecodable_bytes(tmp_path):
    path = tmp_path / "job.out"
    path.write_bytes(b"ok\n\xff\xfe\n")
    assert logs.tail_text(str(path), 2).startswith("ok")


def test_read_appended_returns_only_new_bytes(tmp_path):
    path = tmp_path / "job.out"
    path.write_text("first\n")
    text, offset = logs.read_appended(str(path), 0)
    assert text == "first\n" and offset == 6

    with open(str(path), "a") as handle:
        handle.write("second\n")
    text, offset = logs.read_appended(str(path), offset)
    assert text == "second\n" and offset == 13

    assert logs.read_appended(str(path), offset) == ("", 13)


def test_read_appended_restarts_after_truncation(tmp_path):
    path = tmp_path / "job.out"
    path.write_text("short\n")
    text, offset = logs.read_appended(str(path), 999)
    assert text == "short\n" and offset == 6


def test_read_appended_tolerates_a_missing_file(tmp_path):
    assert logs.read_appended(str(tmp_path / "gone.out"), 12) == ("", 12)


def test_follow_starts_at_the_end_of_the_file(tmp_path):
    path = tmp_path / "job.out"
    path.write_text("old\n")
    stream = io.StringIO()
    logs.follow([("stdout", str(path))], stream=stream, poll=0, iterations=1)
    assert stream.getvalue() == ""


def test_follow_prints_appended_lines(tmp_path):
    path = tmp_path / "job.out"
    path.write_text("old\nnew\n")
    stream = io.StringIO()
    logs.follow(
        [("stdout", str(path))],
        stream=stream,
        poll=0,
        iterations=1,
        offsets={str(path): 4},
    )
    assert stream.getvalue() == "new\n"


def test_follow_prefixes_lines_when_two_streams(tmp_path):
    out = tmp_path / "job.out"
    err = tmp_path / "job.err"
    out.write_text("a\n")
    err.write_text("b\n")
    stream = io.StringIO()
    logs.follow(
        [("stdout", str(out)), ("stderr", str(err))],
        stream=stream,
        poll=0,
        iterations=1,
        offsets={str(out): 0, str(err): 0},
    )
    assert stream.getvalue() == "[stdout] a\n[stderr] b\n"


def test_render_log_section_headers(tmp_path):
    section = output.render_log_section("stdout", "/tmp/job.out", "line 1")
    assert section == "== stdout: /tmp/job.out ==\nline 1"
    assert "(not set in plist)" in output.render_log_section("stderr", None, "-")
