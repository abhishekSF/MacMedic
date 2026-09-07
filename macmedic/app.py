"""MacMedic menu bar application.

A single lightweight polling loop (rumps.Timer, two seconds) drives the whole
app: it refreshes the status text, the top-process lists, and periodically the
launch agent list. Nothing else spins; heavier work (cleaning scan, ioreg
reads) runs on demand in background threads.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from typing import Any

import objc
import psutil
import rumps

try:
    from AppKit import (
        NSApp,
        NSAttributedString,
        NSColor,
        NSEvent,
        NSEventMaskLeftMouseUp,
        NSEventMaskRightMouseUp,
        NSFont,
        NSFontAttributeName,
        NSForegroundColorAttributeName,
        NSHeight,
        NSMakePoint,
        NSMenu,
        NSObject,
    )
except ImportError:  # pragma: no cover - rumps always pulls in AppKit
    NSAttributedString = NSColor = NSFont = NSApp = NSMenu = NSEvent = None
    NSFontAttributeName = NSForegroundColorAttributeName = None
    NSEventMaskLeftMouseUp = NSEventMaskRightMouseUp = NSMakePoint = NSObject = NSHeight = None

try:
    from . import panel
except Exception as exc:  # pragma: no cover - panel needs a UI environment
    logging.debug("panel unavailable: %s", exc)
    panel = None  # type: ignore

try:
    from . import touchbar
except Exception as exc:  # pragma: no cover - touchbar needs AppKit
    logging.debug("touchbar unavailable: %s", exc)
    touchbar = None  # type: ignore

from . import __version__, config, debloat, smc, trends
from .launchagents import (
    DISABLED_DIR,
    LaunchAgentInfo,
    disable_agent,
    list_launch_agents,
    reveal_in_finder,
)
from .monitors import PRESSURE_LABELS, SystemMonitor, battery_detail, eol_fitness_score, sensors_report
from .processes import (
    SAFETY_LABELS,
    ProcessInfo,
    ProcessTracker,
    request_force_quit,
    request_quit,
    top_by_cpu,
    top_by_memory,
)
from .scanner import delete_item, format_bytes, scan, total_size

log = logging.getLogger("macmedic.app")

SPARKLINE_BARS = "▁▂▃▄▅▆▇█"
AGENT_REFRESH_EVERY_TICKS = 15
THERMAL_CHECK_EVERY_TICKS = 15
HEALTH_REFRESH_EVERY_TICKS = 30
SAFETY_BADGES: dict[str, str] = {"safe": "●", "caution": "◐", "critical": "✖"}


_STATUS_BAR_CLICK: Any = None

if NSObject is not None:

    class _StatusBarClick(NSObject):
        def initWithApp_(self, app):
            self = objc.super(_StatusBarClick, self).init()
            if self is None:
                return None
            self._app = app
            return self

        def handleClick_(self, sender):
            self._app._status_clicked(sender)

    _STATUS_BAR_CLICK = _StatusBarClick


def sparkline(values: deque[float]) -> str:
    if not values:
        return ""
    maximum = max(values) or 1.0
    return "".join(SPARKLINE_BARS[min(7, int(v / maximum * 8) % 8)] for v in values)


def _danger_color(cpu_percent: float, memory_percent: float, memory_pressure: int):
    """Return a menu-bar color for the status, or the adaptive label color when healthy."""
    if NSColor is None:
        return None
    cpu_crit = config.get_float("thresholds.cpu_crit_pct", 90.0)
    cpu_warn = config.get_float("thresholds.cpu_warn_pct", 75.0)
    ram_crit = config.get_float("thresholds.ram_crit_pct", 92.0)
    ram_warn = config.get_float("thresholds.ram_warn_pct", 80.0)
    level = 0
    if cpu_percent >= cpu_crit or memory_percent >= ram_crit or memory_pressure >= 3:
        level = 2
    elif cpu_percent >= cpu_warn or memory_percent >= ram_warn or memory_pressure == 2:
        level = 1
    if level == 0:
        return NSColor.labelColor()
    return NSColor.systemRedColor() if level == 2 else NSColor.systemOrangeColor()


def _macos_build() -> str | None:
    try:
        result = subprocess.run(["sw_vers", "-buildVersion"], capture_output=True, text=True, timeout=3)
        return result.stdout.strip() or None
    except Exception:  # pragma: no cover - defensive
        return None


class MacMedicApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("MacMedic", title="MacMedic", quit_button=None)
        self.monitor = SystemMonitor()
        self.tracker = ProcessTracker()
        self.history: deque[float] = deque(maxlen=config.get_int("sparkline_len", 10))
        self._top_cpu: list[ProcessInfo] = []
        self._top_mem: list[ProcessInfo] = []
        self._agents: list[LaunchAgentInfo] = []
        self._agents_dirty = False
        self._agents_ticks_since_refresh = 0
        self._thermal_ticks = 0
        self._health_ticks = 0
        self._health_score: int | None = None
        self._last_snap: Any = None
        self._last_alert_time = 0.0
        self._last_trend_time = 0.0
        self._machine_label = self._detect_machine()
        self._touchbar = None
        self._touchbar_tried = False
        self._tb_item = None
        self._build_menu()
        self._refresh_health()
        self._panel_view: Any = None
        self._popover: Any = None
        self._status_handler: Any = None
        self._nsmenu: Any = None
        self._wired = False
        self._build_panel()
        self.timer = rumps.Timer(self._tick, config.get_float("poll_interval_seconds", 2.0))
        self.timer.start()

    def _build_panel(self) -> None:
        if panel is None:
            return
        callbacks = {
            "sensors": self._show_sensors,
            "clean": self._run_clean,
            "quit": self._quit,
            "fan_manual": self._panel_fan_manual,
            "fan_auto": self._restore_fan,
            "kill_process": self._panel_kill_process,
        }
        self._panel_view, self._popover = panel.build(callbacks)
        lo, hi = smc.fan_bounds()
        self._panel_view.applyFanRange_(lo, hi)
        self._panel_view.applyFanValue_(smc.fan_rpm())

    def _wire_status_item(self) -> None:
        """Take over the status-item clicks: left toggles the Vorssaint-style
        panel, right opens the classic tool menu. Runs once, after rumps has
        created the status item during ``run()``."""
        self._wired = True
        if panel is None or self._popover is None or _STATUS_BAR_CLICK is None:
            return
        nsapp = getattr(self, "_nsapp", None)
        if nsapp is None or not hasattr(nsapp, "nsstatusitem"):
            return
        si = nsapp.nsstatusitem
        button = si.button()
        if button is None:
            return
        self._nsmenu = si.menu()  # retained for the right-click menu
        si.setMenu_(None)
        handler = _STATUS_BAR_CLICK.alloc().initWithApp_(self)
        self._status_handler = handler
        button.setTarget_(handler)
        button.setAction_("handleClick:")
        button.setSendActionOn_(NSEventMaskLeftMouseUp | NSEventMaskRightMouseUp)
        if os.environ.get("MACMEDIC_PANEL_AUTOOPEN"):
            self._toggle_panel(button)

    def _status_clicked(self, sender) -> None:
        ev = NSApp.currentEvent() if NSApp is not None else None
        if ev is not None and ev.type() == 3:  # NSRightMouseUp
            self._open_menu(sender)
        else:
            self._toggle_panel(sender)

    def _open_menu(self, sender) -> None:
        if self._nsmenu is None:
            return
        self._nsmenu.popUpMenu_positionItem_atLocation_inView_(None, NSMakePoint(0, NSHeight(sender.bounds())), sender)

    def _toggle_panel(self, sender) -> None:
        if self._popover is None or panel is None:
            return
        if self._last_snap is not None:
            self._update_panel(self._last_snap)
        panel.show_popover(self._popover, sender)

    def _update_panel(self, snap) -> None:
        if self._panel_view is None:
            return
        battery = psutil.sensors_battery()
        bd = battery_detail()
        state = {
            "cpu_temp": smc.cpu_temperature(),
            "gpu_temp": smc.gpu_temperature(),
            "fan_rpm": smc.fan_rpm(),
            "cpu_pct": snap.cpu_percent,
            "mem_pct": snap.memory_percent,
            "mem_pressure": snap.memory_pressure,
            "battery_pct": float(battery.percent) if battery else None,
            "health_pct": getattr(bd, "health_percent", None),
            "cycles": getattr(bd, "cycles", None),
            "health_score": self._health_score,
            "cpu_history": list(self.history),
        }
        self._panel_view.update(state)
        self._panel_view.applyFanValue_(smc.fan_rpm())

    def _panel_fan_manual(self, rpm: float) -> None:
        rpm = float(rpm)
        if smc.set_fan_manual(rpm):
            if self._panel_view is not None:
                self._panel_view.applyFanValue_(rpm)
            rumps.notification("MacMedic", "Fan Control", f"Fan set to {rpm:.0f} RPM (manual).")
        else:
            rumps.notification("MacMedic", "Fan Control", "Could not set fan speed (permission or hardware).")

    def _panel_kill_process(self, info) -> None:
        self._handle_process_action(request_quit, info)

    def _proc_rows(self, infos, metric: str) -> list:
        rows = []
        for info in infos:
            name = info.app_name or info.name
            value = f"{info.cpu_percent:.0f}%" if metric == "cpu" else format_bytes(info.memory_rss)
            rows.append({"name": name, "value": value, "info": info})
        return rows

    def _detect_machine(self) -> str:
        _, _, machine = platform.mac_ver()
        return "Intel Mac" if machine.startswith(("x86_64", "i386")) else "Apple Silicon"

    def _build_menu(self) -> None:
        self._header = rumps.MenuItem(self._header_title(), callback=self._show_eol)
        agents_menu = rumps.MenuItem("Launch Agents")
        agents_menu.add(rumps.MenuItem("Refresh", callback=self._refresh_agents_now))
        agents_menu.add(rumps.separator)
        self._agents_menu = agents_menu

        cpu_menu = rumps.MenuItem("Top CPU")
        cpu_menu.add(rumps.MenuItem("Loading…"))
        self._cpu_menu = cpu_menu
        mem_menu = rumps.MenuItem("Top Memory")
        mem_menu.add(rumps.MenuItem("Loading…"))
        self._mem_menu = mem_menu

        self.menu.add(self._header)
        self.menu.add(rumps.separator)
        self.menu.add(cpu_menu)
        self.menu.add(mem_menu)
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Sensors…", callback=self._show_sensors))
        self.menu.add(rumps.MenuItem("Battery Trends…", callback=self._show_trends))
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Fan Control…", callback=self._show_fan_control))
        self.menu.add(rumps.MenuItem("Restore Automatic Fan", callback=self._restore_fan))
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Smart Clean…", callback=self._run_clean))
        self.menu.add(rumps.MenuItem("Orphaned App Data…", callback=self._run_debloat))
        self.menu.add(agents_menu)
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("About MacMedic", callback=self._show_about))
        if touchbar is not None and touchbar.available():
            self._tb_item = rumps.MenuItem("Touch Bar Widget", callback=self._toggle_touchbar)
            self._tb_item.state = bool(config.get("touchbar.enabled", True))
            self.menu.add(self._tb_item)
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Quit", callback=self._quit))

    def _tick(self, sender: object | None = None) -> None:
        try:
            infos = self.tracker.snapshot()
            self._top_cpu = top_by_cpu(infos, config.get_int("top_processes", 10))
            self._top_mem = top_by_memory(infos, config.get_int("top_processes", 10))
            self._rebuild_proc_menu(self._cpu_menu, self._top_cpu)
            self._rebuild_proc_menu(self._mem_menu, self._top_mem)
            snap = self.monitor.sample()
            self.history.append(snap.cpu_percent)
            text, color = self._format_status(snap)
            self._set_status_text(text, color, tooltip=snap)
            self._last_snap = snap
            if not self._wired:
                self._wire_status_item()
            if not self._touchbar_tried:
                self._touchbar_tried = True
                self._install_touchbar()
            if self._touchbar is not None:
                self._update_touchbar(snap)
            if self._popover is not None and self._popover.isShown():
                self._update_panel(snap)
                self._panel_view.update_processes(
                    self._proc_rows(self._top_cpu, "cpu"),
                    self._proc_rows(self._top_mem, "mem"),
                )
            self._agents_ticks_since_refresh += 1
            if self._agents_ticks_since_refresh >= AGENT_REFRESH_EVERY_TICKS:
                self._agents_ticks_since_refresh = 0
                threading.Thread(target=self._refresh_agents_background, daemon=True).start()
            if self._agents_dirty:
                self._agents_dirty = False
                self._rebuild_agents_menu()
            self._thermal_ticks += 1
            if self._thermal_ticks >= THERMAL_CHECK_EVERY_TICKS:
                self._thermal_ticks = 0
                self._check_thermal()
            self._health_ticks += 1
            if self._health_ticks >= HEALTH_REFRESH_EVERY_TICKS:
                self._health_ticks = 0
                self._refresh_health()
            self._record_trend()
        except Exception as exc:  # pragma: no cover - never crash silently
            log.exception("poll tick failed: %s", exc)

    def _refresh_health(self) -> None:
        try:
            score, _ = eol_fitness_score()
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("health score failed: %s", exc)
            return
        self._health_score = score
        try:
            self._header.title = self._header_title()
        except Exception:  # pragma: no cover - defensive
            pass

    def _header_title(self) -> str:
        if self._health_score is None:
            return f"MacMedic  ·  {self._machine_label}"
        return f"MacMedic  ·  {self._machine_label}  ·  Health {self._health_score}/100"

    def _format_status(self, snap):
        """Compact status text: a severity dot, CPU % with sparkline, RAM %."""
        cpu = snap.cpu_percent
        memory = snap.memory_percent
        text = f"● CPU {cpu:02.0f}%{sparkline(self.history)}  RAM {memory:02.0f}%"
        return text, _danger_color(cpu, memory, snap.memory_pressure)

    def _set_status_text(self, text: str, color, tooltip=None) -> None:
        """Render the status with a color and a hover tooltip, falling back to
        a plain rumps title if attributed titles are unavailable."""
        if NSAttributedString is None or color is None:
            self.title = text
            return
        try:
            attrs = {
                NSForegroundColorAttributeName: color,
                NSFontAttributeName: NSFont.menuBarFontOfSize_(0),
            }
            attributed = NSAttributedString.alloc().initWithString_attributes_(text, attrs)
            nsapp = getattr(self, "_nsapp", None)
            if nsapp is None or not hasattr(nsapp, "nsstatusitem"):
                self.title = text
                return
            nsapp.nsstatusitem.setAttributedTitle_(attributed)
            try:
                hint = text if tooltip is None else self._tooltip_text(tooltip)
                nsapp.nsstatusitem.setToolTip_(hint)
            except Exception:
                pass
        except Exception:  # pragma: no cover - defensive
            log.exception("could not set colored status text")
            self.title = text

    def _tooltip_text(self, snap) -> str:
        pressure = PRESSURE_LABELS.get(snap.memory_pressure, "?")
        return f"CPU {snap.cpu_percent:.0f}% · RAM {snap.memory_percent:.0f}% · memory pressure {pressure}"

    def _rebuild_proc_menu(self, menu: rumps.MenuItem, infos: list[ProcessInfo]) -> None:
        menu.clear()
        menu.add(rumps.MenuItem("● safe   ◐ caution   ✖ critical — don't quit"))
        menu.add(rumps.separator)
        if not infos:
            menu.add(rumps.MenuItem("No data"))
            return
        for info in infos:
            display_name = info.app_name or info.name
            title = (
                f"{SAFETY_BADGES[info.safety]} {display_name} · "
                f"CPU {info.cpu_percent:.0f}% · {format_bytes(info.memory_rss)}"
            )
            item = rumps.MenuItem(title)
            item.add(rumps.MenuItem(f"Path: {info.exe_path or (info.cmdline[0] if info.cmdline else '?')}"))
            item.add(rumps.MenuItem(f"{info.proc_type} · PID {info.pid} · User: {info.username}"))
            item.add(rumps.MenuItem(f"Safety: {SAFETY_LABELS[info.safety]}"))
            item.add(rumps.separator)
            item.add(rumps.MenuItem("Quit", callback=self._make_proc_callback(request_quit, info)))
            item.add(rumps.MenuItem("Force Quit", callback=self._make_proc_callback(request_force_quit, info)))
            menu.add(item)

    def _make_proc_callback(self, action, info: ProcessInfo):
        def callback(sender: object | None = None) -> None:
            self._handle_process_action(action, info)

        return callback

    def _handle_process_action(self, action, info: ProcessInfo) -> None:
        verb = "Force quit" if action is request_force_quit else "Quit"
        if info.safety != "safe":
            if info.safety == "critical":
                warning = (
                    f"'{info.app_name or info.name}' (PID {info.pid}) is a system-critical process "
                    f"({info.name}). Quitting it may destabilise your Mac.\n\n{verb} anyway?"
                )
            else:
                warning = (
                    f"'{info.app_name or info.name}' (PID {info.pid}) is a system helper "
                    f"({SAFETY_LABELS[info.safety]}).\n\n{verb} anyway?"
                )
            ok = rumps.alert("Confirm", warning, ok="Continue", cancel="Cancel")
            if not ok:
                return
        ok, message = action(info.pid)
        rumps.notification("MacMedic", f"{verb}: {info.name}", message)

    def _show_sensors(self, sender: object | None = None) -> None:
        rumps.alert("Sensors", sensors_report())

    def _show_fan_control(self, sender: object | None = None) -> None:
        fan = smc.fan_rpm()
        current = f"{fan:.0f} RPM" if fan is not None else "unavailable"
        lo, hi = smc.fan_bounds()
        proceed = rumps.alert(
            "Fan Control",
            f"Current fan: {current}\n\n"
            "Manual fan control overrides the SMC's automatic curve. Set the "
            "RPM too low and the Mac may overheat; the value is clamped to the "
            f"safe range {lo:.0f}–{hi:.0f} RPM.\n\nContinue?",
            ok="Continue",
            cancel="Cancel",
        )
        if not proceed:
            return
        window = rumps.Window(
            f"Target RPM ({lo:.0f}–{hi:.0f}):",
            title="Fan Control",
            default_text=f"{fan:.0f}" if fan is not None else "",
            ok="Set Manual",
            cancel="Cancel",
        )
        response = window.run()
        if not response.clicked:
            return
        try:
            rpm = float(response.text.strip())
        except ValueError:
            rumps.notification("MacMedic", "Fan Control", "Please enter a number.")
            return
        if rpm < lo or rpm > hi:
            rumps.notification(
                "MacMedic",
                "Fan Control",
                f"Target out of range — clamped to {lo:.0f}–{hi:.0f} RPM.",
            )
        if smc.set_fan_manual(rpm):
            rumps.notification("MacMedic", "Fan Control", f"Fan set to {max(lo, min(rpm, hi)):.0f} RPM (manual).")
        else:
            rumps.notification("MacMedic", "Fan Control", "Could not set fan speed (permission or hardware).")

    def _restore_fan(self, sender: object | None = None) -> None:
        if smc.restore_fan_auto():
            rumps.notification("MacMedic", "Fan Control", "Fan returned to automatic control.")
        else:
            rumps.notification("MacMedic", "Fan Control", "Could not restore automatic fan control.")

    def _check_thermal(self) -> None:
        """Notify on sustained high CPU temperature, throttled by a cooldown."""
        if not config.get("alerts.enabled", True):
            return
        temp = smc.cpu_temperature()
        if temp is None:
            return
        warn = config.get_float("thresholds.temp_warn_c", 85.0)
        crit = config.get_float("thresholds.temp_crit_c", 95.0)
        now = time.time()
        min_interval = config.get_float("alerts.min_interval_seconds", 300)
        if now - self._last_alert_time < min_interval:
            return
        if temp >= crit:
            self._last_alert_time = now
            rumps.notification("MacMedic", "Thermal", f"CPU at {temp:.0f} °C — critical. Check fans and airflow.")
        elif temp >= warn:
            self._last_alert_time = now
            rumps.notification("MacMedic", "Thermal", f"CPU at {temp:.0f} °C — getting hot.")

    def _show_eol(self, sender: object | None = None) -> None:
        rumps.alert("EOL Health Check", self._eol_report())

    def _eol_report(self) -> str:
        lines: list[str] = []
        version, _, machine = platform.mac_ver()
        lines.append(f"macOS: {version} (build {_macos_build() or '?'})")
        is_intel = machine.startswith(("x86_64", "i386"))
        lines.append(f"Chip: {'Intel' if is_intel else 'Apple Silicon / other'} ({machine})")
        if is_intel:
            try:
                major = int(version.split(".")[0])
            except (ValueError, AttributeError):
                major = 0
            if major >= 26:
                lines.append("Status: on the final macOS for Intel — enjoy the stable plateau.")
            else:
                lines.append("Status: past the Intel support window (macOS 26 was the last).")
        else:
            lines.append("Status: not an Intel Mac — EOL guidance may not apply.")

        score, verdict = eol_fitness_score()
        lines.append(f"Health score: {score}/100 — {verdict}")
        lines.append("")

        detail = self.monitor.battery_report()
        for line in detail.splitlines():
            if line.startswith(("Health:", "Cycles:", "Battery:")):
                lines.append(line)

        cpu_temp = smc.cpu_temperature()
        if cpu_temp is not None:
            fan = smc.fan_rpm()
            fan_text = f"{fan:.0f} RPM" if fan is not None else "n/a"
            lines.append(f"CPU temp: {cpu_temp:.1f} °C · Fan: {fan_text}")

        vm = psutil.virtual_memory()
        total_gb = vm.total / (1024**3)
        used_gb = vm.used / (1024**3)
        lines.append(f"RAM: {total_gb:.0f} GB — {used_gb:.1f} GB used ({vm.percent:.0f}%)")
        try:
            usage = shutil.disk_usage("/")
            free_gb = usage.free / (1024**3)
            lines.append(f"Disk free: {free_gb:.0f} GB")
        except OSError:
            pass

        lines.append("")
        lines.append("For an unsupported Intel Mac:")
        lines.append("• Trim launch agents — one click in this app's panel")
        lines.append("• Keep ≥15% disk free; a full disk makes macOS crawl")
        lines.append("• Reduce motion/transparency in Accessibility settings")
        lines.append("• Renew thermal paste every 4-6 years if temps climb")
        return "\n".join(lines)

    def _refresh_agents_now(self, sender: object | None = None) -> None:
        threading.Thread(target=self._refresh_agents_background, daemon=True).start()

    def _refresh_agents_background(self) -> None:
        try:
            self._agents = list_launch_agents()
            self._agents_dirty = True
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("agent refresh failed: %s", exc)

    def _rebuild_agents_menu(self) -> None:
        for key in list(self._agents_menu.keys()):
            if key != "Refresh":
                self._agents_menu.pop(key)
        if not self._agents:
            self._agents_menu.add(rumps.MenuItem("No launch agents found"))
            return
        for agent in self._agents:
            flag = f"  ⚠ {agent.match.category}" if agent.match else ""
            state = " (disabled)" if agent.disabled else ""
            item = rumps.MenuItem(f"{agent.label}{flag}{state}")
            item.add(rumps.MenuItem("Disable", callback=self._make_agent_callback(self._disable_agent, agent)))
            item.add(rumps.MenuItem("Reveal in Finder", callback=self._make_agent_callback(self._reveal_agent, agent)))
            self._agents_menu.add(item)

    def _make_agent_callback(self, func, agent: LaunchAgentInfo):
        def callback(sender: object | None = None) -> None:
            func(agent)

        return callback

    def _disable_agent(self, agent: LaunchAgentInfo) -> None:
        if agent.disabled:
            rumps.notification("MacMedic", "Launch Agent", f"'{agent.label}' is already disabled.")
            return
        if agent.match:
            question = (
                f"Disable launch agent '{agent.label}'?\n\n"
                f"Flagged as: {agent.match.reason}\n\n"
                f"It will be unloaded and moved to:\n{DISABLED_DIR}"
            )
        else:
            question = f"Disable launch agent '{agent.label}'?\n\nIt will be unloaded and moved to:\n{DISABLED_DIR}"
        ok = rumps.alert("Disable Launch Agent", question, ok="Disable", cancel="Cancel")
        if not ok:
            return
        success, message = disable_agent(agent)
        rumps.notification("MacMedic", "Launch Agent", message)
        self._agents_ticks_since_refresh = AGENT_REFRESH_EVERY_TICKS

    def _reveal_agent(self, agent: LaunchAgentInfo) -> None:
        reveal_in_finder(agent.path)

    def _run_clean(self, sender: object | None = None) -> None:
        proceed = rumps.alert(
            "Smart Clean",
            "MacMedic will now run a read-only scan — nothing is deleted yet.\n\n"
            "It checks:\n"
            "• App cache folders of 50 MB or more in ~/Library/Caches\n"
            "  (Apple and system-managed caches are skipped)\n"
            "• Log files older than 30 days in ~/Library/Logs and /var/log\n"
            "• Duplicate downloads of 1 MB or more in ~/Downloads\n"
            "  (verified by content hash, not just file name)\n\n"
            "Anything found is listed for your review. Deletion only happens "
            "after you confirm it. Start the scan?",
            ok="Start Scan",
            cancel="Cancel",
        )
        if not proceed:
            return
        rumps.notification("MacMedic", "Smart Clean", "Scanning caches, logs, and duplicates…")
        threading.Thread(target=self._clean_worker, daemon=True).start()

    def _clean_worker(self) -> None:
        try:
            items = scan()
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("clean scan failed: %s", exc)
            rumps.notification("MacMedic", "Smart Clean", f"Scan failed: {exc}")
            return
        if not items:
            rumps.notification("MacMedic", "Smart Clean", "Nothing to clean.")
            return
        total = total_size(items)
        kinds: dict[str, int] = {}
        for item in items:
            kinds[item.kind] = kinds.get(item.kind, 0) + 1
        kind_labels = {"cache": "app caches", "log": "log files", "duplicate": "duplicates"}
        breakdown = "   ".join(
            f"{count} {kind_labels.get(kind, kind)}" for kind, count in sorted(kinds.items(), key=lambda kv: -kv[1])
        )
        lines = "\n".join(f"• {item.reason}\n  {item.path}" for item in items[:10])
        if len(items) > 10:
            lines += f"\n… and {len(items) - 10} more"
        ok = rumps.alert(
            "Smart Clean",
            f"Scan complete — found {len(items)} items totalling {format_bytes(total)}.\n"
            f"{breakdown}\n\n"
            f"⚠ These will be permanently deleted — they are NOT moved to Trash.\n\n"
            f"{lines}\n\nDelete these items?",
            ok="Delete",
            cancel="Cancel",
        )
        if not ok:
            rumps.notification("MacMedic", "Smart Clean", "Cancelled — nothing was deleted.")
            return
        deleted = 0
        errors: list[str] = []
        for item in items:
            error = delete_item(item)
            if error:
                errors.append(f"{item.path}: {error}")
            else:
                deleted += 1
        message = f"Deleted {deleted} of {len(items)} items."
        if errors:
            message += "\n\nFailed:\n" + "\n".join(errors[:5])
        rumps.notification("MacMedic", "Smart Clean", message)

    def _run_debloat(self, sender: object | None = None) -> None:
        proceed = rumps.alert(
            "Orphaned App Data",
            "Scans ~/Library/Application Support for orphaned leftovers of apps "
            "that are no longer installed and haven't been touched in weeks.\n\n"
            "This scan is read-only — MacMedic will NOT delete anything it "
            "finds. It only reports candidates for you to inspect.\n\n"
            "Start the scan?",
            ok="Scan",
            cancel="Cancel",
        )
        if not proceed:
            return
        rumps.notification("MacMedic", "Orphaned App Data", "Scanning for orphaned app leftovers…")
        threading.Thread(target=self._debloat_worker, daemon=True).start()

    def _debloat_worker(self) -> None:
        try:
            items = debloat.scan_orphaned()
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("debloat scan failed: %s", exc)
            rumps.notification("MacMedic", "Orphaned App Data", f"Scan failed: {exc}")
            return
        if not items:
            rumps.notification("MacMedic", "Orphaned App Data", "No orphaned app leftovers found.")
            return
        total = sum(item.size for item in items)
        lines = "\n".join(f"• {item.app_name} — {format_bytes(item.size)}" for item in items[:12])
        if len(items) > 12:
            lines += f"\n… and {len(items) - 12} more"
        rumps.alert(
            "Orphaned App Data",
            f"Found {len(items)} orphaned app leftovers totalling {format_bytes(total)}.\n\n"
            f"{lines}\n\n"
            "These are suggestions only — review each one in Finder before "
            "removing anything manually.",
        )

    def _record_trend(self) -> None:
        """Write one battery/thermal sample at most once per configured interval."""
        now = time.time()
        interval = config.get_float("trends.interval_seconds", trends.DEFAULT_INTERVAL_SECONDS)
        if now - self._last_trend_time < interval:
            return
        battery = psutil.sensors_battery()
        percent = float(battery.percent) if battery else None
        detail = battery_detail()
        cpu = smc.cpu_temperature()
        fan = smc.fan_rpm()
        trends.record(percent, detail.health_percent, detail.cycles, detail.temperature_c, cpu, fan)
        trends.trim()
        self._last_trend_time = now

    def _show_trends(self, sender: object | None = None) -> None:
        rumps.alert("Battery Trends", trends.trend_report())

    def _show_about(self, sender: object | None = None) -> None:
        rumps.alert(
            "About MacMedic",
            f"MacMedic {__version__}\n\n"
            "A lightweight menu bar monitor and maintenance tool for Intel "
            "Macs nearing the end of Apple's support window.\n\n"
            "Uses ~30 MB, one 2-second polling loop, and nothing else running "
            "in the background.",
        )

    def _install_touchbar(self) -> None:
        """Attach the Control Strip chip once, after rumps is running.

        No-op on Macs without a Touch Bar, when the user has disabled it, or
        when the private Control Strip API is missing. Never raises.
        """
        if touchbar is None or not config.get("touchbar.enabled", True):
            return
        try:
            self._touchbar = touchbar.install(on_sensors=self._show_sensors, on_health=self._show_eol)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("touch bar install failed: %s", exc)
            self._touchbar = None

    def _update_touchbar(self, snap) -> None:
        if self._touchbar is None:
            return
        try:
            self._touchbar.update(
                {
                    "cpu": snap.cpu_percent,
                    "ram": snap.memory_percent,
                    "pressure": snap.memory_pressure,
                    "temp": smc.cpu_temperature(),
                    "fan": smc.fan_rpm(),
                    "health": self._health_score,
                    "cpu_warn": config.get_float("thresholds.cpu_warn_pct", 75.0),
                    "cpu_crit": config.get_float("thresholds.cpu_crit_pct", 90.0),
                    "ram_warn": config.get_float("thresholds.ram_warn_pct", 80.0),
                    "ram_crit": config.get_float("thresholds.ram_crit_pct", 92.0),
                    "temp_warn": config.get_float("thresholds.temp_warn_c", 85.0),
                    "temp_crit": config.get_float("thresholds.temp_crit_c", 95.0),
                }
            )
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("touch bar update failed: %s", exc)

    def _toggle_touchbar(self, sender) -> None:
        if touchbar is None:
            return
        if self._touchbar is not None:
            try:
                self._touchbar.teardown()
            except Exception:
                pass
            self._touchbar = None
            sender.state = False
            rumps.notification("MacMedic", "Touch Bar", "Widget hidden for this session.")
            return
        sender.state = True
        self._install_touchbar()
        if self._touchbar is None:
            sender.state = False
            rumps.notification("MacMedic", "Touch Bar", "Could not attach the widget on this Mac.")
        else:
            rumps.notification("MacMedic", "Touch Bar", "Widget added to the Control Strip. Tap it to expand.")
            if self._last_snap is not None:
                self._update_touchbar(self._last_snap)

    def _quit(self, sender: object | None = None) -> None:
        try:
            self.timer.stop()
        except Exception:
            pass
        if self._touchbar is not None:
            try:
                self._touchbar.teardown()
            except Exception:
                pass
            self._touchbar = None
        rumps.quit_application()


def _setup_logging() -> None:
    try:
        os.makedirs(os.path.dirname(config.LOG_FILE), exist_ok=True)
        if os.path.exists(config.LOG_FILE) and os.path.getsize(config.LOG_FILE) > config.LOG_MAX_BYTES:
            os.remove(config.LOG_FILE)
    except OSError:
        pass
    logging.basicConfig(
        filename=config.LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    def hook(exc_type, exc_value, exc_tb) -> None:
        logging.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))

    sys.excepthook = hook


def main() -> None:
    _setup_logging()
    try:
        MacMedicApp().run()
    except Exception as exc:  # pragma: no cover - defensive
        logging.critical("App exited: %s", exc)
        raise


if __name__ == "__main__":
    main()
