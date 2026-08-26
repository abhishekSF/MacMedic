"""Low-overhead system sampling: CPU, memory pressure, battery, and thermal.

CPU and memory pressure are polled every two seconds, so they must be cheap.
``sysctlbyname`` is called through ctypes to avoid spawning a subprocess per
tick. Anything heavier (ioreg, powermetrics) only runs when the user opens the
battery / thermal panel.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
import re
import subprocess
from dataclasses import dataclass

import psutil

from . import smc

log = logging.getLogger("macmedic.monitors")

PRESSURE_LABELS: dict[int, str] = {1: "OK", 2: "WARN", 3: "HIGH", 4: "CRIT"}

_libc = None
_libc_failed = False


def _libc_handle():
    global _libc, _libc_failed
    if _libc is None and not _libc_failed:
        path = ctypes.util.find_library("c")
        if path:
            try:
                _libc = ctypes.CDLL(path, use_errno=True)
                _libc.sysctlbyname.argtypes = [
                    ctypes.c_char_p,
                    ctypes.c_void_p,
                    ctypes.POINTER(ctypes.c_size_t),
                    ctypes.c_void_p,
                    ctypes.c_size_t,
                ]
                _libc.sysctlbyname.restype = ctypes.c_int
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("could not load libc: %s", exc)
                _libc_failed = True
        else:  # pragma: no cover - defensive
            _libc_failed = True
    return _libc


def sysctl_int(name: str) -> int | None:
    libc = _libc_handle()
    if libc is None:
        return None
    try:
        value = ctypes.c_uint32()
        size = ctypes.c_size_t(ctypes.sizeof(value))
        if libc.sysctlbyname(name.encode(), ctypes.byref(value), ctypes.byref(size), None, 0) == 0:
            return int(value.value)
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("sysctl %s failed: %s", name, exc)
    return None


@dataclass(frozen=True)
class SystemSnapshot:
    cpu_percent: float
    memory_percent: float
    memory_pressure: int
    swap_percent: float
    battery_percent: float | None
    power_plugged: bool | None


@dataclass(frozen=True)
class BatteryDetail:
    health_percent: float | None
    cycles: int | None
    temperature_c: float | None


class SystemMonitor:
    def __init__(self) -> None:
        psutil.cpu_percent(None)

    def sample(self) -> SystemSnapshot:
        cpu = float(psutil.cpu_percent(None) or 0.0)
        vm = psutil.virtual_memory()
        memory = float(vm.percent or 0.0)
        swap = psutil.swap_memory()
        swap_pct = float(swap.percent if swap else 0.0)
        battery = psutil.sensors_battery()
        return SystemSnapshot(
            cpu_percent=cpu,
            memory_percent=memory,
            memory_pressure=self._memory_pressure(swap_pct),
            swap_percent=swap_pct,
            battery_percent=float(battery.percent) if battery else None,
            power_plugged=bool(battery.power_plugged) if battery else None,
        )

    def _memory_pressure(self, swap_percent: float) -> int:
        level = sysctl_int("kern.memorystatus_vm_pressure_level")
        if level is not None and 1 <= level <= 4:
            return level
        if swap_percent >= 60.0:
            return 2
        return 1

    def battery_report(self) -> str:
        lines: list[str] = []
        battery = psutil.sensors_battery()
        if battery is not None:
            state = "Plugged in" if battery.power_plugged else "On battery"
            lines.append(f"Battery: {int(battery.percent)}% ({state})")
        detail = _ioreg_battery()
        if detail.health_percent is not None:
            lines.append(f"Health: {detail.health_percent:.0f}% of design capacity")
        if detail.cycles is not None:
            lines.append(f"Cycles: {detail.cycles}")
        if detail.temperature_c is not None:
            lines.append(f"Battery temp: {detail.temperature_c:.1f} °C")
        cpu_temp = smc.cpu_temperature()
        if cpu_temp is not None:
            lines.append(f"CPU temp: {cpu_temp:.1f} °C")
        gpu_temp = smc.gpu_temperature()
        if gpu_temp is not None:
            lines.append(f"GPU temp: {gpu_temp:.1f} °C")
        if not lines:
            lines.append("Battery sensor data unavailable.")
        fan = get_fan_rpm()
        if fan is not None:
            lines.append(f"Fan: {fan:.0f} RPM")
        else:
            lines.append("Fan speed unavailable on this machine.")
        thermal = get_thermal_state()
        if thermal:
            lines.append(thermal)
        lines.append(_health_note(detail))
        return "\n".join(lines)


def battery_detail() -> BatteryDetail:
    return _ioreg_battery()


def _ioreg_battery() -> BatteryDetail:
    try:
        result = subprocess.run(
            ["ioreg", "-rn", "AppleSmartBattery"],
            capture_output=True,
            text=True,
            timeout=4,
        )
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("ioreg battery failed: %s", exc)
        return BatteryDetail(None, None, None)
    if result.returncode != 0:
        return BatteryDetail(None, None, None)

    def get_num(key: str) -> int | None:
        match = re.search('"' + re.escape(key) + r'"\s*=\s*(\d+)', result.stdout)
        return int(match.group(1)) if match else None

    get_num("AppleRawCurrentCapacity") or get_num("CurrentCapacity")
    maximum = get_num("AppleRawMaxCapacity") or get_num("MaxCapacity")
    design = get_num("AppleRawDesignCapacity") or get_num("DesignCapacity")
    cycles = get_num("CycleCount")
    raw_temp = get_num("Temperature")

    health = None
    if maximum is not None and design and design > 0:
        health = (maximum / design) * 100.0
    temperature = None
    if raw_temp is not None:
        celsius = raw_temp / 100.0
        if 0.0 <= celsius <= 100.0:
            temperature = celsius
    return BatteryDetail(health, cycles, temperature)


def get_fan_rpm() -> float | None:
    value = smc.fan_rpm(0)
    if value is not None:
        return value
    if os.geteuid() != 0:
        return None
    try:
        result = subprocess.run(
            ["powermetrics", "-n", "1", "-s", "smc"],
            capture_output=True,
            text=True,
            timeout=6,
        )
        match = re.search(r"Fan:\s+(\d+)\s+rpm", result.stdout)
        if match:
            return float(match.group(1))
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("powermetrics failed: %s", exc)
    return None


def get_thermal_state() -> str | None:
    level = sysctl_int("machdep.xcpm.cpu_thermal_level")
    if level in (2, 3, 4):
        return f"Thermal: throttling (level {level})"
    if level == 1:
        return "Thermal: nominal"
    if level is not None:
        log.debug("unexpected cpu_thermal_level=%s; ignoring", level)
    try:
        result = subprocess.run(["pmset", "-g", "therm"], capture_output=True, text=True, timeout=3)
        if result.returncode == 0 and "CPU speed limit" in result.stdout:
            for line in result.stdout.splitlines():
                if line.strip().lower().startswith("cpu speed limit") and not line.rstrip().endswith("0"):
                    return "Thermal: throttling active"
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("pmset therm failed: %s", exc)
    return None


def _health_note(detail: BatteryDetail) -> str:
    if detail.health_percent is None:
        return "Health note: no sensor data available."
    if detail.health_percent >= 80:
        return f"Health note: {detail.health_percent:.0f}% capacity — reasonable for its age."
    if detail.health_percent >= 60:
        return f"Health note: {detail.health_percent:.0f}% capacity — degrading; prefer to keep it plugged in."
    return f"Health note: {detail.health_percent:.0f}% capacity — consider battery service."


def sensors_report() -> str:
    """One-shot panel readout: battery, thermals, per-core temps, power, fan."""
    lines: list[str] = []
    battery = psutil.sensors_battery()
    if battery is not None:
        state = "Plugged in" if battery.power_plugged else "On battery"
        lines.append(f"Battery: {int(battery.percent)}% ({state})")
    detail = _ioreg_battery()
    if detail.health_percent is not None:
        lines.append(f"Health: {detail.health_percent:.0f}% of design capacity")
    if detail.cycles is not None:
        lines.append(f"Cycles: {detail.cycles}")
    if detail.temperature_c is not None:
        lines.append(f"Battery temp: {detail.temperature_c:.1f} °C")
    cpu_temp = smc.cpu_temperature()
    if cpu_temp is not None:
        lines.append(f"CPU package: {cpu_temp:.1f} °C")
    cores = smc.core_temps()
    for key, value in cores.items():
        lines.append(f"  Core {key}: {value:.0f} °C")
    gpu_temp = smc.gpu_temperature()
    if gpu_temp is not None:
        lines.append(f"GPU: {gpu_temp:.1f} °C")
    power = smc.power_readings()
    if power:
        parts = []
        if "system_w" in power:
            parts.append(f"System {power['system_w']:.1f} W")
        if "cpu_w" in power:
            parts.append(f"CPU {power['cpu_w']:.1f} W")
        if "gpu_w" in power:
            parts.append(f"GPU {power['gpu_w']:.1f} W")
        if "disk_w" in power:
            parts.append(f"Disk {power['disk_w']:.1f} W")
        lines.append("Power: " + " · ".join(parts))
    fan = get_fan_rpm()
    if fan is not None:
        lines.append(f"Fan: {fan:.0f} RPM")
    thermal = get_thermal_state()
    if thermal:
        lines.append(thermal)
    if not lines:
        lines.append("Sensor data unavailable on this machine.")
    lines.append(_health_note(detail))
    return "\n".join(lines)


def eol_fitness_score() -> tuple[int, str]:
    """Score the machine 0-100 for EOL usability, plus a one-line verdict.

    Weights: CPU thermal headroom 30, RAM 25, disk 25, battery 20.
    """
    score = 0
    notes: list[str] = []

    cpu_temp = smc.cpu_temperature()
    if cpu_temp is None:
        notes.append("thermal sensors unavailable")
    elif cpu_temp >= 95:
        notes.append("CPU very hot")
    elif cpu_temp >= 85:
        notes.append("CPU hot")
        score += 15
    elif cpu_temp >= 75:
        notes.append("CPU warm")
        score += 25
    else:
        score += 30

    memory = psutil.virtual_memory()
    if memory.percent >= 92:
        notes.append("RAM nearly exhausted")
    elif memory.percent >= 80:
        notes.append("RAM tight")
        score += 15
    else:
        score += 25

    disk = psutil.disk_usage("/")
    if disk.percent >= 95:
        notes.append("disk nearly full")
    elif disk.percent >= 85:
        notes.append("disk filling up")
        score += 15
    else:
        score += 25

    battery = _ioreg_battery()
    if battery.health_percent is None:
        notes.append("battery health unknown")
    elif battery.health_percent >= 80:
        score += 20
    elif battery.health_percent >= 60:
        score += 10
        notes.append("battery degrading")
    else:
        notes.append("battery needs service")

    if score >= 75:
        verdict = "In good shape for daily use."
    elif score >= 50:
        verdict = "Usable, but plan upgrades carefully."
    else:
        verdict = "Struggling; prioritize thermals, RAM, or storage."
    if notes:
        verdict += f" ({', '.join(notes)})"
    return score, verdict
