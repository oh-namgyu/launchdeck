# launchdeck

`launchdeck` is a zero-dependency Python CLI (`ldm`) that replaces the awkward
`launchctl` interface for personal macOS LaunchAgents. It reads the plists in
`~/Library/LaunchAgents`, overlays live state from `launchctl list`, and shows
one table telling you what is running, idle, failing, or not loaded at all.

> Work in progress. Inspection (`status`, `info`, `logs`), the lifecycle verbs
> and `install`/`uninstall`/`restore` are here. `doctor` lands in the next
> stage, and the full README arrives with it.

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

## Creating and removing jobs

```console
$ ldm install --label com.you.backup --cmd "/usr/bin/rsync -a ~/src /Volumes/bk" \
      --interval 2h
$ ldm install --label com.you.report --cmd "/bin/sh ~/bin/report.sh" \
      --calendar "Mon 09:30" --log-dir ~/logs/report --run-at-load
$ ldm uninstall com.you.backup     # backs the plist up first, then unloads it
$ ldm restore com.you.backup       # newest backup back in place, and loaded
```

`--interval` takes `45s` / `30m` / `2h` / `1d`; `--calendar` takes `"09:30"`,
`"daily 09:30"` or `"Mon 09:30"`. `--cmd` is split into `ProgramArguments` with
`shlex` and handed to launchd as data - no shell ever sees it. Logs default to
`~/Library/Logs/<label>/out.log` and `err.log`.

All three are transactions, so a failure leaves the machine as it was:

- **install** writes a temp file next to the target, validates it with
  `plutil -lint`, moves it into place and bootstraps it. If the lint or the
  bootstrap fails, the new plist is removed again. An existing label is refused
  unless you pass `--force`, which uninstalls the old job first (backup
  included) and puts it back - load state and all - if the new one fails.
- **uninstall** copies the plist to `~/.local/share/ldm/backups/<UTC>/` before
  it unloads the job, verifies launchd let go, and only then deletes the file.
  A failure after the unload restores the file and loads it again. The backup
  path is printed, and `LDM_BACKUP_DIR` moves the store elsewhere.
- **restore** takes the newest backup for a label, refuses to overwrite an
  existing plist without `--force`, and loads what it restored.

One thing `ldm` cannot undo: `launchctl enable`/`disable` writes into a
root-owned override database, and that row survives the job it belongs to.
Uninstalling a disabled label says so in its output - re-install it later and
you will need `ldm enable <label>` before launchd accepts it.

Requires Python >= 3.9 and macOS. Verified on macOS 15 (Darwin 24).

MIT licensed.
