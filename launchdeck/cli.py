"""Command line entry point for ``ldm``."""

import argparse
import sys
from typing import Callable, Dict, List, Optional, Sequence

from . import (
    doctor,
    info,
    lifecycle,
    logs,
    merge,
    output,
    provision,
    removal,
    spec,
)
from .arguments import LIFECYCLE_HELP, build_parser

EXIT_OK = 0
EXIT_ERROR = 1


def _job(args: argparse.Namespace):
    """Resolve the requested label to a JobRecord, or raise with suggestions."""
    return info.find_job(merge.collect(args.directory), args.label)


def cmd_status(args: argparse.Namespace) -> int:
    """Run the ``status`` command."""
    records = merge.collect(args.directory)
    text = output.render_status(records, as_json=args.as_json)
    print(text)
    return EXIT_OK


def cmd_info(args: argparse.Namespace) -> int:
    """Run the ``info`` command."""
    detail = info.describe(_job(args))
    print(output.render_info(detail, as_json=args.as_json))
    return EXIT_OK


def cmd_logs(args: argparse.Namespace) -> int:
    """Run the ``logs`` command."""
    record = _job(args)
    streams = logs.resolve_log_paths(record)
    if not logs.declared(streams):
        print(
            "ldm: {0} defines no log paths (the plist sets neither "
            "StandardOutPath nor StandardErrorPath)".format(record.label),
            file=sys.stderr,
        )
        return EXIT_ERROR

    for name, path in streams:
        body = logs.tail_text(path, args.lines) if path else ""
        print(output.render_log_section(name, path, body))
    if args.follow:
        _follow(logs.follow_targets(streams))
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace) -> int:
    """Run the ``doctor`` command.

    A successful scan exits 0 even when it found problems - doctor reports, it
    does not fail builds - unless ``--strict`` asks for the opposite.
    """
    report = doctor.run(args.directory)
    print(output.render_doctor(report, as_json=args.as_json))
    return EXIT_ERROR if args.strict and report.warnings else EXIT_OK


def _follow(targets: Sequence) -> None:
    """Stream appended log lines until the user interrupts."""
    print("\n(following - press Ctrl-C to stop)")
    try:
        logs.follow(targets)
    except KeyboardInterrupt:
        print("")


def _emit(result, as_json: bool) -> int:
    """Print one ActionResult and turn it into an exit code."""
    text = output.render_action(result, as_json=as_json)
    print(text, file=sys.stdout if result.ok or as_json else sys.stderr)
    return EXIT_OK if result.ok else EXIT_ERROR


def cmd_lifecycle(args: argparse.Namespace) -> int:
    """Run one lifecycle command (start/stop/.../disable) on one job."""
    record = lifecycle.resolve(
        merge.collect(args.directory), args.label, args.directory
    )
    return _emit(lifecycle.ACTIONS[args.command](record), args.as_json)


def cmd_install(args: argparse.Namespace) -> int:
    """Run the ``install`` command."""
    job = spec.JobSpec(
        label=args.label,
        command=args.cmd,
        interval=args.interval,
        calendar=args.calendar,
        log_dir=args.log_dir,
        run_at_load=args.run_at_load,
        keep_alive=args.keepalive,
    )
    result = provision.install(job, directory=args.directory, force=args.force)
    return _emit(result, args.as_json)


def cmd_uninstall(args: argparse.Namespace) -> int:
    """Run the ``uninstall`` command."""
    record = lifecycle.resolve(
        merge.collect(args.directory), args.label, args.directory
    )
    return _emit(removal.uninstall(record), args.as_json)


def cmd_restore(args: argparse.Namespace) -> int:
    """Run the ``restore`` command."""
    result = provision.restore(
        args.label, directory=args.directory, force=args.force
    )
    return _emit(result, args.as_json)


COMMANDS: Dict[str, Callable[[argparse.Namespace], int]] = {
    "status": cmd_status,
    "info": cmd_info,
    "logs": cmd_logs,
    "doctor": cmd_doctor,
    "install": cmd_install,
    "uninstall": cmd_uninstall,
    "restore": cmd_restore,
}
COMMANDS.update((name, cmd_lifecycle) for name, _help in LIFECYCLE_HELP)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point. Returns the process exit code."""
    raw: List[str] = list(sys.argv[1:] if argv is None else argv)
    # Bare `ldm` is shorthand for `ldm status`.
    if not raw or raw[0].startswith("-") and raw[0] not in ("--version", "-h", "--help"):
        raw = ["status"] + raw

    parser = build_parser()
    args = parser.parse_args(raw)
    if args.command is None:
        parser.print_help()
        return EXIT_OK

    try:
        return COMMANDS[args.command](args)
    except KeyboardInterrupt:
        return EXIT_ERROR
    except Exception as exc:  # never dump a traceback at a user
        print("ldm: {0}".format(exc), file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
