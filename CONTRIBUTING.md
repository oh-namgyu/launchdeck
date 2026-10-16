# Contributing to launchdeck

Thanks for your interest! Bug reports (with your macOS version and the
`launchctl` output involved) and pull requests are welcome.

## Development setup

```sh
python -m venv .venv && source .venv/bin/activate
python -m pip install -e ".[dev]"     # pytest is the only dev dependency
python -m pytest tests/ -q
ldm --help
```

The unit suite never invokes `launchctl`: the subprocess runner is
injectable and every launchd interaction runs against a fake, so the suite is
safe to run anywhere. CI runs it on Python 3.9 (Ubuntu) and 3.12 (macOS).

## Guidelines

- **Zero runtime dependencies.** Standard library only. Do not add a
  third-party import.
- **Keep the safety model.** User domain (`gui/$UID`) only, `com.apple.*`
  refused, labels resolved to files inside the scanned directory, and
  backup-first transactions with rollback for anything destructive. Read the
  Safety model in the [README](README.md) and [SECURITY.md](SECURITY.md).
- **One place for subprocesses.** Every subprocess call lives in
  `launchdeck/adapter.py`, uses an argv list and never a shell, and runs only
  `/bin/launchctl` or `/usr/bin/plutil`.
- **No real launchd in tests.** Use the injectable runner and fakes; a test
  must never load, unload or kill a real job.
- **JSON is a contract.** `--json` output carries `"schema": 1`; changing its
  shape means a new schema number and a README update.
- **Degrade, do not crash.** Unrecognised `launchctl` output should yield less
  information, not an exception.
- Add a regression test for any bug fix, and a CHANGELOG entry for anything a
  user would notice.

## Pull requests

Keep PRs focused on one change, describe what changed and how you verified
it, and make sure `python -m pytest tests/ -q` is green before opening one.
