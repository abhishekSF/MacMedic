# MacMedic — Project Plan

This document is the living plan for **MacMedic**: what it is, why it exists,
the architecture, the roadmap, and a record of what has actually been shipped.
It complements the user-facing [`README.md`](README.md) and the
[`CHANGELOG.md`](CHANGELOG.md).

---

## 1. Purpose

MacMedic is a **native macOS menu bar application written in plain Python**
(`rumps` + `psutil` + `ctypes`/`PyObjC`). It is built specifically for the **last
generation of Intel MacBooks** (e.g. a 2020 Intel MacBook Pro, 16 GB) that Apple
is leaving behind after macOS 26 (the final Intel release).

Design constraints, in priority order:

1. **Use as little as possible itself.** The whole point is to *save* resources,
   so the app must be tiny: one 2-second polling timer, no background daemons,
   no Electron/web views, no subprocesses on the hot path.
2. **Real Intel hardware access.** The SMC (System Management Controller) is
   fully readable on Intel Macs without root — CPU temperature, fan RPM, power
   draw. This is exactly the data that becomes hard to get on Apple Silicon, so
   MacMedic leans into it.
3. **Practical maintenance for an aging machine** — kill runaway processes,
   trim launch agents, clean caches, watch battery health, and control the fan
   when thermals climb.
4. **Safe by default.** Every destructive action is confirmation-gated; nothing
   is deleted or signalled without an explicit user choice.

---

## 2. Target environment

| Item | Value |
| --- | --- |
| OS | macOS 15.x (Sequoia) on Intel x86_64 (also runs on Apple Silicon) |
| Python | 3.14 (developed); `requires-python = ">=3.9"`) |
| Runtime | Single `rumps.App`, packaged with `py2app` into an `LSUIElement` (menu-bar, no Dock icon) `.app` |
| Deps | `rumps`, `psutil` (packaged); `pyobjc` is pulled in transitively by `rumps`; `pytest`, `ruff`, `mypy` for dev |
| Footprint | ~30 MB idle, ~0% CPU between ticks |

---

## 3. Architecture

```
                    ┌─────────────────────────────┐
                    │        MacMedicApp          │  rumps.App subclass
                    │  (macmedic/app.py)          │
                    └──────────────┬──────────────┘
        ┌───────────────┬─────────┴──────────┬──────────────────┐
        ▼               ▼                    ▼                  ▼
  SystemMonitor    ProcessTracker      SMCReader          config
  (monitors.py)    (processes.py)      (smc.py)           (config.py)
        │               │                  │                  │
        ▼               ▼                  ▼                  ▼
  battery_detail   top_by_cpu/mem    core_temps/         JSON @
  eol_fitness_     quit/force_quit   fan_rpm/            ~/Library/.../
  score            request_*         set_fan_manual     config.json
                                   (IOKit, no root)
```

### Modules

| File | Responsibility |
| --- | --- |
| `macmedic/app.py` | Menu-bar shell, the single 2 s polling loop (`_tick`), status rendering, the right-click tool menu, and the **left-click Vorssaint-style panel** wiring. |
| `macmedic/panel.py` | Custom `NSPopover` over an `NSVisualEffectView` — the dark, rounded card UI (tiles, usage bars + sparklines, pills, fan slider, Processes list, footer buttons). Pure `PyObjC`; no `rumps` menu used. |
| `macmedic/monitors.py` | `SystemMonitor.sample()` (CPU %, memory %, memory pressure via `sysctlbyname` + ctypes), `battery_detail()`, `eol_fitness_score()` (0–100), `sensors_report()`. |
| `macmedic/smc.py` | `AppleSMC` IOKit reader/writer. Decodes temps (incl. 1-byte `sp78` per-core reads on 2020 Intel), power (`PSTR`/`PC0R`/`PDTR`), fan RPM/bounds, and safe fan control (`F<n>Md`/`F<n>Tg`, clamped 1000–7000 RPM). |
| `macmedic/processes.py` | Process snapshot (`psutil`), ranking by CPU/memory, safety classification (`safe`/`caution`/`critical`), and `request_quit`/`request_force_quit` (SIGTERM/SIGKILL). |
| `macmedic/launchagents.py` | Discovery of `~/Library/LaunchAgents` + system agents, blocklist matching, and **reversible** disable (move plist to `~/Library/LaunchAgents/MacMedic Disabled/`). |
| `macmedic/blocklist.py` | Built-in list of known bloatware / telemetry / updater agents. |
| `macmedic/scanner.py` | Rule-based cleaning scanner: large caches, old logs, hashed duplicate downloads. Read-only until confirmed. |
| `macmedic/debloat.py` | Read-only scan for orphaned `~/Library/Application Support` leftovers of uninstalled apps. |
| `macmedic/trends.py` | SQLite store (`trends.db`) of hourly battery/thermal samples with a 30-day summary. |
| `macmedic/config.py` | Defaults + deep-merge JSON loader from `~/Library/Application Support/MacMedic/config.json`. |

### The UI split (important)

`rumps` can only draw an **NSMenu** dropdown — it cannot reproduce a card-style
UI. To match the Vorssaint aesthetic requested by the user, the left-click
interaction was taken over with `PyObjC`:

- **Left-click** on the status item → toggles the custom `NSPopover` panel
  (`panel.py`): header + Health pill, CPU/GPU/Fan tiles, CPU bar + sparkline,
  Memory bar + pressure pill, Battery bar + health/cycles, **Processes list
  (CPU/MEM toggle, per-row ✕ to quit)**, Fan slider + Auto, footer
  (Sensors / Clean / Quit).
- **Right-click** → opens the classic `rumps` tool menu (Sensors, Battery
  Trends, Fan Control, Smart Clean, Orphaned App Data, Launch Agents, About,
  Quit, and the Top CPU / Top Memory submenus with Quit / Force Quit).

The status-bar text itself remains a compact `● CPU 12%▂▅▆▇ RAM 57%` readout
with a severity color and a hover tooltip.

---

## 4. Design reference

The panel UI is modelled on **Vorssaint** (`vorssaint/vorssaint-utils`):
native SwiftUI dark popover, temperature tiles, colored usage bars with
sparklines, a memory-pressure pill, and big footer buttons. Note that Vorssaint
targets macOS 14+ and Apple Silicon and is *not* Intel-focused — MacMedic borrows
the visual language but keeps its Intel/EOL mission and adds the process-killing
and maintenance features Vorssaint does not have.

---

## 5. Roadmap (shipped vs. planned)

### Shipped
- **Phase 1 — Project hygiene & foundation**: `pyproject.toml` (ruff/mypy/pytest),
  CI workflow (lint + format + typecheck), release workflow (tag → build → attach
  `.app` zip), JSON config, Homebrew cask skeleton, CONTRIBUTING / CODE_OF_CONDUCT
  / SECURITY, issue templates. (59 unit tests.)
- **Phase 2 — Intel hardware depth**: per-core temps (TC0C–TC7C, incl. 1-byte
  `sp78` fix), live power draw (PSTR/PC0R/PDTR), thermal alerts with cooldown,
  EOL health score (thermals 30 / RAM 25 / disk 25 / battery 20).
- **Phase 3 — Maintenance toolkit**: SMC fan control (clamped manual + restore
  auto), Orphaned App Data (read-only), SQLite battery trends.
- **UI v1/v2 polish**: removed duplicate Quit, renamed jargon, live health badge
  in the menu bar, merged panels.
- **Vorssaint-style panel**: custom `NSPopover` card (left-click) with tiles,
  bars, sparklines, pills, fan slider, and a live **Processes** section with
  per-row kill. Right-click menu preserved.

### Planned / open
- Replace the `release/` zip placeholder SHA in `Casks/macmedic.rb` once the first
  GitHub Release exists.
- Add a "Force Quit" option per row in the panel's Processes list.
- Optional light-mode tuning of the card (currently tuned for dark).
- Signed/notarized distribution (currently ad-hoc; users may need to grant
  permissions / right-click → Open on first launch).

---

## 6. Repository layout

```
MacMedic/
├── MacMedic.py              # entry point (py2app)
├── setup.py                 # py2app packaging
├── pyproject.toml           # ruff / mypy / pytest config
├── requirements.txt
├── scripts/build_release.sh # one-command release build
├── Casks/macmedic.rb        # Homebrew cask
├── .github/
│   ├── workflows/ci.yml     # lint + format + typecheck + tests
│   ├── workflows/release.yml# build .app on tag push + attach asset
│   └── ISSUE_TEMPLATE/
├── macmedic/                # application package (see module table)
├── tests/                   # unit tests (no live system required)
├── plan.md                  # this file
├── README.md                # user-facing docs
├── CHANGELOG.md
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── SECURITY.md
└── LICENSE                  # MIT
```

---

## 7. How to build / run / test

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python MacMedic.py                       # or: python -m macmedic
python -m pytest -q                     # tests
ruff check macmedic/ && mypy macmedic/  # lint + types
./scripts/build_release.sh              # -> release/MacMedic-<version>.zip
```

Environment variable `MACMEDIC_PANEL_AUTOOPEN=1` launches with the panel open
(used for screenshots/debugging).
