import os
import time

import pytest

from macmedic import config, debloat

FIXTURE_DIR = "ZzOrphanScanFixture"


@pytest.fixture
def orphan_root(tmp_path, monkeypatch):
    root = tmp_path / "appsupport"
    root.mkdir()
    debloat.configure_for_tests(str(root))
    monkeypatch.setitem(config.SETTINGS["debloat"], "min_size", 1)
    yield root
    debloat.configure_for_tests(None)


def _make_dir(root, name, size=1024, mtime=None):
    path = os.path.join(str(root), name)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "data.bin"), "wb") as fh:
        fh.write(b"x" * size)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_finds_old_orphan(orphan_root):
    _make_dir(orphan_root, FIXTURE_DIR, mtime=time.time() - 40 * 86400)
    items = debloat.scan_orphaned()
    assert [i.app_name for i in items] == [FIXTURE_DIR]


def test_skips_recent_dirs(orphan_root):
    _make_dir(orphan_root, FIXTURE_DIR, mtime=time.time() - 3600)
    assert debloat.scan_orphaned() == []


def test_skips_system_and_apple_dirs(orphan_root):
    _make_dir(orphan_root, "Xcode", mtime=time.time() - 60 * 86400)
    _make_dir(orphan_root, "com.apple.test", mtime=time.time() - 60 * 86400)
    assert debloat.scan_orphaned() == []
