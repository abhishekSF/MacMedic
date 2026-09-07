"""Central configuration for MacMedic.

Settings live in ``~/Library/Application Support/MacMedic/config.json`` and are
deep-merged over the defaults below, so users can tune thresholds, scan rules,
and polling without touching code. Invalid JSON falls back to defaults silently.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger("macmedic.config")

CONFIG_PATH: str = os.path.expanduser("~/Library/Application Support/MacMedic/config.json")

DEFAULTS: dict[str, Any] = {
    "poll_interval_seconds": 2.0,
    "sparkline_len": 10,
    "top_processes": 10,
    "thresholds": {
        "cpu_warn_pct": 75.0,
        "cpu_crit_pct": 90.0,
        "ram_warn_pct": 80.0,
        "ram_crit_pct": 92.0,
        "temp_warn_c": 85.0,
        "temp_crit_c": 95.0,
    },
    "scan": {
        "cache_min_bytes": 50 * 1024 * 1024,
        "log_max_age_days": 30,
        "duplicate_min_bytes": 1024 * 1024,
        "duplicate_scan_dir": os.path.expanduser("~/Downloads"),
    },
    "debloat": {
        "min_size": 5 * 1024 * 1024,
        "min_age_days": 30,
        "max_recent_mod_days": 14,
    },
    "alerts": {
        "enabled": True,
        "min_interval_seconds": 300,
    },
    "touchbar": {
        "enabled": True,
    },
}

LOG_FILE: str = os.path.expanduser("~/Library/Logs/MacMedic.log")
LOG_MAX_BYTES: int = 1_000_000

CACHE_ROOT: str = os.path.expanduser("~/Library/Caches")
LOG_ROOTS: tuple[str, ...] = (
    os.path.expanduser("~/Library/Logs"),
    "/var/log",
)


def _deep_merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path: str = CONFIG_PATH) -> dict:
    settings = json.loads(json.dumps(DEFAULTS))
    try:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                user = json.load(fh)
            if isinstance(user, dict):
                _deep_merge(settings, user)
    except (OSError, ValueError) as exc:
        log.warning("could not read config %s: %s", path, exc)
    return settings


SETTINGS: dict[str, Any] = load_config()


def get(path: str, default: Any = None) -> Any:
    """Look up a dotted path such as ``thresholds.cpu_warn_pct``."""
    node: Any = SETTINGS
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def get_int(path: str, default: int) -> int:
    value = get(path, default)
    return int(value) if isinstance(value, (int, float)) else default


def get_float(path: str, default: float) -> float:
    value = get(path, default)
    return float(value) if isinstance(value, (int, float)) else default
