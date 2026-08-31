"""Where ``uninstall`` puts a plist before deleting it, and where ``restore``
looks for it.

Layout: ``<root>/<UTC timestamp>/<label>.plist``. The root is
``~/.local/share/ldm/backups`` unless ``LDM_BACKUP_DIR`` overrides it, which is
how the test suite keeps every byte it writes inside a temporary directory.
"""

import datetime
import os
import shutil
from typing import List, Optional

ENV_VAR = "LDM_BACKUP_DIR"
DEFAULT_ROOT = "~/.local/share/ldm/backups"
TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"


def root(path: Optional[str] = None) -> str:
    """Resolve the backup root: argument, then ``LDM_BACKUP_DIR``, then default."""
    chosen = path or os.environ.get(ENV_VAR) or DEFAULT_ROOT
    return os.path.abspath(os.path.expanduser(chosen))


def _slot(base: str) -> str:
    """Pick a fresh timestamped directory, so a same-second backup never clashes."""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime(TIMESTAMP_FORMAT)
    candidate = os.path.join(base, stamp)
    index = 1
    while os.path.exists(candidate):
        candidate = os.path.join(base, "{0}-{1}".format(stamp, index))
        index += 1
    return candidate


def save(label: str, plist_path: str, path: Optional[str] = None) -> str:
    """Copy a plist into a new backup slot and return the copy's path."""
    slot = _slot(root(path))
    os.makedirs(slot, exist_ok=True)
    destination = os.path.join(slot, "{0}.plist".format(label))
    shutil.copy2(plist_path, destination)
    return destination


def find(label: str, path: Optional[str] = None) -> List[str]:
    """List every backup of ``label``, oldest first (slot names sort by time)."""
    base = root(path)
    try:
        slots = sorted(os.listdir(base))
    except OSError:
        return []
    name = "{0}.plist".format(label)
    found = [os.path.join(base, slot, name) for slot in slots]
    return [candidate for candidate in found if os.path.isfile(candidate)]


def newest(label: str, path: Optional[str] = None) -> Optional[str]:
    """The most recent backup of ``label``, or None when there is none."""
    candidates = find(label, path)
    return candidates[-1] if candidates else None
