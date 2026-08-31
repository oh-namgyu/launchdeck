"""The doctor report, its rendering, and the ``ldm doctor`` command itself."""

import json

import pytest

from launchdeck import cli, doctor
from launchdeck.findings import SEVERITY_INFO, SEVERITY_WARN, Finding, Report

from .clinic import (  # noqa: F401  (fixtures are used by name)
    CLINIC_NOTICES,
    CLINIC_WARNINGS,
    clean,
    clean_cli,
    clinic,
    clinic_runner,
    doctor_cli,
    empty_cli,
)

FINDING_KEYS = {"check", "severity", "label_or_path", "message", "suggestion"}


def test_run_collects_every_check(clinic):
    report = doctor.run(str(clinic), clinic_runner())
    assert {f.check for f in report.findings} == {n for n, _t in doctor.CHECK_TITLES}
    assert report.warnings == CLINIC_WARNINGS
    assert report.notices == CLINIC_NOTICES


def test_run_on_a_clean_directory_finds_nothing(clean):
    report = doctor.run(str(clean), clinic_runner(loaded={"com.example.ok": (1, 0)}))
    assert report.findings == []
    assert (report.warnings, report.notices, report.subjects) == (0, 0, 0)


def test_run_does_not_modify_the_directory(clinic):
    before = {p.name: p.stat().st_mtime for p in clinic.iterdir()}
    doctor.run(str(clinic), clinic_runner())
    assert {p.name: p.stat().st_mtime for p in clinic.iterdir()} == before


def test_report_counts_distinct_subjects():
    report = Report(
        [
            Finding("exit", SEVERITY_WARN, "a", "m", "s"),
            Finding("program", SEVERITY_WARN, "a", "m", "s"),
            Finding("unloaded", SEVERITY_INFO, "b", "m", "s"),
        ]
    )
    assert (report.warnings, report.notices, report.subjects) == (2, 1, 2)


def test_report_groups_in_check_order(clinic):
    report = doctor.run(str(clinic), clinic_runner())
    titles = [title for title, _findings in report.grouped()]
    assert titles == [title for _name, title in doctor.CHECK_TITLES]


def test_report_grouping_drops_empty_checks():
    report = Report([Finding("exit", SEVERITY_WARN, "a", "m", "s")])
    assert len(report.grouped()) == 1


def test_finding_json_shape():
    payload = Finding("exit", SEVERITY_WARN, "a", "m", "s").to_dict()
    assert set(payload) == FINDING_KEYS
    assert payload["label_or_path"] == "a"


def test_doctor_command_exits_zero_even_with_warnings(clinic, doctor_cli, capsys):
    assert cli.main(["doctor", "--dir", str(clinic)]) == 0
    out = capsys.readouterr().out
    assert "com.example.failing - last run exited with code 28" in out
    assert "warn" in out and "info" in out


def test_doctor_command_prints_every_section_and_a_summary(clinic, doctor_cli, capsys):
    cli.main(["doctor", "--dir", str(clinic)])
    out = capsys.readouterr().out
    for _name, title in doctor.CHECK_TITLES:
        assert "== {0} (".format(title) in out
    assert out.strip().endswith(
        "{0} warnings, {1} notices across 12 jobs".format(
            CLINIC_WARNINGS, CLINIC_NOTICES
        )
    )


def test_doctor_command_reports_a_clean_directory(clean, clean_cli, capsys):
    assert cli.main(["doctor", "--dir", str(clean)]) == 0
    assert capsys.readouterr().out.strip() == "No problems found."


def test_doctor_strict_exits_one_on_warnings(clinic, doctor_cli, capsys):
    assert cli.main(["doctor", "--strict", "--dir", str(clinic)]) == 1
    assert "warnings" in capsys.readouterr().out


def test_doctor_strict_exits_zero_when_only_notices(tmp_path, empty_cli, capsys):
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "leftover.bak").write_text("stale")
    assert cli.main(["doctor", "--strict", "--dir", str(agents)]) == 0
    assert "0 warnings, 1 notice across 1 job" in capsys.readouterr().out


def test_doctor_json_matches_the_contract(clinic, doctor_cli, capsys):
    assert cli.main(["doctor", "--json", "--dir", str(clinic)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == 1
    assert payload["summary"] == {
        "warnings": CLINIC_WARNINGS,
        "notices": CLINIC_NOTICES,
    }
    assert len(payload["findings"]) == CLINIC_WARNINGS + CLINIC_NOTICES
    for finding in payload["findings"]:
        assert set(finding) == FINDING_KEYS
        assert finding["severity"] in (SEVERITY_WARN, SEVERITY_INFO)


def test_doctor_json_is_emitted_under_strict_too(clinic, doctor_cli, capsys):
    assert cli.main(["doctor", "--strict", "--json", "--dir", str(clinic)]) == 1
    assert json.loads(capsys.readouterr().out)["schema"] == 1


def test_doctor_help_mentions_it_is_read_only(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["doctor", "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "Read-only" in out
    assert "--strict" in out
