"""Command line entry point for ``ldm``."""

import argparse
import sys
from typing import Callable, Dict, List, Optional, Sequence

from . import (
    __version__,
    info,
    lifecycle,
    logs,
    merge,
    output,
    provision,
    removal,
    spec,
)

EXIT_OK = 0
EXIT_ERROR = 1

# Lifecycle subcommands: name -> help text. The launchd mapping behind each one
# lives in lifecycle.py.
LIFECYCLE_HELP = (
    ("start", "run the job now (its schedule is unchanged)"),
    ("stop", "send SIGTERM to the running process; the job stays loaded"),
    ("restart", "stop the running process and run the job again"),
    ("load", "register the job's plist with launchd"),
    ("unload", "unregister the job from launchd; the plist stays on disk"),
    ("enable", "allow the job to be loaded"),
    ("disable", "refuse to load the job until it is enabled again"),
)


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="ldm",
        description="Inspect and manage your personal macOS LaunchAgents.",
    )
    parser.add_argument(
        "--version", action="version", version="launchdeck {0}".format(__version__)
    )
    subparsers = parser.add_subparsers(dest="command")
    _add_read_parsers(subparsers)
    _add_write_parsers(subparsers)
    return parser


def _add_read_parsers(subparsers) -> None:
    """Define the read-only commands: status, info, logs."""
    status = subparsers.add_parser(
        "status", help="list every LaunchAgent with its runtime state"
    )
    _add_common_arguments(status)

    detail = subparsers.add_parser("info", help="show one job in detail")
    detail.add_argument("label", help="the job's Label")
    _add_common_arguments(detail)

    tail = subparsers.add_parser("logs", help="tail a job's stdout and stderr logs")
    tail.add_argument("label", help="the job's Label")
    tail.add_argument(
        "-n",
        "--lines",
        type=int,
        default=logs.DEFAULT_LINES,
        help="lines to show per log (default: {0})".format(logs.DEFAULT_LINES),
    )
    tail.add_argument(
        "-f",
        "--follow",
        action="store_true",
        help="keep printing appended lines until interrupted",
    )
    _add_directory_argument(tail)


def _add_write_parsers(subparsers) -> None:
    """Define the commands that change something: lifecycle plus install family."""
    for name, help_text in LIFECYCLE_HELP:
        action = subparsers.add_parser(name, help=help_text)
        action.add_argument("label", help="the job's Label")
        _add_common_arguments(action)

    _add_install_parser(subparsers)

    remove = subparsers.add_parser(
        "uninstall", help="back up the plist, unload the job and remove it"
    )
    remove.add_argument("label", help="the job's Label")
    _add_common_arguments(remove)

    back = subparsers.add_parser(
        "restore", help="put the newest backup of a job back and load it"
    )
    back.add_argument("label", help="the job's Label")
    back.add_argument(
        "--force", action="store_true", help="replace the plist that is there now"
    )
    _add_common_arguments(back)


def _add_install_parser(subparsers) -> None:
    """Define ``ldm install`` and its plist-building flags."""
    new = subparsers.add_parser("install", help="create a LaunchAgent and load it")
    new.add_argument("--label", required=True, help="the job's Label, e.g. com.you.backup")
    # dest stays "cmd": the top-level parser already uses "command" for the
    # subcommand name, and --cmd would silently overwrite it.
    new.add_argument(
        "--cmd",
        required=True,
        help="the command to run; it is split into ProgramArguments and never "
        "passed to a shell",
    )
    schedule = new.add_mutually_exclusive_group()
    schedule.add_argument("--interval", help="run every 45s / 30m / 2h / 1d")
    schedule.add_argument(
        "--calendar", help='run at a clock time: "09:30", "daily 09:30" or "Mon 09:30"'
    )
    new.add_argument(
        "--log-dir",
        dest="log_dir",
        help="directory for out.log and err.log (default: ~/Library/Logs/<label>)",
    )
    new.add_argument(
        "--run-at-load", dest="run_at_load", action="store_true", help="set RunAtLoad"
    )
    new.add_argument(
        "--keepalive", action="store_true", help="set KeepAlive (launchd restarts it)"
    )
    new.add_argument(
        "--force", action="store_true", help="replace an existing job with this label"
    )
    _add_common_arguments(new)


def _add_directory_argument(parser: argparse.ArgumentParser) -> None:
    """Add the LaunchAgents directory override."""
    parser.add_argument(
        "--dir",
        dest="directory",
        default=None,
        help="LaunchAgents directory to scan (default: ~/Library/LaunchAgents)",
    )


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Add flags shared by every read-only command."""
    parser.add_argument(
        "--json", action="store_true", dest="as_json", help="emit JSON (schema v1)"
    )
    _add_directory_argument(parser)


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
