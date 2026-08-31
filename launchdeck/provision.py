"""``ldm install`` and ``ldm restore`` - the two commands that create a plist.

Both follow the same fixed order (plan section 2): make room for the file
(refusing to clobber anything unless ``--force``, which uninstalls the old job
through the backup-first transaction first), write a temp file beside the
target, validate it with ``plutil -lint``, ``os.replace`` it into place and
bootstrap it. Any failure after that point removes the new plist and puts the
displaced job back, load state included.
"""

import os
import plistlib
from typing import List, Optional, Tuple

from . import adapter, backups, removal, spec, transaction
from .model import ActionResult


def _prepare_logs(data) -> Optional[str]:
    """Create the directories the plist's log paths point into."""
    for key in ("StandardOutPath", "StandardErrorPath"):
        directory = os.path.dirname(data.get(key) or "")
        if not directory:
            continue
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            return "cannot create the log directory {0}: {1}".format(directory, exc)
    return None


def _refuse(action: str, label: str, path: str, old_path: Optional[str]) -> ActionResult:
    """Explain that something is already there and how to replace it."""
    if old_path is None:
        return transaction.result(
            action,
            label,
            ok=False,
            lines=[
                "{0} exists but is not a readable plist".format(path),
                "inspect and remove it by hand, then run this again",
            ],
        )
    return transaction.result(
        action,
        label,
        ok=False,
        lines=[
            "{0} is already installed at {1}".format(label, old_path),
            "re-run with --force to replace it (the old plist is backed up first)",
        ],
        plist_path=old_path,
    )


def _clear_conflict(
    action: str,
    label: str,
    path: str,
    directory: Optional[str],
    force: bool,
    runner: Optional[adapter.Runner],
    uid: Optional[int],
    backup_root: Optional[str],
) -> Tuple[Optional[transaction.Replaced], Optional[ActionResult]]:
    """Make room for a new plist. Returns (replaced, failure); both may be None."""
    old = transaction.installed(label, path, directory, runner)
    if old is None:
        if not os.path.lexists(path):
            return None, None
        return None, _refuse(action, label, path, None)
    if not force:
        return None, _refuse(action, label, path, old.plist_path)

    removed = removal.uninstall(old, runner, uid, backup_root)
    if not removed.ok:
        return None, transaction.result(
            action,
            label,
            ok=False,
            lines=["cannot replace the installed {0}:".format(label)] + removed.lines,
        )
    return (
        transaction.Replaced(
            label=old.label,
            path=old.plist_path,
            backup=removed.details["backup_path"],
            was_loaded=old.loaded,
        ),
        None,
    )


def _summary(label: str, path: str, data, replaced) -> List[str]:
    """The success message of ``install``."""
    lines = ["installed {0} at {1}".format(label, path)]
    if replaced is not None:
        lines.append("replaced the previous plist (backup: {0})".format(replaced.backup))
    lines.append("command: {0}".format(" ".join(data["ProgramArguments"])))
    lines.append("logs: {0}".format(os.path.dirname(data["StandardOutPath"])))
    lines.append("loaded it with launchd")
    return lines


def install(
    job: spec.JobSpec,
    runner: Optional[adapter.Runner] = None,
    uid: Optional[int] = None,
    directory: Optional[str] = None,
    force: bool = False,
    backup_root: Optional[str] = None,
) -> ActionResult:
    """Create a LaunchAgent plist and load it, atomically."""
    try:
        data = spec.build(job)
        path = transaction.target_path(job.label, directory)
    except ValueError as exc:
        return transaction.result("install", job.label, ok=False, lines=[str(exc)])

    replaced, failure = _clear_conflict(
        "install", job.label, path, directory, force, runner, uid, backup_root
    )
    if failure is not None:
        return failure

    problem = _prepare_logs(data)
    if problem:
        return transaction.result(
            "install",
            job.label,
            ok=False,
            lines=[problem] + transaction.undo(replaced, runner, uid),
        )

    return transaction.commit(
        "install",
        job.label,
        path,
        plistlib.dumps(data, fmt=plistlib.FMT_XML),
        replaced,
        runner,
        uid,
        _summary(job.label, path, data, replaced),
    )


def _backup_payload(label: str, backup_root: Optional[str]):
    """Read the newest backup of ``label``: returns (path, bytes, failure)."""
    backup = backups.newest(label, backup_root)
    if backup is None:
        return None, None, transaction.result(
            "restore",
            label,
            ok=False,
            lines=[
                "no backup of {0} found under {1}".format(
                    label, backups.root(backup_root)
                )
            ],
        )
    try:
        with open(backup, "rb") as handle:
            return backup, handle.read(), None
    except OSError as exc:
        return backup, None, transaction.result(
            "restore",
            label,
            ok=False,
            lines=["cannot read the backup {0}: {1}".format(backup, exc)],
        )


def restore(
    label: str,
    runner: Optional[adapter.Runner] = None,
    uid: Optional[int] = None,
    directory: Optional[str] = None,
    force: bool = False,
    backup_root: Optional[str] = None,
) -> ActionResult:
    """Copy the newest backup of ``label`` back into place and load it."""
    try:
        spec.validate_label(label)
        path = transaction.target_path(label, directory)
    except ValueError as exc:
        return transaction.result("restore", label, ok=False, lines=[str(exc)])

    backup, payload, failure = _backup_payload(label, backup_root)
    if failure is not None:
        return failure

    replaced, failure = _clear_conflict(
        "restore", label, path, directory, force, runner, uid, backup_root
    )
    if failure is not None:
        return failure

    lines = [
        "restored {0} to {1}".format(label, path),
        "from backup {0}".format(backup),
    ]
    if replaced is not None:
        lines.append(
            "replaced the plist that was there (backup: {0})".format(replaced.backup)
        )
    lines.append("loaded it with launchd")
    return transaction.commit(
        "restore", label, path, payload, replaced, runner, uid, lines
    )
