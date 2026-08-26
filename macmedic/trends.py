"""Long-term battery and thermal trend recording.

One row is written at most every ``interval_seconds`` while the app runs, so
the database stays tiny (a year of hourly samples is ~8,700 rows). The store is
created under ``~/Library/Application Support/MacMedic/trends.db``.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from dataclasses import dataclass

log = logging.getLogger("macmedic.trends")

TRENDS_DB_PATH: str = os.path.expanduser("~/Library/Application Support/MacMedic/trends.db")
DEFAULT_INTERVAL_SECONDS = 3600  # one sample per hour


@dataclass(frozen=True)
class TrendSummary:
    samples: int
    percent_min: float | None
    percent_max: float | None
    percent_avg: float | None
    temp_min_c: float | None
    temp_max_c: float | None
    temp_avg_c: float | None
    days_span: int | None


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(TRENDS_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(TRENDS_DB_PATH, timeout=5)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS battery ("
        "ts REAL PRIMARY KEY,"
        "percent REAL,"
        "health REAL,"
        "cycles INTEGER,"
        "temp_c REAL,"
        "cpu_c REAL,"
        "fan_rpm REAL"
        ")"
    )
    return conn


def record(
    percent: float | None,
    health: float | None,
    cycles: int | None,
    battery_temp: float | None,
    cpu_temp: float | None,
    fan_rpm: float | None,
) -> None:
    if percent is None:
        return
    try:
        conn = _connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO battery (ts, percent, health, cycles, temp_c, cpu_c, fan_rpm)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (time.time(), percent, health, cycles, battery_temp, cpu_temp, fan_rpm),
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as exc:  # pragma: no cover - defensive
        log.debug("trend record failed: %s", exc)


def trim(keep_days: int = 365) -> None:
    try:
        conn = _connect()
        try:
            conn.execute("DELETE FROM battery WHERE ts < ?", (time.time() - keep_days * 86400,))
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as exc:  # pragma: no cover - defensive
        log.debug("trend trim failed: %s", exc)


def summary(days: int = 30) -> TrendSummary:
    try:
        conn = _connect()
        try:
            since = time.time() - days * 86400
            row = conn.execute(
                "SELECT COUNT(*), MIN(percent), MAX(percent), AVG(percent),"
                " MIN(temp_c), MAX(temp_c), AVG(temp_c),"
                " (MAX(ts) - MIN(ts)) / 86400.0"
                " FROM battery WHERE ts >= ?",
                (since,),
            ).fetchone()
            if not row or not row[0]:
                return TrendSummary(0, None, None, None, None, None, None, None)
            span = int(row[7]) if row[7] is not None else 0
            return TrendSummary(
                samples=row[0],
                percent_min=row[1],
                percent_max=row[2],
                percent_avg=row[3],
                temp_min_c=row[4],
                temp_max_c=row[5],
                temp_avg_c=row[6],
                days_span=span,
            )
        finally:
            conn.close()
    except sqlite3.Error as exc:  # pragma: no cover - defensive
        log.debug("trend summary failed: %s", exc)
        return TrendSummary(0, None, None, None, None, None, None, None)


def trend_report() -> str:
    """Human-readable 30-day trend summary for the panel."""
    summary_30 = summary(30)
    lines: list[str] = []
    if summary_30.samples == 0:
        lines.append("No trend data yet — MacMedic records battery/thermal")
        lines.append("samples hourly while it runs.")
    else:
        lines.append(f"Samples (30 days): {summary_30.samples}")
        lines.append(
            f"Battery range: {_fmt(summary_30.percent_min)}% – {_fmt(summary_30.percent_max)}%"
            f" (avg {_fmt(summary_30.percent_avg)}%)"
        )
        if summary_30.temp_max_c is not None:
            lines.append(
                f"Battery temp: {_fmt(summary_30.temp_min_c)} – {_fmt(summary_30.temp_max_c)} °C"
                f" (avg {_fmt(summary_30.temp_avg_c)} °C)"
            )
        lines.append(f"Data spans {summary_30.days_span} day(s).")
    lines.append("")
    lines.append(f"Database: {TRENDS_DB_PATH}")
    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return f"{value:.0f}" if value is not None else "—"


def configure_for_tests(path: str) -> None:
    """Point the trend store at a temporary database (used only by tests)."""
    global TRENDS_DB_PATH
    TRENDS_DB_PATH = path
