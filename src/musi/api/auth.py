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
    """Write a fresh random token and return it.

    Created 0600 by os.open rather than written and then chmod'ed — the latter
    leaves the token world-readable for the moment in between.
    """
    path = path or api_token_path()
    token = secrets.token_urlsafe(24)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(token + "\n")
        # O_CREAT only applies the mode to a *new* file; fix up an existing one.
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)   # 0600 (no-op on Windows)
    except OSError:
        log.warning("could not write api-token securely", exc_info=True)
        path.write_text(token + "\n")
    return token
