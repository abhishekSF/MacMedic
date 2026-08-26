"""Rule-based cleaning scanner.

Never deletes anything itself. It only reports candidates; the menu bar shell
always asks for explicit confirmation before calling ``delete_item``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import stat
import time
from dataclasses import dataclass

from . import config

log = logging.getLogger("macmedic.scanner")


@dataclass(frozen=True)
class CleanupItem:
    path: str
    size: int
    kind: str
    reason: str


def format_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{value:.0f} B"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} PB"


def _dir_size(root: str, cap: int = 2 * 1024 * 1024 * 1024) -> int:
    total = 0
    try:
        with os.scandir(root) as iterator:
            for entry in iterator:
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        total += _dir_size(entry.path, cap)
                    elif entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
                if total >= cap:
                    return total
    except OSError as exc:
        log.debug("dir_size %s: %s", root, exc)
    return total


def scan_caches() -> list[CleanupItem]:
    items: list[CleanupItem] = []
    if not os.path.isdir(config.CACHE_ROOT):
        return items
    try:
        names = sorted(os.listdir(config.CACHE_ROOT))
    except OSError as exc:
        log.debug("scan caches: %s", exc)
        return items
    min_bytes = config.get_int("scan.cache_min_bytes", 50 * 1024 * 1024)
    for name in names:
        if name.startswith("com.apple.") or name.startswith("."):
            continue
        path = os.path.join(config.CACHE_ROOT, name)
        try:
            if os.path.islink(path) or not os.path.isdir(path):
                continue
        except OSError:
            continue
        size = _dir_size(path)
        if size >= min_bytes:
            items.append(
                CleanupItem(
                    path=path,
                    size=size,
                    kind="cache",
                    reason=f"App cache folder ({format_bytes(size)})",
                )
            )
    return items


def scan_logs(older_than_days: int | None = None) -> list[CleanupItem]:
    items: list[CleanupItem] = []
    if older_than_days is None:
        older_than_days = config.get_int("scan.log_max_age_days", 30)
    cutoff = time.time() - older_than_days * 86400
    for root in config.LOG_ROOTS:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for filename in filenames:
                path = os.path.join(dirpath, filename)
                try:
                    st = os.lstat(path)
                except OSError:
                    continue
                if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                    continue
                if st.st_mtime > time.time() or st.st_mtime > cutoff:
                    continue
                items.append(
                    CleanupItem(
                        path=path,
                        size=st.st_size,
                        kind="log",
                        reason=f"Old log file (>{older_than_days} days)",
                    )
                )
    return items


def _chunk_hash(path: str) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            digest.update(fh.read(65536))
    except OSError:
        return ""
    return digest.hexdigest()


def _newest(paths: list[str]) -> str:
    def mtime(path: str) -> float:
        try:
            return os.stat(path, follow_symlinks=False).st_mtime
        except OSError:
            return 0.0

    return max(paths, key=mtime)


def scan_duplicates(directory: str | None = None) -> list[CleanupItem]:
    items: list[CleanupItem] = []
    if directory is None:
        directory = str(config.get("scan.duplicate_scan_dir", os.path.expanduser("~/Downloads")))
    if not os.path.isdir(directory):
        return items
    min_bytes = config.get_int("scan.duplicate_min_bytes", 1024 * 1024)
    groups: dict[tuple[str, int], list[str]] = {}
    try:
        walker = os.walk(directory)
        for root, dirnames, filenames in walker:
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for filename in filenames:
                path = os.path.join(root, filename)
                try:
                    st = os.lstat(path)
                except OSError:
                    continue
                if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                    continue
                if st.st_size < min_bytes:
                    continue
                groups.setdefault((filename, st.st_size), []).append(path)
    except OSError as exc:
        log.debug("duplicates walk: %s", exc)
        return items

    for (_, size), paths in groups.items():
        if len(paths) < 2:
            continue
        by_hash: dict[str, list[str]] = {}
        for path in paths:
            digest = _chunk_hash(path)
            if not digest:
                continue
            by_hash.setdefault(digest, []).append(path)
        for duplicate_group in by_hash.values():
            if len(duplicate_group) < 2:
                continue
            keeper = _newest(duplicate_group)
            for path in duplicate_group:
                if path == keeper:
                    continue
                items.append(
                    CleanupItem(
                        path=path,
                        size=size,
                        kind="duplicate",
                        reason=f"Duplicate of '{os.path.basename(keeper)}' ({format_bytes(size)})",
                    )
                )
    return items


def scan() -> list[CleanupItem]:
    items: list[CleanupItem] = []
    items.extend(scan_caches())
    items.extend(scan_logs())
    items.extend(scan_duplicates())
    items.sort(key=lambda item: item.size, reverse=True)
    return items


def total_size(items: list[CleanupItem]) -> int:
    return sum(item.size for item in items)


def delete_item(item: CleanupItem) -> str | None:
    """Delete one item. Returns an error string on failure, or ``None`` on success."""
    path = item.path
    home = os.path.expanduser("~")
    if path == home or path == config.CACHE_ROOT:
        return "Refusing to delete a protected path."
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        return str(exc)
    if stat.S_ISLNK(st.st_mode):
        return "Skipped symlink."
    try:
        if stat.S_ISDIR(st.st_mode):
            import shutil

            shutil.rmtree(path)
        else:
            os.remove(path)
    except OSError as exc:
        return str(exc)
    return None
