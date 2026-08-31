# launchdeck

`launchdeck` is a zero-dependency Python CLI (`ldm`) that replaces the awkward
`launchctl` interface for personal macOS LaunchAgents. It reads the plists in
`~/Library/LaunchAgents`, overlays live state from `launchctl list`, and shows
one table telling you what is running, idle, failing, or not loaded at all.

> Work in progress. Stage 1 ships `ldm status` (read-only). Lifecycle,
> install/uninstall, logs, and `doctor` land in later stages, and the full
> README arrives with them.

```console
$ ldm status
$ ldm status --json
```

Requires Python >= 3.9 and macOS. Verified on macOS 15 (Darwin 24).

MIT licensed.
