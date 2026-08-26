# Contributing to MacMedic

Thanks for your interest. This project is a small, dependency-light, Intel-EOL-focused macOS menu bar tool. Before you open a PR, please read this.

## Ground rules

- **Keep it lightweight.** MacMedic targets aging Intel Macs (2014–2020 era). Memory and CPU footprint matter; a 5 MB frame or 200 MB cache is a bug. Run the memory smoke check in `README.md` before/after changes.
- **Keep dependencies minimal.** Prefer `ctypes`/stdlib over a new PyPI package. If you must add a dependency, justify it in the PR and update `requirements.txt` and `pyproject.toml`.
- **No admin rights by default.** Monitoring (SMC read, sensors, processes, launch agents) must work without `sudo`.
- **Safety first.** Anything that deletes, disables, or writes (Smart Clean, agent disabling, future fan control) needs an explicit confirmation with a clear description of what will happen.

## Development setup

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -r <(grep -E "pytest|ruff|mypy" requirements.txt)
```

Run all checks:

```sh
.venv/bin/ruff check macmedic tests MacMedic.py setup.py
.venv/bin/ruff format --check macmedic tests MacMedic.py setup.py
.venv/bin/mypy macmedic
.venv/bin/python -m pytest -q
```

## Tests

- New behavior needs tests. Put them in `tests/` with the same file name as the module (`test_scanner.py` for `macmedic/scanner.py`).
- Use `tmp_path` fixtures and `monkeypatch` for anything touching the filesystem; never write to real user paths in tests.
- The SMC reader tests skip automatically on non-macOS / non-Intel hardware. Tests must never require the app to be running.

## Smart Clean thresholds

Scan behavior is configurable via `~/Library/Application Support/MacMedic/config.json`. When you change defaults, update `macmedic/config.py` (both `DEFAULTS` and the `config.get*` fallbacks), the README, and the tests.

## Packaging

- `scripts/build_release.sh` builds `dist/MacMedic.app` and zips it into `release/`.
- GitHub Actions runs lint, typecheck, and tests on every push; a `v*` tag triggers the release build. Never commit the built `.app` or `release/` zips.
- If you bump the version, update `pyproject.toml`, `Casks/macmedic.rb`, and `CHANGELOG.md` together.

## Changelog

Add an entry to `CHANGELOG.md` under `[Unreleased]` (or a new release heading) for any user-visible change. One line, past tense, focused on the benefit.

## Commit style

Small, focused commits. Prefer: `add:`, `fix:`, `refactor:`, `test:`, `docs:`, `ci:`. For example `fix: read F0Ac fan RPM as little-endian float on older Intel Macs`.

## Questions

Open an issue instead of emailing. If it is a bug, include your macOS version, Intel/Apple Silicon, and the relevant section of `~/Library/Logs/MacMedic.log`.