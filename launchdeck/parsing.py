"""Pure parsers for launchctl's text output.

Split out of ``adapter`` only for size; conceptually this is the other half of
the launchctl boundary. Nothing here runs a process, so every macOS output
quirk can be pinned down by a test against canned text. Everything is
re-exported from ``adapter``, which stays the single import point.
"""

import re
from typing import Dict, Optional, Set, Tuple

# launchd errno values seen on the failure paths of the lifecycle commands.
# The raw message is always shown; these only add the "why" in parentheses.
ERROR_HINTS = {
    3: "no such process - the job is loaded but nothing is running",
    5: "launchd refused the request; usually the job is already in that state, "
    "or it is disabled",
    36: "operation now in progress",
    37: "operation already in progress",
    112: "no such domain - is a GUI session open for this user?",
    113: "no such service in this domain - the job is not loaded",
    125: "the domain does not support that action",
    133: "the service is disabled",
    150: "operation not permitted",
}

# The handful of ``launchctl print`` fields worth surfacing in ``ldm info``.
PRINT_FIELDS = (
    "state",
    "last exit code",
    "last exit reason",
    "runs",
    "run interval",
    "path",
)

# "Bootstrap failed: 5: Input/output error" -> code 5.
_ERRNO = re.compile(r"(?:^|\s)(\d{1,3}):\s+\S")

# print-disabled rows: `"com.example.job" => disabled` (older: `=> true`).
_DISABLED_ROW = re.compile(r'"([^"]+)"\s*=>\s*(\w+)')
_DISABLED_VALUES = ("disabled", "true")


def _to_int(token: str) -> Optional[int]:
    """Parse a launchctl numeric column; ``-`` and junk become None."""
    token = token.strip()
    if not token or token == "-":
        return None
    try:
        return int(token)
    except ValueError:
        return None


def parse_list_output(text: str) -> Dict[str, Tuple[Optional[int], Optional[int]]]:
    """Parse ``launchctl list`` output into ``{label: (pid, last_exit)}``.

    The output is a header line followed by tab-separated ``PID Status Label``
    rows. A ``-`` in the PID column means the job is loaded but not running.
    Unparsable lines are skipped rather than raising.
    """
    jobs: Dict[str, Tuple[Optional[int], Optional[int]]] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t") if "\t" in line else line.split()
        if len(parts) < 3:
            continue
        pid_token, status_token, label = parts[0], parts[1], parts[2].strip()
        if not label or label == "Label":
            continue
        jobs[label] = (_to_int(pid_token), _to_int(status_token))
    return jobs


def parse_print_output(text: str) -> Dict[str, str]:
    """Pull the ``PRINT_FIELDS`` out of ``launchctl print`` output.

    The output is a nested brace dump of ``key = value`` lines whose exact
    shape varies between macOS releases, so anything unrecognized is ignored
    and only the first occurrence of each known key is kept.
    """
    found: Dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if "=" not in stripped or stripped.endswith("{"):
            continue
        key, _, value = stripped.partition("=")
        key = key.strip().lower()
        if key in PRINT_FIELDS and key not in found:
            found[key] = value.strip()
    return found


def parse_disabled_output(text: str) -> Set[str]:
    """Collect the labels marked disabled in ``launchctl print-disabled``."""
    return {
        label
        for label, value in _DISABLED_ROW.findall(text)
        if value.lower() in _DISABLED_VALUES
    }


def error_code(stderr: str) -> Optional[int]:
    """Pull launchd's errno out of a failure line, e.g. ``... : 5: ...`` -> 5."""
    match = _ERRNO.search(stderr)
    return int(match.group(1)) if match else None


def parse_error(stderr: str, code: int) -> str:
    """Turn a launchctl failure into one readable line, raw text included.

    launchctl says things like ``Boot-out failed: 5: Input/output error``; the
    raw wording is kept (it is what users find in search results) and the errno
    is explained when we know it.
    """
    text = " ".join(stderr.split())
    if not text:
        text = "launchctl exited with status {0}".format(code)
    number = error_code(text)
    hint = ERROR_HINTS.get(number) if number is not None else None
    return "{0} ({1})".format(text, hint) if hint else text


def says_disabled(stderr: str) -> bool:
    """True when launchctl blamed the failure on the job being disabled.

    macOS 15 does not: it answers ``Bootstrap failed: 5: Input/output error``
    for a disabled job, so ``adapter.is_disabled`` is the reliable check and
    this only catches releases that word it explicitly.
    """
    return "disabled" in stderr.lower() or error_code(stderr) == 133
