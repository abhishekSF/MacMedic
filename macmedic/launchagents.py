"""Launch agents and login items: discovery, flagging, and safe disabling.

Disabling works by unloading the agent from launchd and moving its plist out
of the search path, which both stops it now and keeps it from auto-starting on
the next login. Nothing is ever removed, only relocated, so it is reversible.
"""

from __future__ import annotations

import logging
import os
import plistlib
import subprocess
from dataclasses import dataclass

from .blocklist import BlocklistEntry, match_blocklist

log = logging.getLogger("macmedic.launchagents")

USER_AGENTS_DIR = os.path.expanduser("~/Library/LaunchAgents")
SYSTEM_AGENTS_DIR = "/Library/LaunchAgents"
SYSTEM_DAEMONS_DIR = "/Library/LaunchDaemons"
DISABLED_DIR = os.path.join(USER_AGENTS_DIR, "MacMedic Disabled")

AGENT_DIRS: tuple[tuple[str, str], ...] = (
    ("user", USER_AGENTS_DIR),
    ("system", SYSTEM_AGENTS_DIR),
    ("daemon", SYSTEM_DAEMONS_DIR),
)


@dataclass
class LaunchAgentInfo:
    path: str
    label: str
    loaded: bool
    domain: str
    match: BlocklistEntry | None = None
    disabled: bool = False


def _read_plist(path: str) -> tuple[str, bool]:
    label = os.path.splitext(os.path.basename(path))[0]
    disabled = False
    try:
        with open(path, "rb") as fh:
            data = plistlib.load(fh)
        label = str(data.get("Label") or label)
        disabled = bool(data.get("Disabled"))
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("could not read %s: %s", path, exc)
    return label, disabled


def _loaded_labels() -> set[str]:
    try:
        result = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return set()
        labels: set[str] = set()
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[2].strip():
                labels.add(parts[2].strip())
        return labels
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("launchctl list failed: %s", exc)
        return set()


def list_launch_agents() -> list[LaunchAgentInfo]:
    loaded = _loaded_labels()
    agents: list[LaunchAgentInfo] = []
    seen: set[str] = set()
    for domain, directory in AGENT_DIRS:
        if not os.path.isdir(directory):
            continue
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for name in names:
            if not name.endswith(".plist"):
                continue
            path = os.path.join(directory, name)
            if path in seen:
                continue
            seen.add(path)
            label, disabled = _read_plist(path)
            is_loaded = (label in loaded) if domain == "user" else True
            agents.append(
                LaunchAgentInfo(
                    path=path,
                    label=label,
                    loaded=is_loaded and not disabled,
                    disabled=disabled,
                    domain=domain,
                    match=match_blocklist(f"{label} {name}"),
                )
            )
    agents.sort(key=lambda a: (a.domain, a.label.lower()))
    return agents


def disable_agent(agent: LaunchAgentInfo) -> tuple[bool, str]:
    if agent.domain != "user":
        return False, "System-wide agents need admin privileges; disable them with 'sudo launchctl bootout'."

    uid = os.getuid()
    messages: list[str] = []
    try:
        result = subprocess.run(
            ["launchctl", "bootout", f"gui/{uid}", agent.label],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            messages.append(f"launchctl: {stderr or 'could not unload'}")
    except Exception as exc:  # pragma: no cover - defensive
        messages.append(f"launchctl error: {exc}")

    try:
        os.makedirs(DISABLED_DIR, exist_ok=True)
    except OSError as exc:
        return False, f"Could not create disabled folder: {exc}"

    dest = os.path.join(DISABLED_DIR, os.path.basename(agent.path))
    try:
        os.replace(agent.path, dest)
        messages.append(f"plist moved to {dest}")
    except PermissionError:
        return False, "Permission denied. Grant MacMedic Full Disk Access (see README)."
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"Could not move plist: {exc}"

    return True, " ".join(messages) or "Agent unloaded."


def reveal_in_finder(path: str) -> None:
    try:
        subprocess.run(["open", "-R", path], check=False, timeout=5)
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("reveal failed: %s", exc)
