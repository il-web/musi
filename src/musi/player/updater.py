"""Self-update via git.

The Pi runs the player from a git clone of the project repo. This module checks
GitHub for newer commits and, on request, pulls them and restarts the app's
systemd user service so the new code takes over.

All git/network calls are best-effort and never raise — they return a small
result dict the UI can display.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# Repo root = three levels above this file's package:
#   <root>/src/musi/player/updater.py  → parents[3] == <root>
REPO_DIR = Path(__file__).resolve().parents[3]

# systemd user service that runs the app (see pi/musi-ui.service)
SERVICE = "musi-ui"


@dataclass
class UpdateStatus:
    current:  str  = "?"      # short current commit
    latest:   str  = "?"      # short upstream commit
    behind:   int  = 0        # how many commits behind upstream
    is_repo:  bool = True     # False if not a git checkout
    error:    str  = ""       # human-readable problem, if any
    changelog: list[str] = field(default_factory=list)  # incoming commit subjects

    @property
    def available(self) -> bool:
        return self.is_repo and not self.error and self.behind > 0


def _git(*args: str, timeout: float = 30.0) -> tuple[int, str]:
    """Run a git command in the repo. Returns (returncode, combined output)."""
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO_DIR), *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return 127, "git not installed"
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    except Exception as exc:                       # pragma: no cover - defensive
        return 1, str(exc)


def _is_git_repo() -> bool:
    rc, _ = _git("rev-parse", "--is-inside-work-tree", timeout=5)
    return rc == 0


def current_version() -> str:
    rc, out = _git("rev-parse", "--short", "HEAD", timeout=5)
    return out if rc == 0 else "?"


def check() -> UpdateStatus:
    """Fetch from the remote and compare local HEAD with upstream."""
    st = UpdateStatus(current=current_version())

    if not _is_git_repo():
        st.is_repo = False
        st.error   = "Not a git checkout"
        return st

    rc, out = _git("fetch", "--quiet", timeout=45)
    if rc != 0:
        st.error = out or "fetch failed (no network?)"
        return st

    # Resolve the upstream ref (origin/main, via @{u} if a tracking branch is set)
    rc, upstream = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", timeout=5)
    if rc != 0:
        upstream = "origin/main"

    rc, latest = _git("rev-parse", "--short", upstream, timeout=5)
    if rc == 0:
        st.latest = latest

    rc, cnt = _git("rev-list", "--count", f"HEAD..{upstream}", timeout=10)
    if rc == 0 and cnt.isdigit():
        st.behind = int(cnt)

    if st.behind > 0:
        rc, out = _git("log", "--no-merges", "--format=%s",
                       f"HEAD..{upstream}", timeout=10)
        if rc == 0:
            st.changelog = [ln for ln in out.splitlines() if ln.strip()]
    return st


def apply(progress: "Callable[[float, str], None] | None" = None) -> tuple[bool, str]:
    """Pull the latest code and restart the app service. On success this restarts
    our own process, so the call effectively does not return.

    ``progress`` (if given) is called with (fraction 0..1, stage label) as each
    stage runs, for a UI progress bar.
    Returns (ok, message) only if it fails before the restart.
    """
    def step(frac: float, label: str) -> None:
        if progress:
            progress(frac, label)

    step(0.08, "Preparing…")
    if not _is_git_repo():
        return False, "Not a git checkout"

    step(0.15, "Downloading…")
    rc, out = _git("pull", "--ff-only", timeout=120)
    if rc != 0:
        return False, out or "pull failed"
    step(0.55, "Downloaded")

    # Reinstall in case dependencies/entry-points changed (best-effort, quiet).
    step(0.60, "Installing…")
    py = REPO_DIR / ".venv" / "bin" / "pip"
    if py.exists():
        try:
            subprocess.run(
                [str(py), "install", "--quiet", "-e", str(REPO_DIR)],
                capture_output=True, text=True, timeout=300,
            )
        except Exception:
            import logging
            logging.warning('Ignored exception', exc_info=True)
    step(0.90, "Installed")

    # Restart the service — this terminates the current process and relaunches
    # the player on the new code. Detached so the SIGTERM doesn't pre-empt logging.
    step(0.95, "Restarting…")
    try:
        subprocess.Popen(
            ["systemctl", "--user", "restart", SERVICE],
            start_new_session=True,
        )
    except Exception as exc:
        return False, f"restart failed: {exc}"

    return True, "Restarting…"
