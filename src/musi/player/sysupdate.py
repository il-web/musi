"""Does this device need a *system* update — and, after one, a restart?

An over-the-air update brings new code and runs update.sh, but update.sh's
root steps only run from the root-owned helper that install.sh installs
(see update.sh's header). So after some updates the device needs one manual
``bash install.sh`` over SSH. This module tells the app when, so it can say
so on screen, and what to do once it's done:

  "install"  root steps are waiting on install.sh — show the SSH command
  "reboot"   install.sh ran and a step it applied needs a reboot
  "refresh"  install.sh ran; restarting the interface is enough
  "none"     nothing to do

A small marker file remembers the level the device was at when the notice
first appeared, so once install.sh has moved the level on the app knows which
steps just landed — and update.sh's REBOOT_STEPS says which need a reboot. A
reboot (or a restart of the app) after install.sh finished clears it.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
UPDATE_SH = REPO / "update.sh"
ROOT_SCRIPT = Path("/usr/local/lib/musi/update-root.sh")
STATE = Path.home() / ".local" / "share" / "musi" / "update-level"
MARKER = STATE.with_name("system-update.json")

COMMAND = "cd ~/musi && bash install.sh"
_STARTED = time.time()            # when this app process started


@dataclass
class SystemUpdate:
    kind: str                     # install | reboot | refresh | none
    applied: int = 0
    latest: int = 0


def _latest(text: str) -> int:
    m = re.search(r"^LATEST_STEP=(\d+)", text, re.M)
    return int(m.group(1)) if m else 0


def _root_steps(text: str) -> set[int]:
    return {int(n) for n in re.findall(r"^root_(\d+)\(\)", text, re.M)}


def _reboot_steps(text: str) -> set[int]:
    m = re.search(r'^REBOOT_STEPS="([\d ]*)"', text, re.M)
    return {int(n) for n in m.group(1).split()} if m else set()


def _read_int(path: Path) -> int:
    try:
        return int(path.read_text().strip() or 0)
    except (OSError, ValueError):
        return 0


def _boot_time() -> float:
    try:
        for line in Path("/proc/stat").read_text().splitlines():
            if line.startswith("btime "):
                return float(line.split()[1])
    except (OSError, ValueError):
        pass
    return 0.0


def _load_marker(marker: Path) -> dict | None:
    try:
        m = json.loads(marker.read_text())
        return m if isinstance(m, dict) else None
    except (OSError, ValueError):
        return None


def _save_marker(marker: Path, data: dict) -> None:
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(data))
    except OSError:
        pass


def check(*, update_sh: Path = UPDATE_SH, root_script: Path = ROOT_SCRIPT,
          state: Path = STATE, marker: Path = MARKER,
          boot_time: float | None = None, started: float = _STARTED,
          device: bool | None = None) -> SystemUpdate:
    """What the system needs right now (cheap: a few small file reads)."""
    if not (on_device() if device is None else device):
        return SystemUpdate("none")
    try:
        text = update_sh.read_text(encoding="utf-8")
    except OSError:
        return SystemUpdate("none")
    latest = _latest(text)
    applied = _read_int(state)
    mk = _load_marker(marker)

    if applied < latest:
        pending_root = {n for n in _root_steps(text) if applied < n <= latest}
        helper = 0
        try:
            helper = _latest(root_script.read_text(encoding="utf-8"))
        except OSError:
            pass
        if pending_root and helper < latest:
            if not mk or mk.get("from") is None:
                _save_marker(marker, {"from": applied})
            return SystemUpdate("install", applied, latest)
        return SystemUpdate("none", applied, latest)   # update.sh can do it

    if not mk:
        return SystemUpdate("none", applied, latest)

    # install.sh has run: which of the steps it applied want a reboot?
    frm = int(mk.get("from") or 0)
    try:
        done_at = state.stat().st_mtime         # when the level last moved
    except OSError:
        done_at = 0.0
    boot = _boot_time() if boot_time is None else boot_time
    needs_reboot = any(frm < n <= applied for n in _reboot_steps(text))
    if needs_reboot and boot <= done_at:
        return SystemUpdate("reboot", applied, latest)
    if not needs_reboot and started <= done_at:
        return SystemUpdate("refresh", applied, latest)
    try:
        marker.unlink()                          # done — restarted since
    except OSError:
        pass
    return SystemUpdate("none", applied, latest)


def reboot() -> None:
    subprocess.Popen(["sudo", "systemctl", "reboot", "-i"], start_new_session=True)


def refresh_ui() -> None:
    subprocess.Popen(["systemctl", "--user", "restart", "musi-ui"],
                     start_new_session=True)


# ── what to say ───────────────────────────────────────────────────────────────

TEXT = {
    "install": ("System update needed",
                "This update changes system files. Connect over SSH and run:"),
    "reboot":  ("System updated",
                "Restart musi to finish the update."),
    "refresh": ("System updated",
                "Refresh the interface to finish the update."),
}
BUTTON = {"reboot": "Restart", "refresh": "Refresh UI"}


def act(kind: str) -> None:
    if kind == "reboot":
        reboot()
    elif kind == "refresh":
        refresh_ui()


def on_device() -> bool:
    """Installed on a musi device (install.sh ran here) — not a dev machine."""
    return sys.platform == "linux" and ROOT_SCRIPT.parent.exists()


def mark_shown(kind: str, marker: Path = MARKER) -> bool:
    """Record that ``kind``'s notice popped up; False if it already had."""
    mk = _load_marker(marker) or {}
    if mk.get("shown") == kind:
        return False
    mk["shown"] = kind
    _save_marker(marker, mk)
    return True
