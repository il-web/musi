"""Hand the screen over from the Plymouth boot splash to the app.

Plymouth holds the panel until it quits, and the app can't open the display
while it does. Quitting it early — when the service starts, as musi-ui.service
used to — left seconds of bare console on the panel while Python imported.
So the app quits it itself, as late as possible: right before it opens the
display. ``--retain-splash`` keeps the last splash frame on the panel until
the app's first frame (the same picture — see boot_look.py) replaces it.

Plymouth may only take orders from root, so a plain ``plymouth quit`` is
tried first and then the one sudoers rule for it (install.sh / update.sh
step 12). If neither works the boot-end fallback (plymouth-quit.service's
musi drop-in) quits it anyway.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time

log = logging.getLogger(__name__)

PLYMOUTH = "/usr/bin/plymouth"
QUIT = ["quit", "--retain-splash"]


def _running(exe: str) -> bool:
    try:
        return subprocess.run([exe, "--ping"], capture_output=True,
                              timeout=2).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def release(run=subprocess.run, exe: str | None = None) -> bool:
    """Quit the boot splash if it is up. True if it was (and was asked to go).

    Only on the device (Linux, no desktop): on a dev machine there is none."""
    if sys.platform != "linux" or os.environ.get("DISPLAY"):
        return False
    exe = exe or shutil.which("plymouth") or (PLYMOUTH if os.path.exists(PLYMOUTH) else None)
    if not exe or not _running(exe):
        return False
    for cmd in ([exe, *QUIT], ["sudo", "-n", PLYMOUTH, *QUIT]):
        try:
            run(cmd, capture_output=True, timeout=4)
        except (OSError, subprocess.TimeoutExpired):
            continue
        for _ in range(20):                       # up to 1 s to let go
            if not _running(exe):
                return True
            time.sleep(0.05)
    log.warning("boot splash would not quit; the display may not open")
    return True
