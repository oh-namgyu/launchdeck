"""Read-only access to a job's StandardOutPath / StandardErrorPath.

Log files are opened for reading only; this module never creates, truncates or
writes a log. ``follow`` is a plain polling loop so the package stays
dependency free.
"""

import os
import sys
import time
from typing import Dict, List, Optional, Sequence, TextIO, Tuple

from .model import JobRecord

DEFAULT_LINES = 20
POLL_SECONDS = 0.5
_CHUNK = 8192

# (stream name, path or None when the plist does not declare it)
Stream = Tuple[str, Optional[str]]


def _expand(path: Optional[str]) -> Optional[str]:
    """Expand ``~`` in a plist-declared path; keep None as None."""
    return os.path.expanduser(path) if path else None


def resolve_log_paths(record: JobRecord) -> List[Stream]:
    """Return both streams of a job, in ``stdout, stderr`` order."""
    return [
        ("stdout", _expand(record.stdout_path)),
        ("stderr", _expand(record.stderr_path)),
    ]


def declared(streams: Sequence[Stream]) -> List[Tuple[str, str]]:
    """Keep only the streams the plist actually declares a path for."""
    return [(name, path) for name, path in streams if path]


def follow_targets(streams: Sequence[Stream]) -> List[Tuple[str, str]]:
    """Declared streams, de-duplicated: stdout and stderr often share a file."""
    seen = set()
    targets: List[Tuple[str, str]] = []
    for name, path in declared(streams):
        if path not in seen:
            seen.add(path)
            targets.append((name, path))
    return targets


def tail_lines(path: str, count: int = DEFAULT_LINES) -> List[str]:
    """Return the last ``count`` lines of a file, reading only its tail."""
    if count <= 0:
        return []
    with open(path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        remaining = handle.tell()
        data = b""
        while remaining > 0 and data.count(b"\n") <= count:
            block = min(_CHUNK, remaining)
            remaining -= block
            handle.seek(remaining)
            data = handle.read(block) + data
    return data.decode("utf-8", "replace").splitlines()[-count:]


def tail_text(path: str, count: int = DEFAULT_LINES) -> str:
    """Last ``count`` lines of ``path``, or a plain note when unavailable."""
    try:
        lines = tail_lines(path, count)
    except FileNotFoundError:
        return "(file does not exist yet)"
    except OSError as exc:
        return "(unreadable: {0})".format(exc.strerror or exc)
    return "\n".join(lines) if lines else "(empty)"


def read_appended(path: str, offset: int) -> Tuple[str, int]:
    """Read whatever was appended past ``offset``; return (text, new offset).

    A file that shrank was rotated or truncated, so reading restarts at 0. A
    file that is missing right now yields no text and keeps the offset.
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return "", offset
    if size < offset:
        offset = 0
    if size == offset:
        return "", offset
    try:
        with open(path, "rb") as handle:
            handle.seek(offset)
            chunk = handle.read(size - offset)
    except OSError:
        return "", offset
    return chunk.decode("utf-8", "replace"), offset + len(chunk)


def _initial_offset(path: str) -> int:
    """Start following at the end of the file, like ``tail -f``."""
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def follow(
    targets: Sequence[Tuple[str, str]],
    stream: Optional[TextIO] = None,
    poll: float = POLL_SECONDS,
    iterations: Optional[int] = None,
    offsets: Optional[Dict[str, int]] = None,
) -> None:
    """Poll the given log files and print appended lines until interrupted.

    ``offsets`` sets where reading starts per path and defaults to the end of
    each file, like ``tail -f``. ``iterations`` bounds the loop; production
    callers leave it None and stop with Ctrl-C.
    """
    out = stream or sys.stdout
    if offsets is None:
        offsets = {path: _initial_offset(path) for _name, path in targets}
    prefixed = len(targets) > 1
    count = 0
    while iterations is None or count < iterations:
        count += 1
        for name, path in targets:
            text, offsets[path] = read_appended(path, offsets[path])
            if not text:
                continue
            for line in text.splitlines():
                out.write("[{0}] {1}\n".format(name, line) if prefixed else line + "\n")
            out.flush()
        if iterations is None or count < iterations:
            time.sleep(poll)
