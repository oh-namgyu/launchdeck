# Security Policy

## Supported versions

`launchdeck` is pre-1.0. Only the latest release receives fixes.

| Version | Supported |
| --- | --- |
| 0.1.x | yes |
| < 0.1 | no |

## Reporting a vulnerability

Please report privately through
[GitHub Security Advisories](https://github.com/oh-namgyu/launchdeck/security/advisories/new)
so a fix can ship before the details are public. For anything that is not
sensitive, a regular
[issue](https://github.com/oh-namgyu/launchdeck/issues) is fine.

Include the macOS and Python versions, the command you ran, and what happened.
Expect an initial reply within about a week; this is a personal project, not a
staffed one.

## Threat model

`launchdeck` is a local CLI that manages the LaunchAgents of the user running
it. It has no network code, no server, no telemetry, no configuration file and
no dependencies beyond the Python standard library.

**It runs as you, and only as you.** Every `launchctl` call targets the
`gui/$UID` domain of the invoking user. The tool never calls `sudo`, never
elevates, and never writes outside the user's own LaunchAgents directory and
backup store. The system domain and `/Library/LaunchDaemons` are out of scope
entirely — there is no write path to them. If you are not root, nothing
`launchdeck` does can become root.

**It never executes plist contents.** Plists are parsed as data with
`plistlib` and their values are only ever displayed, compared, or written back.
The `--cmd` string given to `ldm install` is split with `shlex` into
`ProgramArguments` and stored; launchd, later and independently, is what runs
it. No shell is invoked anywhere in the codebase: every subprocess is an argv
list with `shell=False`, and the only two binaries ever executed are
`/bin/launchctl` and `/usr/bin/plutil`, both by absolute path from a single
module (`launchdeck/adapter.py`).

**Path-normalization rails.** Lifecycle commands accept a label, never a path.
The plist a label resolves to must `os.path.realpath` to a file inside the
scanned LaunchAgents directory, so a symlink planted in that directory cannot
be used to make `launchdeck` operate on a file elsewhere. `install` and
`restore` apply the same check to the path they are about to write, and both
refuse the `com.apple.*` namespace so a typo cannot shadow a system agent.
Labels are validated against `[A-Za-z0-9][A-Za-z0-9.-]*`, which is stricter
than launchd requires, because the label also becomes a file name.

**Destructive operations back up first.** `uninstall` copies the plist into
`~/.local/share/ldm/backups/<UTC>/` before unloading anything, verifies launchd
released the job, and only then deletes. Failures roll back both the file and
its load state. Backups are plain copies of files you already own, written with
your umask; they are not encrypted, so treat them like the plists themselves.

**Log reading is read-only.** `ldm logs` opens the paths a plist declares for
reading and never writes to them. `ldm doctor` only `stat`s them.

### Out of scope

- Anything requiring root, and any protection against a user who already has
  root or can write to your `~/Library/LaunchAgents` directory — at that point
  the attacker can install a LaunchAgent directly and does not need this tool.
- The behaviour of the jobs you schedule. `launchdeck` writes a plist; what the
  program in it does is yours.
- macOS or `launchctl` bugs. Please report those to Apple.
