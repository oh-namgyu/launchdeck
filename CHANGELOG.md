# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-08-31

Initial release. A zero-dependency CLI (`ldm`) for personal macOS LaunchAgents,
covering inspection, lifecycle, provisioning and health checks.

### Added

**Inspection (read-only)**

- `ldm status` — every LaunchAgent in one table: state, pid, last exit code,
  schedule summary and plist path. Merges a `~/Library/LaunchAgents` plist scan
  with runtime state from `launchctl list`. Bare `ldm` is shorthand for it.
- `ldm info <label>` — one job in detail: command line, schedule keys, log file
  paths with existence and size, and an excerpt of `launchctl print`.
- `ldm logs <label>` — tails the stdout and stderr paths the plist declares.
  `-n` sets the line count, `-f` follows.
- `ldm doctor` — seven read-only checks: leftover non-plist files, unreadable
  plists (cross-checked with `plutil -lint`), missing programs, unclean last
  exits, unloaded plists, foreign loaded labels, and oversized logs. `--strict`
  exits 1 on any warning.

**Lifecycle**

- `ldm start` / `stop` / `restart` — `kickstart`, `kill SIGTERM`, `kickstart -k`.
- `ldm load` / `unload` — `bootstrap` and `bootout`.
- `ldm enable` / `disable` — toggles whether launchd will bootstrap the job,
  with output that says so rather than implying autostart.

**Provisioning**

- `ldm install` — builds and loads a plist from flags (`--label`, `--cmd`,
  `--interval`, `--calendar`, `--log-dir`, `--run-at-load`, `--keepalive`,
  `--force`). Atomic: temp file, `plutil -lint`, `os.replace`, `bootstrap`,
  with rollback on any failure.
- `ldm uninstall` — backup-first removal: copy, `bootout`, verify, delete, with
  rollback of both file and load state. `LDM_BACKUP_DIR` relocates the store.
- `ldm restore` — puts the newest backup of a label back and loads it.

**Other**

- `--json` on every command except `logs`, emitting the v1 schema
  (`{"schema": 1, ...}`).
- `--dir` on every command, to operate on a LaunchAgents directory other than
  `~/Library/LaunchAgents`.
- Colored TTY output honouring `NO_COLOR`.
- 312 unit tests that never invoke `launchctl`.

[0.1.0]: https://github.com/oh-namgyu/launchdeck/releases/tag/v0.1.0
