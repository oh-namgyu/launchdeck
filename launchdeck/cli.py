"""Command line entry point for ``ldm``."""

import argparse
import sys
from typing import Callable, Dict, List, Optional, Sequence

from . import __version__, info, lifecycle, logs, merge, output

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

    for name, help_text in LIFECYCLE_HELP:
        action = subparsers.add_parser(name, help=help_text)
        action.add_argument("label", help="the job's Label")
        _add_common_arguments(action)
    return parser


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


def cmd_lifecycle(args: argparse.Namespace) -> int:
    """Run one lifecycle command (start/stop/.../disable) on one job."""
    record = lifecycle.resolve(
        merge.collect(args.directory), args.label, args.directory
    )
    result = lifecycle.ACTIONS[args.command](record)
    text = output.render_action(result, as_json=args.as_json)
    print(text, file=sys.stdout if result.ok or args.as_json else sys.stderr)
    return EXIT_OK if result.ok else EXIT_ERROR


COMMANDS: Dict[str, Callable[[argparse.Namespace], int]] = {
    "status": cmd_status,
    "info": cmd_info,
    "logs": cmd_logs,
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
