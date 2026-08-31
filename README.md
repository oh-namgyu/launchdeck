# launchdeck

> ## 한국어 요약
>
> `launchdeck` 는 macOS 개인 LaunchAgent 를 관리하는 의존성 0 의 파이썬 CLI (`ldm`) 입니다.
> `~/Library/LaunchAgents` 의 plist 를 읽고 `launchctl list` 의 실행 상태를 덧입혀,
> 내 맥에서 무엇이 돌고 있고 무엇이 죽었는지를 표 하나로 보여줍니다.
> 시작·중지·로그·설치·제거를 사람이 기억할 수 있는 동사로 제공하며, 쓰기 작업은 전부
> 백업 우선 트랜잭션이라 실패하면 원래 상태로 되돌립니다. 아래 본문은 영어입니다.

[![CI](https://github.com/oh-namgyu/launchdeck/actions/workflows/ci.yml/badge.svg)](https://github.com/oh-namgyu/launchdeck/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**A zero-dependency Python CLI for your personal macOS LaunchAgents.**

`ldm` reads the plists in `~/Library/LaunchAgents`, overlays the live state from
`launchctl list`, and prints one table telling you what is running, idle,
failing, or not loaded at all. Then it gives you verbs you can remember for the
things `launchctl` makes you look up every single time.

## Why

`launchctl` is not a bad tool, it is just an unfriendly one. There is no command
that answers "what do I have, and is it working?", the verbs changed in Yosemite
and the old ones still half-work, and the modern ones want a domain target you
have to assemble by hand out of your own uid.

| what you want | launchctl | ldm |
| --- | --- | --- |
| see everything you have | *(no such command)* — `ls ~/Library/LaunchAgents` then `launchctl list \| grep`, by hand | `ldm status` |
| see one job in detail | `launchctl print gui/$(id -u)/com.example.backup` | `ldm info com.example.backup` |
| read a job's output | open the plist, find `StandardOutPath`, `tail` it | `ldm logs com.example.backup` |
| run it right now | `launchctl kickstart gui/$(id -u)/com.example.backup` | `ldm start com.example.backup` |
| stop the running process | `launchctl kill SIGTERM gui/$(id -u)/com.example.backup` | `ldm stop com.example.backup` |
| load a plist | `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.example.backup.plist` | `ldm load com.example.backup` |
| unload it | `launchctl bootout gui/$(id -u)/com.example.backup` | `ldm unload com.example.backup` |
| create a scheduled job | write XML by hand, `plutil -lint`, `bootstrap` | `ldm install --label … --cmd … --interval 2h` |
| find what is broken | *(no such command)* | `ldm doctor` |

Compared to the neighbours: **LaunchControl** is an excellent GUI, but it is a
paid GUI. **lunchy** is a Ruby wrapper around the pre-Yosemite `load`/`unload`
verbs. `launchdeck` is a zero-dependency CLI on the modern `bootstrap`/`bootout`
domain API, and it is the one with a `doctor`.

## Install

```console
$ pipx install launchdeck     # recommended: its own isolated environment
$ pip install launchdeck      # or into an environment you already have
```

From a checkout:

```console
$ git clone https://github.com/oh-namgyu/launchdeck
$ cd launchdeck
$ pip install -e .
```

Requires macOS and Python >= 3.9, and nothing else — the whole tool is the
standard library. Modern macOS does not ship `python3` until you install the
Command Line Tools (`xcode-select --install`), which is where `pipx` also
comes from most easily (`brew install pipx`).

## Quickstart

`ldm` on its own is `ldm status`:

```console
$ ldm status
STATE       LABEL                PID   EXIT  SCHEDULE     PLIST
○ idle      com.example.backup   -     0     every 2h     ~/Library/LaunchAgents/com.example.backup.plist
– unloaded  com.example.cleanup  -     -     daily 03:00  ~/Library/LaunchAgents/com.example.cleanup.plist
✗ failing   com.example.indexer  -     -15   every 15m    ~/Library/LaunchAgents/com.example.indexer.plist
✗ failing   com.example.report   -     1     Mon 09:30    ~/Library/LaunchAgents/com.example.report.plist
● running   com.example.sync     1841  0     keepalive    ~/Library/LaunchAgents/com.example.sync.plist
```

`● running` has a pid, `○ idle` is loaded and waiting for its schedule,
`✗ failing` ended its last run with a non-zero status, `– unloaded` is a plist
launchd does not know about. Colors follow the terminal and respect `NO_COLOR`.

Then look closer:

```console
$ ldm info com.example.backup
label      com.example.backup
state      ○ idle
pid        -
last exit  0
plist      ~/Library/LaunchAgents/com.example.backup.plist
command    /usr/bin/rsync -a ~/src /Volumes/bk
schedule   every 2h  [StartInterval]
stdout     ~/Library/Logs/com.example.backup/out.log (12.4 KB)
stderr     ~/Library/Logs/com.example.backup/err.log (0 B)

launchctl print:
  path            ~/Library/LaunchAgents/com.example.backup.plist
  state           not running
  runs            5
  last exit code  0
  run interval    7200 seconds
```

```console
$ ldm logs com.example.backup          # last 20 lines of each stream
$ ldm logs com.example.backup -n 50 -f # more lines, then follow like tail -f
```

And check the whole folder for problems:

```console
$ ldm doctor
== leftover files in the LaunchAgents directory (1) ==
  info  ~/Library/LaunchAgents/com.example.cleanup.plist.bak - not a .plist, so launchd ignores it
        -> delete it, or move it outside the LaunchAgents directory

== programs that are not where the plist says (2) ==
  warn  com.example.indexer - program not found on disk: /usr/local/bin/indexer; the job will fail to launch
        -> fix ProgramArguments in the plist, or put the program back
  warn  com.example.sync - program not found on disk: ~/bin/sync-notes; the job will fail to launch
        -> fix ProgramArguments in the plist, or put the program back

== jobs whose last run did not end cleanly (2) ==
  info  com.example.indexer - terminated by SIGTERM (possibly a deliberate stop/restart)
        -> nothing to do if you stopped it yourself; otherwise read its output: ldm logs com.example.indexer
  warn  com.example.report - last run exited with code 1
        -> read its output: ldm logs com.example.report

== loaded jobs with no plist in your folder (1) ==
  info  com.thirdparty.updater - loaded from outside your LaunchAgents folder (fine if you expected it)
        -> no action needed; ldm only manages the plists in your own folder

3 warnings, 4 notices across 6 jobs
```

## Commands

Every command takes `--dir` (scan a LaunchAgents directory other than
`~/Library/LaunchAgents`), and every command except `logs` takes `--json`
(schema v1).

| command | what it does | underlying launchctl |
| --- | --- | --- |
| `ldm status` | every LaunchAgent with its state, pid, last exit, schedule, plist | `launchctl list` + a plist scan |
| `ldm info <label>` | one job in full: command, schedule keys, log files and sizes | `launchctl print gui/<uid>/<label>` |
| `ldm logs <label>` | tail stdout and stderr; `-n` for lines, `-f` to follow | *(none — reads the files the plist declares)* |
| `ldm doctor` | seven read-only health checks; `--strict` exits 1 on any warning | `launchctl list`, `plutil -lint` |
| `ldm start <label>` | run the job now; the schedule is untouched | `launchctl kickstart gui/<uid>/<label>` |
| `ldm stop <label>` | signal the running process; the job stays loaded | `launchctl kill SIGTERM gui/<uid>/<label>` |
| `ldm restart <label>` | kill the process, then run it again | `launchctl kickstart -k gui/<uid>/<label>` |
| `ldm load <label>` | register the plist with launchd | `launchctl bootstrap gui/<uid> <plist>` |
| `ldm unload <label>` | unregister the job; the plist stays on disk | `launchctl bootout gui/<uid>/<label>` |
| `ldm enable <label>` | allow the job to be loaded | `launchctl enable gui/<uid>/<label>` |
| `ldm disable <label>` | refuse to load the job until enabled again | `launchctl disable gui/<uid>/<label>` |
| `ldm install …` | build a plist, validate it, put it in place and load it | `plutil -lint`, then `bootstrap` |
| `ldm uninstall <label>` | back the plist up, unload the job, remove the file | `launchctl bootout gui/<uid>/<label>` |
| `ldm restore <label>` | newest backup back in place, and loaded | `launchctl bootstrap gui/<uid> <plist>` |

Lifecycle verbs take a **label**, never a path, and only labels found in your
LaunchAgents directory are accepted. No-ops — stopping something that is not
running, loading something already loaded — are successes and exit 0.

## What launchd actually means

These four things surprise nearly everyone, so `ldm` says them out loud in its
own output too.

**`stop` is not `unload`.** `ldm stop` sends SIGTERM to the running process. The
job stays registered with launchd and its schedule still applies, so it will run
again at the next interval. `ldm unload` is what takes it out of launchd until
you load it back.

**`stop` on a KeepAlive job does not keep it stopped.** `KeepAlive` means "restart
this whenever it exits", and launchd honours that within seconds of your SIGTERM.
`ldm stop` prints a warning when the job sets `KeepAlive` and points you at
`ldm unload`.

**`enable`/`disable` is load permission, not autostart.** A disabled label cannot
be bootstrapped at all — `ldm load` will fail — but disabling does nothing to a
job that is already loaded and running. If you want a job not to start at login,
that is `ldm unload` (or removing `RunAtLoad`), not `ldm disable`.

**A negative exit code is a signal.** launchd reports a signalled process as the
negative signal number, so a job you stopped yourself shows up as `-15` in the
`EXIT` column and as `✗ failing` in `status`, because from launchd's point of
view the last run did not exit cleanly. `ldm doctor` knows the difference and
downgrades `-15` (SIGTERM) to a notice, since that is exactly what a deliberate
stop looks like.

## Creating and removing jobs

```console
$ ldm install --label com.example.backup \
      --cmd "/usr/bin/rsync -a /Users/you/src /Volumes/bk" --interval 2h
$ ldm install --label com.example.report \
      --cmd "/bin/sh /Users/you/bin/report.sh" \
      --calendar "Mon 09:30" --log-dir ~/logs/report --run-at-load
$ ldm uninstall com.example.backup   # backs the plist up first, then unloads it
$ ldm restore com.example.backup     # newest backup back in place, and loaded
```

`--interval` takes `45s` / `30m` / `2h` / `1d`. `--calendar` takes `"09:30"`,
`"daily 09:30"` or `"Mon 09:30"`. `--cmd` is split into `ProgramArguments` with
`shlex` and handed to launchd as data — no shell is ever involved, so quoting is
the only thing you have to get right, not escaping. Logs default to
`~/Library/Logs/<label>/out.log` and `err.log`; `--run-at-load` and `--keepalive`
set the matching plist keys.

All three are transactions. A failure leaves the machine as it was:

- **install** writes a temp file next to the target, validates it with
  `plutil -lint`, `os.replace`s it into place and bootstraps it. If the lint or
  the bootstrap fails, the new plist is removed again. An existing label is
  refused unless you pass `--force`, which uninstalls the old job first — backup
  included — and puts it back, load state and all, if the new one fails.
- **uninstall** copies the plist to `~/.local/share/ldm/backups/<UTC>/` *before*
  it unloads the job, verifies launchd actually let go, and only then deletes the
  file. A failure after the unload restores the file and loads it again. The
  backup path is printed; `LDM_BACKUP_DIR` moves the store elsewhere.
- **restore** takes the newest backup for a label, refuses to overwrite an
  existing plist without `--force`, and loads what it restored.

## JSON contract (v1)

Every command accepts `--json`. The payload always carries `"schema": 1`; the
shape only changes with the schema number, so scripts can pin it.

`status` returns `jobs[]`, `info` returns a single `job` with detail fields
added, `doctor` returns `findings[]` plus a `summary`, and the write commands
return a `result`.

```console
$ ldm status --json
```
```json
{
  "schema": 1,
  "jobs": [
    {
      "label": "com.example.backup",
      "loaded": true,
      "pid": null,
      "last_exit": 0,
      "schedule": "every 2h",
      "plist_path": "/Users/you/Library/LaunchAgents/com.example.backup.plist",
      "stdout_path": "/Users/you/Library/Logs/com.example.backup/out.log",
      "stderr_path": "/Users/you/Library/Logs/com.example.backup/err.log",
      "state": "idle"
    }
  ]
}
```

`state` is one of `running`, `idle`, `failing`, `unloaded`, `ghost`, `unknown`.
A plist that cannot be parsed degrades to `unknown` rather than breaking the run.

Exit codes: **0** success (including no-ops, and `doctor` finding problems),
**1** error (or `doctor --strict` with at least one warning).

## Safety model

`ldm` manages *your* LaunchAgents and nothing else.

**Read-only commands** — `status`, `info`, `logs`, `doctor` — never write
anything and never change launchd state. `doctor` reports and suggests; it never
repairs. Log files are opened read-only, and `info` only `stat`s them.

**Write commands** — the lifecycle verbs plus `install`/`uninstall`/`restore` —
are bounded by four rails:

- **User domain only.** Every launchctl call targets `gui/$UID`. The system
  domain, `/Library/LaunchDaemons` and anything requiring root are never touched,
  and `ldm` never elevates: if you are not root, nothing it does can become root.
- **`com.apple.*` is refused.** `install` and `restore` reject the Apple
  namespace outright so a typo cannot shadow a system agent. `doctor` skips
  `com.apple.*` and `application.*` entirely when listing foreign loaded labels,
  and it never acts on any of them — it only ever reports.
- **Path normalization.** Lifecycle commands take a label, never a path, and the
  resolved plist must `realpath` to a file inside the scanned directory — a
  symlink in `~/Library/LaunchAgents` pointing elsewhere is refused. `install`
  applies the same check to where it is about to write.
- **Backup-first transactions.** Nothing destructive happens before a copy
  exists. `uninstall` backs up, unloads, verifies the unload, and only then
  deletes; a failure at any step restores both the file and its load state.
  `install --force` and `restore --force` roll the displaced job back the same
  way.

**Plist contents are data, never code.** `ldm` parses plists with `plistlib`,
runs no shell anywhere, and never executes anything a plist contains. `--cmd` is
split with `shlex` into `ProgramArguments`; launchd, not `ldm`, is what
eventually runs it. Every subprocess in the codebase lives in one module
(`launchdeck/adapter.py`) and is either `/bin/launchctl` or `/usr/bin/plutil`,
invoked as an argv list with no shell.

## Verified on

Tested on macOS 15 (Darwin 24), Python 3.9–3.12. `launchctl` output formats vary
across macOS versions; other versions are unverified. The parsers degrade rather
than crash — an unrecognised `launchctl list` yields the disk inventory alone,
and an unparseable `launchctl print` yields an empty detail section — so an
untested macOS should give you less information rather than wrong information.

## Limitations

- **`enable`/`disable` rows outlive their jobs.** `launchctl disable` writes into
  a root-owned override database that `ldm` cannot read fully or clean up. The
  row survives `uninstall`, so a label you disabled and then removed will refuse
  to load when you install it again. `ldm uninstall` warns when it removes a
  disabled label; the fix is `ldm enable <label>` afterwards.
- **`doctor` judges one run, not a history.** "Failed runs" reflects the single
  last exit status launchd is holding, because that is all `launchctl list`
  reports. A job that fails every third run looks healthy two times out of three.
- **`doctor` cannot see inside every plist.** A plist Apple's parser accepts but
  Python's strict XML parser rejects — a `--` inside an XML comment is the usual
  cause — is reported as a notice with a `plutil -convert xml1` suggestion, and
  its details are missing from `status` until you convert it.
- **"Program not found" can be wrong for shell builtins and PATH tricks.** The
  check resolves absolute paths on disk and bare commands against *your* `PATH`,
  which is not the minimal `PATH` launchd gives the job. Absolute paths in
  `ProgramArguments` are the real fix either way.
- **User LaunchAgents only.** System daemons are out of scope; there is no
  `--system` write mode and there will not be one.
- **macOS only.** No systemd, no remote machines.

## Development

```console
$ pip install -e ".[dev]"
$ python -m pytest tests/ -q
```

The unit suite never invokes `launchctl` — the subprocess runner is injectable,
so every launchd interaction is covered against a fake — which is why it is safe
to run anywhere, CI included.

## License

MIT. See [LICENSE](LICENSE).
