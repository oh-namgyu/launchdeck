"""Command line entry point for ``ldm``."""

import argparse
import sys
from typing import List, Optional, Sequence

from . import __version__, merge, output

EXIT_OK = 0
EXIT_ERROR = 1


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
    return parser


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Add flags shared by every read-only command."""
    parser.add_argument(
        "--json", action="store_true", dest="as_json", help="emit JSON (schema v1)"
    )
    parser.add_argument(
        "--dir",
        dest="directory",
        default=None,
        help="LaunchAgents directory to scan (default: ~/Library/LaunchAgents)",
    )


def cmd_status(args: argparse.Namespace) -> int:
    """Run the ``status`` command."""
    records = merge.collect(args.directory)
    text = output.render_status(records, as_json=args.as_json)
    print(text)
    return EXIT_OK


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
        return cmd_status(args)
    except KeyboardInterrupt:
        return EXIT_ERROR
    except Exception as exc:  # never dump a traceback at a user
        print("ldm: {0}".format(exc), file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
