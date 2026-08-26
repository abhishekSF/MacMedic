# AGENTS.md

## Cursor Cloud specific instructions

MacMedic is a **macOS-only menu bar app**. Its UI shell (`macmedic/app.py`,
`macmedic/panel.py`) imports `rumps` + PyObjC (`objc`, `AppKit`, `Foundation`),
which cannot be installed or run on the Linux Cloud VM. Do **not** try to
`pip install -r requirements.txt` here — `rumps`/`pyobjc`/`py2app` are macOS-only
and will fail. The startup update script installs only the cross-platform dev
subset (`psutil`, `pytest`, `ruff`, `mypy`) into `.venv/`.

### What runs here vs. what does not

- Runnable on Linux: the monitoring engine (`monitors`, `processes`, `scanner`,
  `smc`, `config`, `trends`, `blocklist`, `debloat`, `launchagents`) — plain
  `psutil` + stdlib that degrade gracefully off macOS (sensors/SMC return
  `None`, subprocess calls like `ioreg`/`pmset` are absent). The full test
  suite, `ruff`, and `mypy` all run.
- Not runnable on Linux: the menu bar GUI (`python MacMedic.py` /
  `python -m macmedic`) and the py2app release build (`scripts/build_release.sh`).
  These require macOS.

### Commands (run via the venv created by the update script)

- Tests: `.venv/bin/python -m pytest -q`
- Type check: `.venv/bin/mypy macmedic`
- Lint: `.venv/bin/ruff check macmedic tests MacMedic.py setup.py`
- Format check: `.venv/bin/ruff format --check macmedic tests MacMedic.py setup.py`
- Compile check (CI step): `.venv/bin/python -m compileall -q macmedic tests MacMedic.py setup.py`
- Exercise the core engine without the GUI:
  `PYTHONPATH=/workspace .venv/bin/python -c "from macmedic.monitors import SystemMonitor, eol_fitness_score; print(SystemMonitor().sample()); print(eol_fitness_score())"`

### Gotchas

- Scripts run from outside the repo root need `PYTHONPATH=/workspace` (the
  package is used in-place; it is not `pip install`-ed into the venv).
- `ruff check` currently **fails** on `main` (an `I001` import-sort error in
  `macmedic/panel.py`) and `ruff format --check` reports 2 files. This is a
  pre-existing failure that GitHub Actions CI also hits with the same ruff
  0.16.4 — it is not an environment problem. `mypy`, `pytest`, and the compile
  check all pass.
