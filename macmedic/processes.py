"""Process discovery, ranking, and termination.

All ranking / criticality helpers are pure functions over plain data so they
can be unit tested without hitting the live process table.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass, field

import psutil

log = logging.getLogger("macmedic.processes")

SYSTEM_CRITICAL_NAMES: frozenset[str] = frozenset(
    {
        "launchd",
        "kernel_task",
        "kernelmanagerd",
        "WindowServer",
        "loginwindow",
        "securityd",
        "configd",
        "notifyd",
        "distnoted",
        "mds",
        "mdworker_shared",
        "mdworker",
        "coreaudiod",
        "syslogd",
        "opendirectoryd",
        "taskgated",
        "logd",
        "runningboardd",
        "backboardd",
        "amfid",
        "fseventsd",
        "coreservicesd",
        "syspolicyd",
        "sandboxd",
        "diskmanagementd",
        "powerd",
        "thermalmanagerd",
        "watchdogd",
        "symptomsd",
        "cfprefsd",
        "useractivityd",
    }
)

ROOT_USERNAMES: frozenset[str] = frozenset({"root", "_windowserver", "_coreaudiod", "_hidd", "_nsurlsessiond"})

_DAEMON_SUFFIXES: tuple[str, ...] = ("d", "helper", "agent", "server", "daemon", "watcher")


@dataclass
class ProcessInfo:
    pid: int
    name: str
    username: str
    cpu_percent: float
    memory_percent: float
    memory_rss: int
    status: str
    cmdline: tuple[str, ...] = field(default_factory=tuple)
    is_critical: bool = False
    exe_path: str = ""
    app_name: str = ""
    proc_type: str = "Process"
    safety: str = "safe"


SAFETY_LABELS: dict[str, str] = {
    "safe": "Safe to quit",
    "caution": "Caution — confirm before quitting",
    "critical": "Do not quit",
}

CAUTION_NAMES: frozenset[str] = frozenset(
    {
        "Finder",
        "Dock",
        "Spotlight",
        "ControlCenter",
        "NotificationCenter",
        "SystemUIServer",
        "softwareupdated",
        "storeagentd",
    }
)


def is_system_critical(name: str, username: str, cmdline: Sequence[str]) -> bool:
    """Best-effort guess that a process is important enough to guard."""
    if name in SYSTEM_CRITICAL_NAMES:
        return True
    if username in ROOT_USERNAMES:
        base = ""
        if cmdline and cmdline[0]:
            base = os.path.basename(cmdline[0]).lower()
        if base and base.endswith(_DAEMON_SUFFIXES):
            return True
    return False


def classify_safety(name: str, username: str, cmdline: Sequence[str], app_name: str, pid: int) -> str:
    """Three-tier safety rating: ``safe``, ``caution``, or ``critical``."""
    if pid == os.getpid() or app_name == "MacMedic":
        return "critical"
    if name in SYSTEM_CRITICAL_NAMES:
        return "critical"
    if username in ROOT_USERNAMES or name in CAUTION_NAMES:
        return "caution"
    return "safe"


def resolve_app_name(exe_path: str, cmdline: Sequence[str]) -> str:
    """Return the friendly application name behind a process, or ``""``."""
    candidates: list[str] = []
    if exe_path:
        candidates.append(exe_path)
    if cmdline:
        candidates.extend(arg for arg in cmdline if arg)
    for candidate in candidates:
        marker = candidate.find(".app/")
        if marker == -1:
            continue
        start = candidate.rfind("/", 0, marker) + 1
        bundle_name = candidate[start : marker + 4]
        name = os.path.splitext(os.path.basename(bundle_name))[0]
        if name:
            return name
    return ""


def classify_type(exe_path: str, cmdline: Sequence[str], username: str) -> str:
    path = exe_path or (cmdline[0] if cmdline else "")
    lowered = path.lower()
    if ".app/contents" in lowered or ".app/" in lowered:
        return "App"
    if "launchagents" in lowered or "launchdaemons" in lowered:
        return "LaunchAgent/Daemon"
    base = os.path.basename(path) if path else ""
    if username in ROOT_USERNAMES or (base and base.endswith("d")):
        return "Daemon"
    return "Process"


def top_by_cpu(infos: Sequence[ProcessInfo], n: int) -> list[ProcessInfo]:
    ranked = [i for i in infos if i.cpu_percent >= 0.0]
    ranked.sort(key=lambda i: i.cpu_percent, reverse=True)
    return ranked[:n]


def top_by_memory(infos: Sequence[ProcessInfo], n: int) -> list[ProcessInfo]:
    ranked = [i for i in infos if i.memory_percent >= 0.0]
    ranked.sort(key=lambda i: i.memory_percent, reverse=True)
    return ranked[:n]


class ProcessTracker:
    """Caches per-PID ``psutil.Process`` handles so ``cpu_percent(None)``
    returns the delta since the previous poll instead of a one-shot reading.
    """

    def __init__(self) -> None:
        self._procs: dict[int, psutil.Process] = {}

    def snapshot(self) -> list[ProcessInfo]:
        seen: set[int] = set()
        infos: list[ProcessInfo] = []
        try:
            iterator = psutil.process_iter(
                ["pid", "name", "username", "memory_percent", "memory_info", "status", "cmdline"]
            )
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("process_iter failed: %s", exc)
            return infos

        for proc in iterator:
            try:
                info = proc.info
                pid = info["pid"]
                seen.add(pid)
                handle = self._procs.get(pid)
                if handle is None:
                    handle = psutil.Process(pid)
                    self._procs[pid] = handle
                    handle.cpu_percent(None)
                    cpu = 0.0
                else:
                    cpu = handle.cpu_percent(None)
                memory_info = info.get("memory_info")
                rss = int(getattr(memory_info, "rss", 0) or 0)
                cmdline_tuple = tuple(str(arg) for arg in (info.get("cmdline") or []))
                exe_path = ""
                try:
                    exe_path = str(handle.exe() or "")
                except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                    pass
                except Exception:  # pragma: no cover - defensive
                    pass
                app_name = resolve_app_name(exe_path, cmdline_tuple)
                entry = ProcessInfo(
                    pid=pid,
                    name=str(info.get("name") or "?"),
                    username=str(info.get("username") or "?"),
                    cpu_percent=float(cpu or 0.0),
                    memory_percent=float(info.get("memory_percent") or 0.0),
                    memory_rss=rss,
                    status=str(info.get("status") or "?"),
                    cmdline=cmdline_tuple,
                    exe_path=exe_path,
                    app_name=app_name,
                    proc_type=classify_type(exe_path, cmdline_tuple, str(info.get("username") or "?")),
                )
                entry.safety = classify_safety(entry.name, entry.username, entry.cmdline, entry.app_name, entry.pid)
                entry.is_critical = entry.safety == "critical"
                infos.append(entry)
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except (psutil.AccessDenied, OSError):
                continue
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("skipping pid in snapshot: %s", exc)
                continue

        for pid in [pid for pid in self._procs if pid not in seen]:
            self._procs.pop(pid, None)
        return infos


def _terminate(pid: int, force: bool) -> tuple[bool, str]:
    if pid == os.getpid():
        return False, "Refusing to quit MacMedic itself."
    try:
        proc = psutil.Process(pid)
        if force:
            proc.kill()
        else:
            proc.terminate()
        try:
            proc.wait(timeout=3.0)
            return True, "Process has quit."
        except psutil.TimeoutExpired:
            verb = "Killed" if force else "Terminate signal sent"
            return True, f"{verb}; process still running."
    except psutil.NoSuchProcess:
        return False, "Process already exited."
    except psutil.AccessDenied:
        return False, "Permission denied (needs admin or Full Disk Access)."
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("terminate %s failed: %s", pid, exc)
        return False, f"Error: {exc}"


def request_quit(pid: int) -> tuple[bool, str]:
    return _terminate(pid, force=False)


def request_force_quit(pid: int) -> tuple[bool, str]:
    return _terminate(pid, force=True)


def is_running(pid: int) -> bool:
    try:
        return psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    except Exception:  # pragma: no cover - defensive
        return False
