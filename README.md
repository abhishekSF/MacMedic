# MacMedic

> A tiny macOS menu bar monitor + cleanup tool, built for the last generation of
> Intel MacBooks that Apple is leaving behind.

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue)](#)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-lightgrey)](.github/workflows/ci.yml)
[![macOS](https://img.shields.io/badge/macOS-Intel%20only-orange)](#)

MacMedic is a **native menu bar application** in plain Python — no Electron,
no web views, no background daemons. It was designed for a 2020 Intel
MacBook Pro that is nearing (or past) the end of Apple's support window, so it
exists to **save** resources, and therefore uses as little as possible itself.

## What it does

**Live status in the menu bar** — a compact, color-coded readout:
`⚙12%▂▅▆▇ ◫57%` (CPU percent with a 10-sample sparkline, then memory
percent). The whole status turns **orange** when CPU, RAM, or memory pressure
approaches a worrying level and **red** at dangerous levels; otherwise it
adapts to your menu bar appearance. Hovering over the status shows the same
readout as a tooltip. Everything refreshes every two seconds via a single
polling loop.

**Real hardware access on Intel** — Apple's System Management Controller (SMC)
is fully readable on Intel Macs without root. MacMedic uses it to show **live
CPU temperature** and **fan RPM** in real time. No helper daemon, no admin
prompt. (This is exactly the data that becomes hard to get on Apple Silicon.)

**Top 10 processes** by CPU and by memory, each with one-click **Quit**
(`SIGTERM`) and a **Force Quit** (`SIGKILL`) fallback. System-critical
processes (kernel_task, WindowServer, launchd, root daemons) are flagged with
⚠ and require an explicit confirmation before anything is signalled.

**Launch Agents & Login Items** — lists everything set to auto-start, flags
known bloatware / telemetry / update agents (Adobe helpers, Google and
Microsoft updaters, backup and sync agents, adware) from a small built-in
blocklist, and lets you **disable** one with a click. Disabling unloads the
agent and *moves* its plist into `~/Library/LaunchAgents/MacMedic Disabled/`
— reversible, never destructive.

**Sensors** — one panel with everything: battery %, health, cycles, battery
temperature, CPU package temp, **per-core temps**, GPU temp, real power draw
(system / CPU / disk watts), fan RPM, and thermal state.

**Battery Trends** — hourly samples (battery %, health, cycles, battery temp,
CPU temp, fan) stored in a small SQLite database
(`~/Library/Application Support/MacMedic/trends.db`) with a 30-day summary.

**Fan Control** — set a manual target RPM (clamped to a safe range) or restore
automatic SMC control, all from the menu bar.

**Orphaned App Data** — a read-only scan for orphaned leftovers of uninstalled
apps in `~/Library/Application Support`. It only *reports* candidates; it never
deletes.

**EOL Health Check** — a one-click panel built for unsupported Intel Macs:
macOS version/build, Intel vs Apple Silicon, battery health, live temp and
fan, RAM and disk headroom, a 0–100 health score, plus practical advice (trim
launch agents, keep disk free, renew thermal paste, reduce visual effects).

**Smart Clean** — a rule-based scan (no AI) that finds large cache folders,
old log files, and duplicate downloads (verified by content hash). It always
presents a safe-to-delete list with sizes and **always asks for confirmation**
before deleting anything.

## The menu bar UI

MacMedic uses a **split interaction** so the new card UI and the full tool menu
both stay available:

- **Left-click** the menu-bar item → opens a custom, dark, rounded **popover
  panel** (modelled on Vorssaint) with:
  - a **MacMedic** header and a colour-coded **Health** pill (green/amber/red by
    the 0–100 score);
  - **CPU / GPU / Fan** temperature tiles;
  - a **CPU** usage bar with a live sparkline and a **Memory** bar with a
    **● Normal / Warning / Critical** pressure pill;
  - a **Battery** bar showing health % and cycle count;
  - a **Processes** section (toggle **CPU** / **MEM**) listing the top
    consumers with a per-row **✕** button that runs the same safety-checked
    Quit flow as the menu — so killing a runaway app is one click away;
  - a **Fan** RPM slider + **Auto** button;
  - footer buttons: **Sensors**, **Clean**, **Quit**.
- **Right-click** the menu-bar item → opens the classic tool menu (Sensors,
  Battery Trends, Fan Control, Smart Clean, Orphaned App Data, Launch Agents,
  About, Quit, and the Top CPU / Top Memory submenus with Quit / Force Quit).

The status-bar text itself stays as a compact `● CPU 12%▂▅▆▇ RAM 57%` readout
with a severity colour and a hover tooltip.

## Resource footprint

Measured on macOS 15 with the packaged `.app` (Python 3.14 runtime):

| Metric | Value |
| --- | --- |
| Physical footprint (idle) | **~30–32 MB** |
| Polling | one 2 s timer, ~0% CPU |
| Extra processes | none |

The hot path reads memory pressure via `sysctlbyname` through ctypes and CPU
delta via `psutil.cpu_percent(None)` — no subprocesses on the tick.

## Installation

Requires **Python 3.9+** and macOS. Intel or Apple Silicon.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run from source:

```bash
python MacMedic.py          # or: python -m macmedic
```

The icon and menu live in the menu bar. Quit via the **Quit** menu item.

## Permissions

macOS is strict about system access. MacMedic handles missing permissions
gracefully (it shows a message instead of crashing), but for full features:

| Feature | Permission needed | How to grant |
| --- | --- | --- |
| Read `/var/log` and some Library folders in Smart Clean | **Full Disk Access** | System Settings → Privacy & Security → Full Disk Access → add MacMedic (or your terminal) |
| Quit / Force Quit other users' or root processes | **admin/sudo** | Same-user processes need no permission |
| Reveal in Finder | **Automation** (optional) | Grant when macOS prompts |
| Fan RPM + CPU temp via SMC | **none** | Works out of the box on Intel Macs |
| Manual fan control (F0Tg / F0Md) | **none on most Intel Macs** | If writes fail, relaunch MacMedic as admin (`sudo`) |

When running from a terminal, grant the terminal app Full Disk Access so the
scanner can see `/var/log` and protected caches.

## Configuration

Everything is tunable through a plain JSON file at
`~/Library/Application Support/MacMedic/config.json`. Create it with only the
keys you want to override; the rest fall back to defaults.

```json
{
  "poll_interval_seconds": 2.0,
  "sparkline_len": 10,
  "top_processes": 10,
  "thresholds": {
    "cpu_warn_pct": 75.0,
    "cpu_crit_pct": 90.0,
    "ram_warn_pct": 80.0,
    "ram_crit_pct": 92.0,
    "temp_warn_c": 85.0,
    "temp_crit_c": 95.0
  },
  "scan": {
    "cache_min_bytes": 52428800,
    "log_max_age_days": 30,
    "duplicate_min_bytes": 1048576,
    "duplicate_scan_dir": "~/Downloads"
  },
  "debloat": {
    "min_size": 5242880,
    "min_age_days": 30,
    "max_recent_mod_days": 14
  },
  "trends": {
    "interval_seconds": 3600
  }
}
```

| Key | Default | Meaning |
| --- | --- | --- |
| `poll_interval_seconds` | `2.0` | Seconds between status refreshes |
| `sparkline_len` | `10` | CPU history samples shown in the menu bar sparkline |
| `top_processes` | `10` | Entries in each Top Processes submenu |
| `thresholds.cpu_warn_pct` / `cpu_crit_pct` | `75` / `90` | CPU levels that turn the status orange / red |
| `thresholds.ram_warn_pct` / `ram_crit_pct` | `80` / `92` | Memory levels that turn the status orange / red |
| `thresholds.temp_warn_c` / `temp_crit_c` | `85` / `95` | (reserved) thermal alert levels |
| `scan.cache_min_bytes` | `52 MB` | Minimum cache folder size Smart Clean reports |
| `scan.log_max_age_days` | `30` | Logs older than this are flagged |
| `scan.duplicate_min_bytes` | `1 MB` | Minimum size for duplicate-file comparison |
| `scan.duplicate_scan_dir` | `~/Downloads` | Directory scanned for duplicates |
| `debloat.min_size` / `min_age_days` / `max_recent_mod_days` | `5 MB` / `30` / `14` | Orphaned App Data candidate rules |
| `trends.interval_seconds` | `3600` | How often a battery/thermal sample is recorded |

A malformed config file is ignored with a warning; MacMedic always runs with
safe defaults.

## Building a release (py2app)

```bash
./scripts/build_release.sh
```

This builds `dist/MacMedic.app` (an `LSUIElement` menu-bar app with no Dock
icon) and zips it to `release/MacMedic-<version>.zip` — ready to attach to a
GitHub Release. CI builds and attaches it automatically when you push a `v*`
tag (see `.github/workflows/release.yml`).

## Homebrew

```bash
brew install --cask macmedic
```

The cask (in `Casks/macmedic.rb`) is published to the Homebrew tap after each
release.

## Testing

```bash
python -m pytest -q
```

Unit tests cover process ranking/filtering, the blocklist matching, the SMC
decoder, config loading, and the cleaning scanner (with `tmp_path` fixtures) —
pure logic, no live system required. CI runs these on macOS runners together
with `ruff`, `ruff format --check`, and `mypy` (see `.github/workflows/ci.yml`).

## Safety model

- Quit/kill of a flagged “system critical” process always requires a
  confirmation dialog.
- Manual fan control is clamped to the SMC's own min/max (or a hard
  1000–7000 RPM safety range) and the mode is restored to automatic with one
  click. It never writes to any SMC key other than `F<n>Md` / `F<n>Tg`.
- Orphaned App Data is strictly read-only; it lists orphan candidates but cannot
  delete anything.
- Disabling a launch agent only **moves** its plist into
  `~/Library/LaunchAgents/MacMedic Disabled/` — restore by moving it back.
- Smart Clean only deletes after an explicit “Delete” confirmation.
- Every system call is wrapped defensively. Unexpected errors go to
  `~/Library/Logs/MacMedic.log` (rotated at 1 MB) and the polling loop keeps
  running. The app never crashes silently.

## Project layout

```
MacMedic/
├── MacMedic.py              # entry point (used by py2app)
├── setup.py                 # py2app packaging
├── pyproject.toml           # lint / typecheck / pytest config
├── scripts/build_release.sh # one-command release build
├── requirements.txt
├── Casks/macmedic.rb        # Homebrew cask
├── macmedic/
│   ├── app.py               # menu bar shell + polling loop + click wiring
│   ├── panel.py             # custom Vorssaint-style NSPopover card (PyObjC)
│   ├── monitors.py          # CPU / memory pressure / battery / thermal
│   ├── smc.py               # AppleSMC reader via IOKit (no root)
│   ├── processes.py         # process snapshot, ranking, quit / force-quit
│   ├── launchagents.py      # launch agent discovery + safe disable
│   ├── scanner.py           # rule-based cleaning scanner
│   ├── debloat.py           # read-only orphaned-app-data scan
│   ├── trends.py            # SQLite battery/thermal trend store
│   ├── blocklist.py         # bloatware / telemetry blocklist
│   └── config.py            # defaults + JSON settings loader
└── tests/                   # unit tests (blocklist, processes, smc, config, scanner, monitors, debloat, trends)
```

## License

[MIT](LICENSE) © 2026 Abhishek