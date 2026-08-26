# Changelog

All notable changes to MacMedic are documented here.

## [Unreleased]

### Changed
- **Left-click now opens a real Vorssaint-style panel** instead of the text
  dropdown. The panel is a custom `NSPopover` over an `NSVisualEffectView`
  (dark, rounded card) with: a MacMedic header + colored **Health** pill,
  CPU / GPU / Fan temperature tiles, CPU usage bar + live sparkline, a Memory
  bar with a **Normal / Warning / Critical** pressure pill, a Battery bar with
  health/cycle readout, a Fan RPM slider + **Auto** button, and footer buttons
  (**Sensors**, **Clean**, **Quit**). The original tool menu is still available
  on **right-click**. See `macmedic/panel.py`.
- **Processes section added to the panel**: a scrollable list of the top
  CPU/RAM consumers (toggle between CPU and Memory) with a per-row **✕** button
  that runs the same safety-checked Quit flow as the right-click menu — keeping
  the ability to kill runaway apps front-and-center for an Intel Mac.

## [0.2.0] - 2026-08-19

### Added
- **Sensors** panel: battery, CPU package temp, per-core temperatures
  (TC0C–TC7C), GPU, live power draw (system / CPU / disk watts), fan RPM, and
  thermal state — decoded defensively from the SMC, including 1-byte `sp78`
  core reads found on 2020 Intel hardware.
- **Fan Control**: set a manual target RPM (clamped to the SMC bounds or a hard
  1000–7000 RPM safety range) and restore automatic mode. Writes are
  restricted to the `F<n>Md` / `F<n>Tg` keys only.
- **Battery Trends**: hourly samples stored in a small SQLite database at
  `~/Library/Application Support/MacMedic/trends.db` with a 30-day summary
  panel.
- **Orphaned App Data**: read-only orphan scan of `~/Library/Application Support`
  for leftovers of uninstalled, unused apps — reports candidates, never deletes.
- **EOL Health Check** now includes a 0–100 health score with a plain-language
  verdict (thermals 30, RAM 25, disk 25, battery 20).
- Sustained high CPU temperature notifications (warn/crit thresholds) with a
  configurable cooldown.

### Changed
- Menu reorganized into grouped sections; removed a duplicate **Quit** item
  that `rumps` auto-appended. Process submenu rows decluttered (redundant
  detail lines removed). Status tooltip now shows memory pressure.
- **UI polish (Vorssaint-inspired)**: the menu now opens with a live **health
  badge** header (`MacMedic · Intel Mac · Health 80/100`) that refreshes
  every 30s and opens the health check when clicked. The status bar uses plain
  `CPU`/`RAM` labels with a severity dot + sparkline instead of glyph icons.

### Fixed
- `smc._decode` handles 1-byte `sp78` readings (integer part only) instead of
  returning `None`.
- py2app build fixed under setuptools 84 by removing `[project].dependencies`
  from `pyproject.toml` (runtime deps stay in `requirements.txt`).

## [0.1.1] - 2026-08-19

### Added
- AppleSMC reader (`macmedic/smc.py`) — reads real CPU temperature and fan
  RPM on Intel Macs through IOKit, no root required. Verified on a 2020
  16-inch MacBook Pro (`sp78` fixed-point temps, little-endian `flt` fans).
- **EOL Fitness Check** panel — reports macOS version/build, Intel vs Apple
  Silicon, battery health, live CPU temp + fan, RAM pressure, free disk, and
  practical tips for unsupported Intel Macs.
- CPU temperature and live fan RPM now shown in the **Battery & Thermal** panel.
- GitHub Actions CI workflow (pytest on macOS runners).
- Release build script (`scripts/build_release.sh`) producing a zipped
  `MacMedic.app` bundle.
- MIT license and this changelog.
- `pyproject.toml` with `ruff`, `ruff format`, and `mypy` checks wired into CI.
- GitHub Actions **release** workflow: pushing a `v*` tag builds the app and
  attaches `MacMedic-<version>.zip` to a GitHub Release.
- User-tunable JSON config at
  `~/Library/Application Support/MacMedic/config.json` (poll interval,
  thresholds, scan rules) with deep-merge defaults and safe fallback.
- Homebrew cask (`Casks/macmedic.rb`), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
  `SECURITY.md`, and GitHub issue templates.
- Unit tests for the config loader and the cleaning scanner (cache/log/duplicate
  scanning and protected-path refusal) using `tmp_path` fixtures.

### Fixed
- SMC reader annotated so `mypy` passes with no `# type: ignore`.
- All sources now satisfy `ruff` (E/F/W/I/UP/B) at 120 columns.

## [0.1.0] - 2026-08-19

### Added
- Menu bar status: CPU % with a 10-sample sparkline and memory-pressure label,
  refreshed every 2 seconds via a single `rumps.Timer`.
- Top-10 processes by CPU and by memory, each with one-click **Quit**
  (`SIGTERM`) and **Force Quit** (`SIGKILL`), plus confirmation guards for
  system-critical processes.
- **Launch Agents & Login Items** panel with a built-in bloatware/telemetry
  blocklist and one-click safe disabling (unload + move plist, reversible).
- **Battery & Thermal** panel (battery health, cycles, ioreg temperature).
- **Smart Clean** rule-based scanner for large caches, old logs, and
  hash-verified duplicate downloads — always confirms before deleting.
- Defensive error handling with a rotating log at `~/Library/Logs/MacMedic.log`.
- py2app packaging and unit tests for process ranking and blocklist matching.