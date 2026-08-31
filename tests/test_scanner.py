"""Scanner tests: plist parsing, schedule summaries, and failure degradation."""

from launchdeck import scanner
from launchdeck.model import STATE_UNKNOWN

from .conftest import write_binary_plist, write_plist


def test_scan_ignores_non_plist_files(agents):
    labels = [record.label for record in scanner.scan(str(agents))]
    assert labels == [
        "com.example.failing",
        "com.example.idle",
        "com.example.running",
        "com.example.unloaded",
    ]


def test_scan_reads_xml_plist(agents):
    record = {r.label: r for r in scanner.scan(str(agents))}["com.example.running"]
    assert record.program == ["/bin/sh", "/tmp/run.sh"]
    assert record.stdout_path == "/tmp/run.out"
    assert record.stderr_path == "/tmp/run.err"
    assert record.plist_path.endswith("com.example.running.plist")


def test_scan_reads_binary_plist(tmp_path):
    write_binary_plist(
        tmp_path,
        "com.example.binary.plist",
        {
            "Label": "com.example.binary",
            "Program": "/usr/bin/true",
            "StartInterval": 1800,
        },
    )
    records = scanner.scan(str(tmp_path))
    assert len(records) == 1
    assert records[0].label == "com.example.binary"
    assert records[0].schedule == "every 30m"
    assert records[0].program == ["/usr/bin/true"]


def test_broken_plist_degrades_to_unknown(tmp_path):
    (tmp_path / "com.example.broken.plist").write_text("<<< not a plist >>>")
    records = scanner.scan(str(tmp_path))
    assert len(records) == 1
    assert records[0].label == "com.example.broken"
    assert records[0].state == STATE_UNKNOWN
    assert records[0].plist_path.endswith("com.example.broken.plist")


def test_missing_label_falls_back_to_filename(tmp_path):
    write_plist(tmp_path, "com.example.nolabel.plist", {"Program": "/bin/true"})
    assert scanner.scan(str(tmp_path))[0].label == "com.example.nolabel"


def test_missing_directory_returns_empty(tmp_path):
    assert scanner.scan(str(tmp_path / "does-not-exist")) == []


def test_non_plist_files_listed_for_doctor(agents):
    leftovers = [path.rsplit("/", 1)[-1] for path in scanner.non_plist_files(str(agents))]
    assert leftovers == ["com.example.idle.plist.bak", "notes.txt"]


class TestScheduleSummary:
    def test_keepalive_wins(self):
        assert scanner.summarize_schedule({"KeepAlive": True, "StartInterval": 60}) == (
            "keepalive"
        )

    def test_keepalive_dict(self):
        assert scanner.summarize_schedule({"KeepAlive": {"SuccessfulExit": False}}) == (
            "keepalive"
        )

    def test_interval_hours(self):
        assert scanner.summarize_schedule({"StartInterval": 7200}) == "every 2h"

    def test_interval_minutes(self):
        assert scanner.summarize_schedule({"StartInterval": 300}) == "every 5m"

    def test_interval_seconds(self):
        assert scanner.summarize_schedule({"StartInterval": 45}) == "every 45s"

    def test_interval_days(self):
        assert scanner.summarize_schedule({"StartInterval": 172800}) == "every 2d"

    def test_calendar_daily(self):
        data = {"StartCalendarInterval": {"Hour": 9, "Minute": 40}}
        assert scanner.summarize_schedule(data) == "daily 09:40"

    def test_calendar_hour_only(self):
        data = {"StartCalendarInterval": {"Hour": 22}}
        assert scanner.summarize_schedule(data) == "daily 22:00"

    def test_calendar_minute_only_is_hourly(self):
        data = {"StartCalendarInterval": {"Minute": 5}}
        assert scanner.summarize_schedule(data) == "hourly :05"

    def test_calendar_weekday(self):
        data = {"StartCalendarInterval": {"Weekday": 1, "Hour": 7, "Minute": 0}}
        assert scanner.summarize_schedule(data) == "Mon 07:00"

    def test_calendar_list_counts_extras(self):
        data = {
            "StartCalendarInterval": [
                {"Hour": 9, "Minute": 0},
                {"Hour": 18, "Minute": 0},
            ]
        }
        assert scanner.summarize_schedule(data) == "daily 09:00 +1"

    def test_run_at_load(self):
        assert scanner.summarize_schedule({"RunAtLoad": True}) == "at-load"

    def test_on_demand(self):
        assert scanner.summarize_schedule({"Label": "x"}) == "on-demand"

    def test_run_at_load_false_is_on_demand(self):
        assert scanner.summarize_schedule({"RunAtLoad": False}) == "on-demand"
