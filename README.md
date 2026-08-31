# launchdeck

`launchdeck` is a zero-dependency Python CLI (`ldm`) that replaces the awkward
`launchctl` interface for personal macOS LaunchAgents. It reads the plists in
`~/Library/LaunchAgents`, overlays live state from `launchctl list`, and shows
one table telling you what is running, idle, failing, or not loaded at all.

> Work in progress. `ldm status`, `ldm info` and `ldm logs` are here and are
> all read-only. Lifecycle, install/uninstall and `doctor` land in later
> stages, and the full README arrives with them.

```console
$ ldm status                  # one table: running / idle / failing / unloaded
$ ldm status --json           # schema v1, for scripting
$ ldm info com.example.job    # command line, schedule, log files, launchctl print
$ ldm logs com.example.job    # last 20 lines of stdout and stderr
$ ldm logs com.example.job -n 50 -f   # more lines, then follow like tail -f
```

Requires Python >= 3.9 and macOS. Verified on macOS 15 (Darwin 24).

MIT licensed.
