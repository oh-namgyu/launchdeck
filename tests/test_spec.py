"""Spec tests: label rules, the friendly schedule syntax, the plist shape."""

import pytest

from launchdeck import spec


class TestLabel:
    @pytest.mark.parametrize(
        "label",
        [
            "a",
            "com.example.job",
            "com.you.backup-daily",
            "9lives",
            "A.B-C.0",
        ],
    )
    def test_accepted(self, label):
        assert spec.validate_label(label) == label

    @pytest.mark.parametrize(
        "label",
        [
            "",
            ".leading.dot",
            "-leading.hyphen",
            "com.example job",
            "com/example/job",
            "com.example.job!",
            "com.example.job\n",
            "../escape",
            "café.job",
        ],
    )
    def test_refused(self, label):
        with pytest.raises(ValueError) as excinfo:
            spec.validate_label(label)
        assert "invalid label" in str(excinfo.value)

    def test_apple_namespace_is_refused(self):
        with pytest.raises(ValueError) as excinfo:
            spec.validate_label("com.apple.something")
        assert "belongs to macOS" in str(excinfo.value)

    def test_a_similar_but_different_prefix_is_fine(self):
        assert spec.validate_label("com.appleseed.job")


class TestInterval:
    @pytest.mark.parametrize(
        "text,seconds",
        [("45s", 45), ("30m", 1800), ("2h", 7200), ("1d", 86400), ("90", 90)],
    )
    def test_parsed(self, text, seconds):
        assert spec.parse_interval(text) == seconds

    @pytest.mark.parametrize("text", ["", "0", "0m", "-5m", "2 hours", "abc", "1.5h", "h"])
    def test_refused(self, text):
        with pytest.raises(ValueError) as excinfo:
            spec.parse_interval(text)
        assert "--interval" in str(excinfo.value)


class TestCalendar:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("09:30", {"Hour": 9, "Minute": 30}),
            ("9:30", {"Hour": 9, "Minute": 30}),
            ("23:59", {"Hour": 23, "Minute": 59}),
            ("daily 06:00", {"Hour": 6, "Minute": 0}),
            ("Mon 09:30", {"Weekday": 1, "Hour": 9, "Minute": 30}),
            ("sunday 00:00", {"Weekday": 0, "Hour": 0, "Minute": 0}),
            ("SAT 12:05", {"Weekday": 6, "Hour": 12, "Minute": 5}),
        ],
    )
    def test_parsed(self, text, expected):
        assert spec.parse_calendar(text) == expected

    @pytest.mark.parametrize(
        "text", ["", "25:99", "24:00", "12:60", "noon", "9:3", "Xyz 09:30", "Mon 9 30"]
    )
    def test_refused(self, text):
        with pytest.raises(ValueError) as excinfo:
            spec.parse_calendar(text)
        assert "--calendar" in str(excinfo.value)


def job(**overrides) -> spec.JobSpec:
    """A minimal valid JobSpec; override any field per test."""
    fields = {"label": "com.example.job", "command": "/bin/echo hi"}
    fields.update(overrides)
    return spec.JobSpec(**fields)


class TestBuild:
    def test_minimal_shape(self):
        data = spec.build(job())
        assert data["Label"] == "com.example.job"
        assert data["ProgramArguments"] == ["/bin/echo", "hi"]
        assert data["StandardOutPath"].endswith("/com.example.job/out.log")
        assert data["StandardErrorPath"].endswith("/com.example.job/err.log")
        assert "StartInterval" not in data and "StartCalendarInterval" not in data
        assert "RunAtLoad" not in data and "KeepAlive" not in data

    def test_command_is_split_not_shelled(self):
        data = spec.build(job(command="/bin/sh -c 'echo one two'"))
        assert data["ProgramArguments"] == ["/bin/sh", "-c", "echo one two"]

    def test_empty_command_is_refused(self):
        with pytest.raises(ValueError) as excinfo:
            spec.build(job(command="   "))
        assert "--cmd is empty" in str(excinfo.value)

    def test_unbalanced_quotes_are_refused(self):
        with pytest.raises(ValueError) as excinfo:
            spec.build(job(command="/bin/sh -c 'oops"))
        assert "cannot parse --cmd" in str(excinfo.value)

    def test_interval_becomes_startinterval(self):
        assert spec.build(job(interval="2h"))["StartInterval"] == 7200

    def test_calendar_becomes_startcalendarinterval(self):
        data = spec.build(job(calendar="Mon 09:30"))
        assert data["StartCalendarInterval"] == {"Weekday": 1, "Hour": 9, "Minute": 30}

    def test_both_schedules_are_refused(self):
        with pytest.raises(ValueError) as excinfo:
            spec.build(job(interval="2h", calendar="09:30"))
        assert "cannot be used together" in str(excinfo.value)

    def test_flags_become_plist_keys(self):
        data = spec.build(job(run_at_load=True, keep_alive=True))
        assert data["RunAtLoad"] is True and data["KeepAlive"] is True

    def test_log_dir_is_used_verbatim(self, tmp_path):
        data = spec.build(job(log_dir=str(tmp_path)))
        assert data["StandardOutPath"] == str(tmp_path / "out.log")
        assert data["StandardErrorPath"] == str(tmp_path / "err.log")

    def test_log_dir_expands_the_home_shortcut(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        data = spec.build(job(log_dir="~/logs"))
        assert data["StandardOutPath"] == str(tmp_path / "logs" / "out.log")

    def test_bad_label_is_refused_before_anything_else(self):
        with pytest.raises(ValueError):
            spec.build(job(label="com.apple.evil", command=""))
