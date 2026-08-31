"""Lifecycle commands: start, stop, restart, load, unload, enable, disable.

Every launchctl call goes through ``adapter``; this module only decides which
call to make, whether it is even needed, and what to tell the user. The
launchd semantics are fixed (plan section 2):

  start    kickstart      run now, schedule untouched
  stop     kill SIGTERM   signal the running process only
  restart  kickstart -k   kill the process, then run it again
  load     bootstrap      register the plist with launchd
  unload   bootout        unregister the job from launchd
  enable   enable         allow the job to be bootstrapped
  disable  disable        refuse to bootstrap the job until enabled again
"""

import os
from typing import Callable, Dict, Optional

from . import adapter, info, scanner
from .model import ActionResult, JobRecord

# Signalling a process that already exited is a no-op, not a failure.
_NO_SUCH_PROCESS = 3


def within_managed_dir(plist_path: Optional[str], directory: Optional[str] = None) -> bool:
    """True when ``plist_path`` normalizes to a file inside the scanned dir.

    Defense in depth: lifecycle commands take a label, never a path, but a
    symlink inside the directory could still point somewhere else.
    """
    if not plist_path:
        return False
    root = os.path.realpath(scanner.agents_dir(directory))
    target = os.path.realpath(os.path.expanduser(plist_path))
    return target.startswith(root + os.sep)


def resolve(records, label: str, directory: Optional[str] = None) -> JobRecord:
    """Find the job by label and refuse anything outside the scanned dir."""
    record = info.find_job(records, label)
    if not within_managed_dir(record.plist_path, directory):
        raise ValueError(
            "refusing to operate on {0!r}: its plist does not resolve inside "
            "{1}".format(label, scanner.agents_dir(directory))
        )
    return record


def _failed(action: str, record: JobRecord, code: int, stderr: str) -> ActionResult:
    """Build the failure result carrying launchctl's own words."""
    return ActionResult(
        action=action,
        label=record.label,
        ok=False,
        lines=["{0} failed: {1}".format(action, adapter.parse_error(stderr, code))],
    )


def _noop(action: str, record: JobRecord, message: str) -> ActionResult:
    """Build a successful no-op result: the end state already held."""
    return ActionResult(action=action, label=record.label, changed=False, lines=[message])


def _not_loaded(action: str, record: JobRecord) -> ActionResult:
    """Refuse an action that needs launchd to know about the job."""
    return ActionResult(
        action=action,
        label=record.label,
        ok=False,
        lines=[
            "{0} is not loaded, so launchd cannot {1} it".format(record.label, action),
            "run `ldm load {0}` first".format(record.label),
        ],
    )


def start(
    record: JobRecord,
    runner: Optional[adapter.Runner] = None,
    uid: Optional[int] = None,
) -> ActionResult:
    """Run the job now. Its schedule is not changed and not consumed."""
    if not record.loaded:
        return _not_loaded("start", record)
    code, _out, err = adapter.kickstart(record.label, runner, uid)
    if code != 0:
        return _failed("start", record, code, err)
    return ActionResult(
        action="start",
        label=record.label,
        lines=["started {0} now (its schedule is unchanged)".format(record.label)],
    )


def stop(
    record: JobRecord,
    runner: Optional[adapter.Runner] = None,
    uid: Optional[int] = None,
) -> ActionResult:
    """Signal the running process with SIGTERM. The job stays loaded."""
    idle = "{0} is not running, so there is nothing to stop".format(record.label)
    if record.pid is None:
        return _noop("stop", record, idle)

    code, _out, err = adapter.send_signal(record.label, adapter.TERM_SIGNAL, runner, uid)
    if code != 0:
        if adapter.error_code(err) == _NO_SUCH_PROCESS:
            return _noop("stop", record, idle)
        return _failed("stop", record, code, err)

    lines = [
        "sent {0} to {1} (pid {2}); the job stays loaded".format(
            adapter.TERM_SIGNAL, record.label, record.pid
        )
    ]
    if record.keep_alive:
        lines.append(
            "warning: {0} sets KeepAlive, so launchd will start it again - use "
            "`ldm unload {0}` to keep it stopped".format(record.label)
        )
    return ActionResult(action="stop", label=record.label, lines=lines)


def restart(
    record: JobRecord,
    runner: Optional[adapter.Runner] = None,
    uid: Optional[int] = None,
) -> ActionResult:
    """Kill the running process (if any) and run the job again."""
    if not record.loaded:
        return _not_loaded("restart", record)
    code, _out, err = adapter.kickstart(record.label, runner, uid, restart=True)
    if code != 0:
        return _failed("restart", record, code, err)
    return ActionResult(
        action="restart",
        label=record.label,
        lines=["restarted {0} (its schedule is unchanged)".format(record.label)],
    )


def load(
    record: JobRecord,
    runner: Optional[adapter.Runner] = None,
    uid: Optional[int] = None,
) -> ActionResult:
    """Register the job's plist with launchd (bootstrap)."""
    if record.loaded:
        return _noop("load", record, "{0} is already loaded".format(record.label))
    path = record.plist_path
    if not path or not os.path.isfile(path):
        return ActionResult(
            action="load",
            label=record.label,
            ok=False,
            lines=["load failed: no plist file found for {0}".format(record.label)],
        )

    code, _out, err = adapter.bootstrap(path, runner, uid)
    if code != 0:
        result = _failed("load", record, code, err)
        # macOS reports a disabled job as a plain I/O error, so ask launchd.
        if adapter.says_disabled(err) or adapter.is_disabled(record.label, runner, uid):
            result.lines.append(
                "{0} is disabled, which is why launchd refused it - run "
                "`ldm enable {0}` and load it again".format(record.label)
            )
        return result
    return ActionResult(
        action="load",
        label=record.label,
        lines=["loaded {0} from {1}".format(record.label, path)],
    )


def unload(
    record: JobRecord,
    runner: Optional[adapter.Runner] = None,
    uid: Optional[int] = None,
) -> ActionResult:
    """Unregister the job from launchd (bootout). The plist stays on disk."""
    if not record.loaded:
        return _noop("unload", record, "{0} is not loaded".format(record.label))
    code, _out, err = adapter.bootout(record.label, runner, uid)
    if code != 0:
        return _failed("unload", record, code, err)
    return ActionResult(
        action="unload",
        label=record.label,
        lines=["unloaded {0}; its plist is still on disk".format(record.label)],
    )


def _toggle(
    record: JobRecord,
    enabled: bool,
    runner: Optional[adapter.Runner],
    uid: Optional[int],
) -> ActionResult:
    """Shared body of enable/disable, including the semantics note."""
    action = "enable" if enabled else "disable"
    code, _out, err = adapter.set_enabled(record.label, enabled, runner, uid)
    if code != 0:
        return _failed(action, record, code, err)
    if enabled:
        note = "launchd will now accept it - `ldm load {0}` can bootstrap it".format(
            record.label
        )
    else:
        note = (
            "launchd will now refuse to bootstrap it, so `ldm load {0}` fails "
            "until it is enabled again; this does not stop a job that is "
            "already loaded".format(record.label)
        )
    return ActionResult(
        action=action,
        label=record.label,
        lines=["{0}d {1}".format(action, record.label), note],
    )


def enable(
    record: JobRecord,
    runner: Optional[adapter.Runner] = None,
    uid: Optional[int] = None,
) -> ActionResult:
    """Allow the job to be bootstrapped."""
    return _toggle(record, True, runner, uid)


def disable(
    record: JobRecord,
    runner: Optional[adapter.Runner] = None,
    uid: Optional[int] = None,
) -> ActionResult:
    """Refuse to bootstrap the job until it is enabled again."""
    return _toggle(record, False, runner, uid)


Action = Callable[..., ActionResult]

ACTIONS: Dict[str, Action] = {
    "start": start,
    "stop": stop,
    "restart": restart,
    "load": load,
    "unload": unload,
    "enable": enable,
    "disable": disable,
}
