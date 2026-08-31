"""``ldm uninstall`` - the backup-first removal transaction.

Order is fixed by the plan: copy the plist into the backup directory, bootout
the job, check launchd really let go, and only then delete the file. A failure
after the bootout restores the file and bootstraps it again, so an interrupted
uninstall never leaves a half-removed job behind.
"""

import os
import shutil
from typing import List, Optional, Tuple

from . import adapter, backups, transaction
from .model import ActionResult, JobRecord

ACTION = "uninstall"


def _disabled_note(
    label: str,
    runner: Optional[adapter.Runner],
    uid: Optional[int],
) -> List[str]:
    """Warn that an enable/disable override outlives the job it belongs to."""
    if not adapter.is_disabled(label, runner, uid):
        return []
    return [
        "note: {0} is disabled, and that row lives in launchd's root-owned "
        "override database - uninstall cannot delete it. If you install this "
        "label again, run `ldm enable {0}` first or launchd will refuse "
        "it.".format(label)
    ]


def _unload(
    record: JobRecord,
    backup: str,
    runner: Optional[adapter.Runner],
    uid: Optional[int],
) -> Tuple[bool, Optional[ActionResult]]:
    """Bootout the job and confirm it. Returns (booted_out, failure)."""
    if not record.loaded:
        return False, None

    code, _out, err = adapter.bootout(record.label, runner, uid)
    if code != 0:
        return False, transaction.result(
            ACTION,
            record.label,
            ok=False,
            lines=[
                "could not unload {0}: {1}".format(
                    record.label, adapter.parse_error(err, code)
                ),
                "nothing was removed; the backup is at {0}".format(backup),
            ],
            backup_path=backup,
        )
    if record.label in adapter.launchctl_list(runner):
        return True, transaction.result(
            ACTION,
            record.label,
            ok=False,
            lines=[
                "launchd still lists {0} after bootout".format(record.label),
                "the plist was left in place; the backup is at {0}".format(backup),
            ],
            backup_path=backup,
        )
    return True, None


def _rollback(
    record: JobRecord,
    backup: str,
    booted_out: bool,
    runner: Optional[adapter.Runner],
    uid: Optional[int],
) -> List[str]:
    """Undo a half-finished removal: file back first, then load state."""
    path = record.plist_path or ""
    lines: List[str] = []
    if not os.path.exists(path):
        try:
            shutil.copy2(backup, path)
            lines.append("rolled back: restored {0} from the backup".format(path))
        except OSError as exc:
            return ["warning: could not restore {0}: {1}".format(path, exc)]
    if booted_out:
        lines.append(transaction.reload_file(record.label, path, runner, uid))
    return lines


def uninstall(
    record: JobRecord,
    runner: Optional[adapter.Runner] = None,
    uid: Optional[int] = None,
    backup_root: Optional[str] = None,
) -> ActionResult:
    """Back the plist up, unload the job, then remove the plist."""
    path = record.plist_path
    if not path or not os.path.isfile(path):
        return transaction.result(
            ACTION,
            record.label,
            ok=False,
            lines=["no plist file found for {0}".format(record.label)],
        )
    try:
        backup = backups.save(record.label, path, backup_root)
    except OSError as exc:
        return transaction.result(
            ACTION,
            record.label,
            ok=False,
            lines=["nothing was changed: the backup failed: {0}".format(exc)],
        )

    note = _disabled_note(record.label, runner, uid)
    booted_out, failure = _unload(record, backup, runner, uid)
    if failure is not None:
        return failure

    try:
        os.remove(path)
    except OSError as exc:
        lines = ["could not remove {0}: {1}".format(path, exc)]
        lines.extend(_rollback(record, backup, booted_out, runner, uid))
        return transaction.result(
            ACTION, record.label, ok=False, lines=lines, backup_path=backup
        )

    lines = [
        "uninstalled {0}".format(record.label),
        "removed {0}".format(path),
        "backup: {0}".format(backup),
        "`ldm restore {0}` brings it back".format(record.label),
    ]
    return transaction.result(
        ACTION, record.label, lines=lines + note, backup_path=backup, plist_path=path
    )
