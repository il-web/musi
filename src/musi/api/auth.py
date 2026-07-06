"""Bearer-token management for the device API.

The token lives in ~/.local/share/musi/api-token (0600). It is generated on
first use and can be regenerated from Settings → API on the device. The
server re-reads the file on every request, so a regenerated token takes
effect immediately without a service restart.
"""
from __future__ import annotations

import logging
import os
import secrets
import stat
from pathlib import Path

from musi.library.config import api_token_path

log = logging.getLogger(__name__)


def load_token(path: Path | None = None) -> str:
    """Return the API token, generating and persisting one if missing."""
    path = path or api_token_path()
    try:
        token = path.read_text().strip()
        if token:
            return token
    except OSError:
        pass
    return regenerate_token(path)


def regenerate_token(path: Path | None = None) -> str:
    """Write a fresh random token and return it."""
    path = path or api_token_path()
    token = secrets.token_urlsafe(24)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)   # 0600 (no-op on Windows)
    except OSError:
        log.warning("could not chmod api-token", exc_info=True)
    return token
