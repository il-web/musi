"""Hand the screen over from the Plymouth boot splash to the app.

Plymouth holds the panel (DRM master) until it quits. If the app opens the
display before that, SDL never becomes master and every frame fails with
"Could not queue pageflip: -13" — the panel stays frozen on the splash even
after Plymouth exits. So the app quits the splash itself, as late as
possible (right before it opens the display), and waits until it is really
gone. ``--retain-splash`` keeps the last splash frame on the panel until the
app's first frame (the same picture — see boot_look.py) replaces it.

Plymouth answers only to root — even ``plymouth --ping`` from this user just
fails, which looks exactly like "not running". So whether it runs is read
from /proc (plymouthd's process), and the quit goes through the one sudoers
rule for it (install.sh). The boot-end fallback (plymouth-quit.service's musi
drop-in) quits it after 30 s regardless; we wait a bit longer than that.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)

PLYMOUTH = "/usr/bin/plymouth"
QUIT = ["quit", "--retain-splash"]
WAIT_S = 35.0                 # > the drop-in's 30 s fallback


def running(proc: Path = Path("/proc")) -> bool:
    """plymouthd is alive (no root needed: it's just a process name)."""
    try:
        entries = list(proc.iterdir())
    except OSError:
        return False
    for d in entries:
        if not d.name.isdigit():
            continue
        try:
            if (d / "comm").read_text().strip() == "plymouthd":
                return True
        except OSError:
            continue
    return False


def release(run=subprocess.run, is_running=running, sleep=time.sleep,
            clock=time.monotonic, wait_s: float = WAIT_S) -> bool:
    """Quit the boot splash if it is up and wait until it has let go of the
    panel. True if it was up. Only on the device (Linux, no desktop)."""
    if sys.platform != "linux" or os.environ.get("DISPLAY"):
        return False
    if not is_running():
        return False
    for cmd in (["sudo", "-n", PLYMOUTH, *QUIT], [PLYMOUTH, *QUIT]):
        try:
            run(cmd, capture_output=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if not is_running():
            return True
    # Not gone yet: never open the display under it — wait for it (the
    # boot-end fallback quits it at the latest).
    deadline = clock() + wait_s
    while is_running() and clock() < deadline:
        sleep(0.1)
    if is_running():
        log.warning("boot splash still up after %.0f s; opening the display anyway", wait_s)
    return True
