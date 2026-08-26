"""Deep-debloat scan for EOL Intel Macs.

Finds likely **orphaned** app-leftover folders under ``~/Library/Application
Support``: directories whose owning app is no longer installed, that are not
owned by a running process, and that have been untouched for weeks.

This scan is deliberately conservative and **read-only**. Anything listed is a
suggestion to inspect, not something MacMedic deletes. False positives are
possible (a directory is shared by a still-installed helper), so candidates are
only ever surfaced with an "open in Finder" action.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

import psutil

from . import config

log = logging.getLogger("macmedic.debloat")

# Always-present, system-managed, or vendor-shared support directories that
# must never be reported as orphans.
SYSTEM_SUPPORT_DIRS: frozenset[str] = frozenset(
    {
        "AddressBook",
        "App Store",
        "Apple",
        "CallHistoryDB",
        "CloudDocs",
        "Containers",
        "CoreDuet",
        "CrashReporter",
        "FamilyCircle",
        "Group Containers",
        "Knowledge",
        "MobileSync",
        "Preferences",
        "Printers",
        "SyncServices",
        "WebKit",
        "Xcode",
    }
)

ORPHAN_MIN_SIZE = 5 * 1024 * 1024  # 5 MB
ORPHAN_MIN_AGE_DAYS = 30
ORPHAN_MAX_RECENT_MOD_DAYS = 14


@dataclass(frozen=True)
class OrphanItem:
    path: str
    app_name: str
    size: int


def _installed_app_names() -> set[str]:
    names: set[str] = set()
    roots = ("/Applications", os.path.expanduser("~/Applications"))
    for root in roots:
        try:
            entries = os.listdir(root)
        except OSError:
            continue
        for entry in entries:
            if entry.lower().endswith(".app"):
                names.add(entry[: -len(".app")].lower())
    return names


def _running_app_names() -> set[str]:
    names: set[str] = set()
    for proc in psutil.process_iter(["name"]):
        try:
            name = proc.info.get("name")
        except (psutil.Error, OSError):
            continue
        if name:
            stem = os.path.splitext(name)[0]
            names.add(stem.lower())
            if stem.endswith("Helper") and len(stem) > len("Helper"):
                names.add(stem[: -len("Helper")].lower())
    return names


def scan_orphaned() -> list[OrphanItem]:
    root = _support_root()
    if not os.path.isdir(root):
        return []
    installed = _installed_app_names()
    running = _running_app_names()
    now = time.time()
    min_age = config.get_int("debloat.min_age_days", ORPHAN_MIN_AGE_DAYS) * 86400
    recent_mod = config.get_int("debloat.max_recent_mod_days", ORPHAN_MAX_RECENT_MOD_DAYS) * 86400
    min_size = config.get_int("debloat.min_size", ORPHAN_MIN_SIZE)
    candidates: list[OrphanItem] = []

    try:
        entries = sorted(os.listdir(root))
    except OSError as exc:
        log.debug("orphan scan root: %s", exc)
        return []

    for entry in entries:
        if entry.startswith(".") or entry in SYSTEM_SUPPORT_DIRS:
            continue
        if entry.lower().startswith("com.apple.") or entry.startswith("com.microsoft."):
            continue
        path = os.path.join(root, entry)
        if os.path.islink(path) or not os.path.isdir(path):
            continue
        app_key = entry.lower()
        if app_key in installed or app_key in running:
            continue
        try:
            stat = os.stat(path)
        except OSError:
            continue
        if now - stat.st_mtime < min_age:
            continue
        if now - stat.st_mtime < recent_mod:
            continue
        size = _dir_size(path)
        if size < min_size:
            continue
        candidates.append(OrphanItem(path=path, app_name=entry, size=size))

    candidates.sort(key=lambda item: item.size, reverse=True)
    return candidates


def _dir_size(path: str) -> int:
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for filename in filenames:
                try:
                    total += os.lstat(os.path.join(dirpath, filename)).st_size
                except OSError:
                    continue
    except OSError as exc:
        log.debug("dir size %s: %s", path, exc)
    return total


def reveal_in_finder(path: str) -> None:
    try:
        import subprocess

        subprocess.run(["open", "-R", path], check=False)
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("reveal failed: %s", exc)


def configure_for_tests(root: str) -> None:
    """Point the orphan scan at a temporary root (used only by tests)."""
    global _ORPHAN_ROOT
    _ORPHAN_ROOT = root


_ORPHAN_ROOT: str | None = None


def _support_root() -> str:
    if _ORPHAN_ROOT is not None:
        return _ORPHAN_ROOT
    return os.path.join(os.path.expanduser("~"), "Library", "Application Support")
