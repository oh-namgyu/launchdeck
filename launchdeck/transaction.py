"""The primitives the writing commands share: place a file, load it, undo.

``install``, ``uninstall`` and ``restore`` are all transactions, and this is
the part they have in common - an atomic temp-file swap gated by
``plutil -lint``, a bootstrap that cleans up after itself, and the rollback of
a plist that ``--force`` displaced. Every launchctl and plutil call still goes
through ``adapter``; only the file moves live here.
"""

import os
import shutil
import tempfile
from dataclasses import dataclass
from typing import List, Optional

from . import adapter, lifecycle, merge, scanner
from .model import ActionResult, JobRecord


@dataclass
class Replaced:
    """The job ``--force`` displaced, and what it takes to bring it back."""

    label: str
    path: str
    backup: str
    was_loaded: bool


def result(action: str, label: str, ok: bool = True, lines=None, **details) -> ActionResult:
    """Build an ActionResult, folding extra keys into the JSON contract."""
    return ActionResult(
        action=action, label=label, ok=ok, lines=list(lines or []), details=details
    )


def target_path(label: str, directory: Optional[str] = None) -> str:
    """Where a label's plist belongs, refusing anything outside the managed dir."""
    path = os.path.join(scanner.agents_dir(directory), "{0}.plist".format(label))
    if not lifecycle.within_managed_dir(path, directory):
        raise ValueError(
            "refusing to write {0}: it does not resolve inside {1}".format(
                path, scanner.agents_dir(directory)
            )
        )
    return path


def installed(
    label: str,
    path: str,
    directory: Optional[str] = None,
    runner: Optional[adapter.Runner] = None,
) -> Optional[JobRecord]:
    """The job already holding this label or this file, with its load state."""
    for record in merge.collect(directory, runner):
        if record.label == label or record.plist_path == path:
            return record
    return None


def place(path: str, payload: bytes, runner: Optional[adapter.Runner] = None) -> Optional[str]:
    """Write ``payload`` beside ``path``, lint it, then move it into place.

    Returns an error message, or None on success. After a failure nothing is
    left behind: the temp file is gone and ``path`` was never touched.
    """
    handle, temp = tempfile.mkstemp(
        prefix=".ldm-", suffix=".plist", dir=os.path.dirname(path)
    )
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
        code, out, err = adapter.plutil_lint(temp, runner)
        if code != 0:
            said = " ".join((out + " " + err).split())
            return "the plist did not pass plutil -lint: {0}".format(
                said or "plutil exited with status {0}".format(code)
            )
        os.replace(temp, path)
    except OSError as exc:
        return "cannot write {0}: {1}".format(path, exc)
    finally:
        if os.path.exists(temp):
            os.remove(temp)
    return None


def activate(
    label: str,
    path: str,
    runner: Optional[adapter.Runner] = None,
    uid: Optional[int] = None,
) -> List[str]:
    """Bootstrap the plist. On failure remove it and explain; [] means loaded."""
    code, _out, err = adapter.bootstrap(path, runner, uid)
    if code == 0:
        return []
    lines = [
        "launchd refused to load {0}: {1}".format(label, adapter.parse_error(err, code))
    ]
    # macOS reports a disabled job as a plain I/O error, so ask launchd.
    if adapter.says_disabled(err) or adapter.is_disabled(label, runner, uid):
        lines.append(
            "{0} is disabled - run `ldm enable {0}` and try again".format(label)
        )
    try:
        os.remove(path)
        lines.append("rolled back: {0} was removed".format(path))
    except OSError as exc:
        lines.append("warning: could not remove {0}: {1}".format(path, exc))
    return lines


def reload_file(
    label: str,
    path: str,
    runner: Optional[adapter.Runner],
    uid: Optional[int],
) -> str:
    """Bootstrap a plist that was already on disk, and say how it went."""
    code, _out, err = adapter.bootstrap(path, runner, uid)
    if code == 0:
        return "rolled back: loaded {0} again".format(label)
    return "warning: could not load {0} again: {1}".format(
        label, adapter.parse_error(err, code)
    )


def undo(
    replaced: Optional[Replaced],
    runner: Optional[adapter.Runner] = None,
    uid: Optional[int] = None,
) -> List[str]:
    """Put back the job ``--force`` displaced, load state included."""
    if replaced is None:
        return []
    try:
        shutil.copy2(replaced.backup, replaced.path)
    except OSError as exc:
        return [
            "warning: could not restore the previous plist from {0}: {1}".format(
                replaced.backup, exc
            )
        ]
    lines = ["rolled back: restored the previous {0}".format(replaced.path)]
    if replaced.was_loaded:
        lines.append(reload_file(replaced.label, replaced.path, runner, uid))
    return lines


def commit(
    action: str,
    label: str,
    path: str,
    payload: bytes,
    replaced: Optional[Replaced],
    runner: Optional[adapter.Runner],
    uid: Optional[int],
    lines,
) -> ActionResult:
    """Shared tail of install and restore: place the file, then load it."""
    failure = place(path, payload, runner)
    problems = [failure] if failure else activate(label, path, runner, uid)
    if problems:
        return result(action, label, ok=False, lines=problems + undo(replaced, runner, uid))

    details = {"plist_path": path}
    if replaced is not None:
        details["backup_path"] = replaced.backup
    return result(action, label, lines=list(lines), **details)
