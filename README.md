# launchdeck

`launchdeck` is a zero-dependency Python CLI (`ldm`) that replaces the awkward
`launchctl` interface for personal macOS LaunchAgents. It reads the plists in
`~/Library/LaunchAgents`, overlays live state from `launchctl list`, and shows
one table telling you what is running, idle, failing, or not loaded at all.

> Work in progress. Inspection (`status`, `info`, `logs`) and the lifecycle
> verbs are here. `install`/`uninstall` and `doctor` land in later stages, and
> the full README arrives with them.

```console
$ ldm status                  # one table: running / idle / failing / unloaded
$ ldm status --json           # schema v1, for scripting
$ ldm info com.example.job    # command line, schedule, log files, launchctl print
$ ldm logs com.example.job    # last 20 lines of stdout and stderr
$ ldm logs com.example.job -n 50 -f   # more lines, then follow like tail -f
```

Lifecycle verbs, each mapping to exactly one `launchctl` operation so nothing
happens behind your back:

| command | launchctl | what it does |
| --- | --- | --- |
| `ldm start <label>` | `kickstart` | run the job now; the schedule is untouched |
| `ldm stop <label>` | `kill SIGTERM` | signal the running process; the job stays loaded |
| `ldm restart <label>` | `kickstart -k` | kill the process, then run it again |
| `ldm load <label>` | `bootstrap` | register the plist with launchd |
| `ldm unload <label>` | `bootout` | unregister the job; the plist stays on disk |
| `ldm enable <label>` | `enable` | allow the job to be loaded |
| `ldm disable <label>` | `disable` | refuse to load the job until it is enabled |

`enable`/`disable` control whether a job **can be loaded at all** - a disabled
job makes `ldm load` fail - not whether it starts at boot. Stopping a job that
sets `KeepAlive` prints a warning, because launchd will start it right back up;
`ldm unload` is what keeps it down. Every verb takes a label, only labels found
in `~/Library/LaunchAgents` are accepted, and no-ops (stopping something that
is not running, loading something already loaded) exit 0.

Requires Python >= 3.9 and macOS. Verified on macOS 15 (Darwin 24).

MIT licensed.
