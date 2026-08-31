"""Doctor checks: a positive and a negative case for each of the seven rules.

Every check runs against a temporary LaunchAgents directory and a fake runner,
so neither launchctl nor plutil is ever spawned.
"""

from launchdeck import doctor, scanner
from launchdeck.findings import SEVERITY_INFO, SEVERITY_WARN

from .clinic import clean, clinic, clinic_runner, records_of, subjects  # noqa: F401
from .conftest import write_plist


# --- check 1: leftover clutter ------------------------------------------------


def test_clutter_reports_every_non_plist_file(clinic):
    found = doctor.check_clutter(str(clinic))
    assert len(found) == 2
    assert {f.severity for f in found} == {SEVERITY_INFO}
    assert all(f.check == doctor.CHECK_CLUTTER for f in found)
    assert any(f.subject.endswith("com.example.ok.plist.bak") for f in found)
    assert any(f.subject.endswith("notes.txt") for f in found)


def test_clutter_suggests_removing_the_file(clinic):
    assert "delete it" in doctor.check_clutter(str(clinic))[0].suggestion


def test_clutter_is_silent_on_a_tidy_directory(clean):
    assert doctor.check_clutter(str(clean)) == []


# --- check 2: unparseable plists ---------------------------------------------


def test_lenient_plist_is_reported_as_valid_for_launchd(clinic):
    records, _runtime = records_of(clinic)
    found = doctor.check_plists(records, clinic_runner())
    lenient = [f for f in found if f.subject.endswith("lenient.plist")]
    assert len(lenient) == 1
    assert lenient[0].severity == SEVERITY_INFO
    assert "valid for launchd but not strict XML" in lenient[0].message
    # The parser's own reason is carried through to the user.
    assert "not well-formed" in lenient[0].message
    assert "plutil -convert xml1" in lenient[0].suggestion


def test_plist_plutil_also_rejects_is_reported_as_corrupt(clinic):
    records, _runtime = records_of(clinic)
    found = doctor.check_plists(records, clinic_runner())
    corrupt = [f for f in found if f.subject.endswith("corrupt.plist")]
    assert len(corrupt) == 1
    assert corrupt[0].severity == SEVERITY_WARN
    assert "corrupt plist" in corrupt[0].message
    assert "Unexpected character x" in corrupt[0].message


def test_plist_check_without_plutil_still_warns(clinic):
    records, _runtime = records_of(clinic)
    found = doctor.check_plists(records, clinic_runner(plutil_missing=True))
    assert {f.severity for f in found} == {SEVERITY_WARN}
    assert all("plutil is not available" in f.message for f in found)


def test_plist_check_is_silent_when_everything_parses(clean):
    records, _runtime = records_of(clean)
    assert doctor.check_plists(records, clinic_runner()) == []


# --- check 3: broken program paths -------------------------------------------


def test_missing_absolute_program_is_a_warning(clinic):
    records, _runtime = records_of(clinic)
    gone = [f for f in doctor.check_programs(records) if f.subject == "com.example.gone"]
    assert len(gone) == 1
    assert gone[0].severity == SEVERITY_WARN
    assert "program not found on disk" in gone[0].message
    assert "the job will fail to launch" in gone[0].message


def test_bare_command_not_on_path_is_a_warning(clinic):
    records, _runtime = records_of(clinic)
    found = doctor.check_programs(records)
    nocmd = [f for f in found if f.subject == "com.example.nocmd"]
    assert len(nocmd) == 1
    assert "is not on your PATH" in nocmd[0].message
    assert "absolute path" in nocmd[0].suggestion


def test_existing_program_is_not_reported(clinic):
    records, _runtime = records_of(clinic)
    reported = subjects(doctor.check_programs(records))
    assert "com.example.ok" not in reported
    assert "com.example.failing" not in reported


def test_bare_command_on_path_is_not_reported(tmp_path):
    write_plist(
        tmp_path, "com.example.sh.plist", {"Label": "com.example.sh", "Program": "sh"}
    )
    assert doctor.check_programs(scanner.scan(str(tmp_path))) == []


def test_job_without_a_program_is_not_reported(tmp_path):
    write_plist(tmp_path, "com.example.bare.plist", {"Label": "com.example.bare"})
    assert doctor.check_programs(scanner.scan(str(tmp_path))) == []


# --- check 4: failing jobs ----------------------------------------------------


def test_non_zero_exit_is_a_warning_naming_the_code(clinic):
    records, _runtime = records_of(clinic)
    found = doctor.check_exits(records)
    failing = [f for f in found if f.subject == "com.example.failing"]
    assert len(failing) == 1
    assert failing[0].severity == SEVERITY_WARN
    assert "last run exited with code 28" in failing[0].message
    assert "ldm logs com.example.failing" in failing[0].suggestion


def test_sigterm_exit_is_only_a_notice(clinic):
    records, _runtime = records_of(clinic)
    found = doctor.check_exits(records)
    stopped = [f for f in found if f.subject == "com.example.stopped"]
    assert len(stopped) == 1
    assert stopped[0].severity == SEVERITY_INFO
    assert stopped[0].message == (
        "terminated by SIGTERM (possibly a deliberate stop/restart)"
    )


def test_other_signals_stay_warnings(clinic):
    records, _runtime = records_of(clinic)
    found = doctor.check_exits(records)
    killed = [f for f in found if f.subject == "com.example.killed"]
    assert len(killed) == 1
    assert killed[0].severity == SEVERITY_WARN
    assert "terminated by SIGKILL (exit -9)" in killed[0].message


def test_unknown_signal_number_falls_back_to_a_plain_name():
    severity, message, _suggestion = doctor._exit_detail(-999, "com.example.x")
    assert severity == SEVERITY_WARN
    assert "signal 999" in message


def test_clean_and_unloaded_exits_are_not_reported(clinic):
    records, _runtime = records_of(clinic)
    reported = subjects(doctor.check_exits(records))
    assert "com.example.ok" not in reported  # exit 0
    assert "com.example.sleeping" not in reported  # never ran


# --- check 5: unloaded plists -------------------------------------------------


def test_unloaded_plist_is_a_notice(clinic):
    records, _runtime = records_of(clinic)
    found = doctor.check_unloaded(records)
    assert [f.subject for f in found] == ["com.example.sleeping"]
    assert found[0].severity == SEVERITY_INFO
    assert "ldm load com.example.sleeping" in found[0].suggestion


def test_loaded_jobs_are_not_reported_as_unloaded(clinic):
    records, _runtime = records_of(clinic)
    assert "com.example.ok" not in subjects(doctor.check_unloaded(records))


def test_unparseable_plists_are_not_reported_as_unloaded(clinic):
    """Their runtime state is unknown, so calling them unloaded would be a guess."""
    records, _runtime = records_of(clinic)
    reported = subjects(doctor.check_unloaded(records))
    assert "com.example.lenient" not in reported
    assert "com.example.corrupt" not in reported


# --- check 6: foreign loads ---------------------------------------------------


def test_foreign_load_is_an_informational_notice(clinic):
    records, runtime = records_of(clinic)
    found = doctor.check_foreign(records, runtime)
    assert [f.subject for f in found] == ["com.other.tool"]
    assert found[0].severity == SEVERITY_INFO
    assert "loaded from outside your LaunchAgents folder" in found[0].message


def test_foreign_check_never_suggests_removal(clinic):
    records, runtime = records_of(clinic)
    suggestion = doctor.check_foreign(records, runtime)[0].suggestion
    assert "no action needed" in suggestion
    for word in ("remove", "delete", "uninstall"):
        assert word not in suggestion


def test_apple_and_application_labels_are_excluded(clinic):
    records, runtime = records_of(clinic)
    reported = subjects(doctor.check_foreign(records, runtime))
    assert not any(label.startswith("com.apple.") for label in reported)
    assert not any(label.startswith("application.") for label in reported)


def test_labels_with_a_plist_of_ours_are_excluded(clinic):
    records, runtime = records_of(clinic)
    reported = subjects(doctor.check_foreign(records, runtime))
    assert "com.example.ok" not in reported
    # An unreadable plist still claims its label, so it is not a ghost either.
    assert "com.example.lenient" not in reported


# --- check 7: log bloat -------------------------------------------------------


def test_large_log_file_is_reported_with_its_size(clinic):
    records, _runtime = records_of(clinic)
    found = doctor.check_logs(records)
    assert [f.subject for f in found] == ["com.example.noisy"]
    assert found[0].severity == SEVERITY_INFO
    assert "stdout log is 11.0 MB" in found[0].message


def test_small_missing_and_unset_logs_are_not_reported(clinic, tmp_path):
    records, _runtime = records_of(clinic)
    assert all("stderr" not in f.message for f in doctor.check_logs(records))
    write_plist(
        tmp_path,
        "com.example.absent.plist",
        {
            "Label": "com.example.absent",
            "Program": "/bin/sh",
            "StandardOutPath": str(tmp_path / "never-written.log"),
        },
    )
    assert doctor.check_logs(scanner.scan(str(tmp_path))) == []


def test_log_exactly_at_the_limit_is_not_reported(tmp_path):
    log = tmp_path / "exact.log"
    with open(str(log), "wb") as handle:
        handle.truncate(doctor.LOG_SIZE_LIMIT)
    agents = tmp_path / "agents"
    agents.mkdir()
    write_plist(
        agents,
        "com.example.edge.plist",
        {
            "Label": "com.example.edge",
            "Program": "/bin/sh",
            "StandardOutPath": str(log),
        },
    )
    assert doctor.check_logs(scanner.scan(str(agents))) == []
