import os
import time

import pytest

from macmedic import config
from macmedic.scanner import CleanupItem, delete_item, scan_caches, scan_duplicates, scan_logs


@pytest.fixture
def scan_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_ROOT", str(tmp_path / "caches"))
    monkeypatch.setattr(config, "LOG_ROOTS", (str(tmp_path / "logs"),))
    monkeypatch.setitem(config.SETTINGS["scan"], "cache_min_bytes", 1)
    monkeypatch.setitem(config.SETTINGS["scan"], "log_max_age_days", 1)
    monkeypatch.setitem(config.SETTINGS["scan"], "duplicate_min_bytes", 1)
    return tmp_path


def _touch(path, size, mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"x" * size)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_scan_caches_finds_big_only(scan_settings):
    _touch(os.path.join(scan_settings, "caches", "BigApp", "big.bin"), 1024)
    _touch(os.path.join(scan_settings, "caches", "Tiny", "tiny.bin"), 0)
    items = scan_caches()
    assert [i.path for i in items] == [os.path.join(scan_settings, "caches", "BigApp")]
    assert items[0].kind == "cache"


def test_scan_logs_skips_fresh_files(scan_settings):
    old = _touch(os.path.join(scan_settings, "logs", "app", "old.log"), 10, time.time() - 3600 * 48)
    _touch(os.path.join(scan_settings, "logs", "app", "new.log"), 10, time.time())
    items = scan_logs()
    assert [i.path for i in items] == [old]


def test_scan_duplicates_keeps_newest(scan_settings):
    dup_root = os.path.join(scan_settings, "downloads")
    older = _touch(os.path.join(dup_root, "sub-a", "file.bin"), 100, time.time() - 3600)
    newer = _touch(os.path.join(dup_root, "sub-b", "file.bin"), 100, time.time())
    items = scan_duplicates(dup_root)
    assert len(items) == 1
    assert items[0].path == older
    assert os.path.basename(newer) == "file.bin"


def test_delete_item_removes_file(scan_settings):
    target = _touch(os.path.join(scan_settings, "caches", "App", "gone.bin"), 10)
    item = CleanupItem(path=target, size=10, kind="cache", reason="test")
    assert delete_item(item) is None
    assert not os.path.exists(target)


def test_delete_item_refuses_protected_paths(scan_settings):
    item = CleanupItem(path=config.CACHE_ROOT, size=1, kind="cache", reason="test")
    assert delete_item(item) == "Refusing to delete a protected path."
    item = CleanupItem(path=str(scan_settings), size=1, kind="cache", reason="test")
    assert delete_item(item) is None
