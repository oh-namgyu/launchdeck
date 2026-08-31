"""Argument parsing for ``ldm``: every subcommand and flag lives here.

Split out of ``cli`` so the command implementations stay readable; ``cli``
owns what the commands do, this module owns how they are spelled.
"""

import argparse

from . import __version__, logs

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
    """Define the read-only commands: status, info, logs, doctor."""
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

    check = subparsers.add_parser(
        "doctor",
        help="check your LaunchAgents for common problems (read-only)",
        description="Check your LaunchAgents for common problems. Read-only: "
        "doctor reports what it finds and changes nothing.",
    )
    check.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when anything is reported as a warning",
    )
    _add_common_arguments(check)


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
