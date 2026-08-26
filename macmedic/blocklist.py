"""Built-in blocklist of common bloatware / telemetry launch agents.

Matching is deliberately simple substring-regex so it stays easy to reason
about and unit test. Apple-owned agents are never flagged by default.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

APPLE_PREFIX = "com.apple."


@dataclass(frozen=True)
class BlocklistEntry:
    pattern: str
    category: str
    reason: str


BLOCKLIST: tuple[BlocklistEntry, ...] = (
    BlocklistEntry(r"adobe|macromedia", "Adobe", "Adobe update / helper agent"),
    BlocklistEntry(r"creative.?cloud", "Adobe", "Adobe Creative Cloud helper"),
    BlocklistEntry(r"googleupdate|keystone|ksoftwareupdate", "Update", "Google software updater"),
    BlocklistEntry(
        r"microsoft\.autoupdate|\.update\..*microsoft|microsoft.*update",
        "Update",
        "Microsoft auto-update agent",
    ),
    BlocklistEntry(r"java.*update|com\.oracle\.java", "Update", "Java update checker"),
    BlocklistEntry(
        r"norton|symantec|mcafee|avg(?!.*free)|avast|kaspersky|bitdefender",
        "Security",
        "Third-party security / antivirus bloat",
    ),
    BlocklistEntry(
        r"mackeeper|genieo|sparkling|webcake|bndver|vsearch|excelm|searchprotect|brightnessmenu",
        "Adware",
        "Known adware / crapware",
    ),
    BlocklistEntry(r"backup.?and.?sync|google.?drive|dropbox|onedrive", "Backup", "Cloud backup / sync agent"),
    BlocklistEntry(
        r"telemetry|diagnostic|crash.?reporter|feedback.?assistant|hang.?reporter",
        "Telemetry",
        "Telemetry / diagnostics agent",
    ),
    BlocklistEntry(r"update.?checker|autoupdate|auto.?update", "Update", "Generic update checker"),
    BlocklistEntry(
        r"teamviewer|logmein|gotomypc|remote.?desktop",
        "Remote",
        "Remote access agent (confirm before disabling)",
    ),
)


_COMPILED: list[tuple[re.Pattern[str], BlocklistEntry]] = [
    (re.compile(entry.pattern, re.IGNORECASE), entry) for entry in BLOCKLIST
]


def match_blocklist(text: str | None, apple_is_ok: bool = True) -> BlocklistEntry | None:
    """Return the first blocklist entry matching *text*, or ``None``.

    When *apple_is_ok* is true, ``com.apple.*`` agents are never flagged so
    the tool does not alarm on normal system helpers.
    """
    if not text:
        return None
    lowered = text.lower().strip()
    if apple_is_ok and lowered.startswith(APPLE_PREFIX):
        return None
    for pattern, entry in _COMPILED:
        if pattern.search(lowered):
            return entry
    return None


def flag_reasons_for(text: str, apple_is_ok: bool = True) -> tuple[str, ...]:
    entry = match_blocklist(text, apple_is_ok=apple_is_ok)
    if entry is None:
        return ()
    return (entry.reason,)
