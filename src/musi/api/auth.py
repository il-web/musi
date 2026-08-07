"""Bearer-token management for the device API.

The token lives in ~/.local/share/musi/api-token (0600). It is generated on
first use and can be regenerated from Settings → API on the device. The
server re-reads the file on every request, so a regenerated token takes
effect immediately without a service restart.

FORMAT: 8 characters from a 32-symbol alphabet with the look-alikes removed
(no 0/O, no 1/I), displayed grouped as ``XXXX-XXXX``. That is ~1.1 trillion
combinations — 32**8 — which is short enough to read off a 3.5" screen and
type on a phone, and far too many to guess given the login throttle in
``musi.api.server``. Comparison is case-insensitive and ignores the dash, so
the user can type it however it is easiest.

The short form is only safe *because* of that throttle. If you ever remove the
rate limiting, put the length back.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
import stat
from pathlib import Path

from musi.library.config import api_token_path

log = logging.getLogger(__name__)

# 32 symbols: digits 2-9 (0 and 1 dropped) + A-Z without I and O.
ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
TOKEN_LEN = 8
GROUP = 4                       # display grouping: XXXX-XXXX

_CANONICAL = re.compile(rf"^[{ALPHABET}]{{{TOKEN_LEN}}}$")


def normalize(raw: str) -> str:
    """Fold a user-typed token to its canonical form.

    Uppercases and drops anything outside the alphabet, so 'k7rm-92fq',
    'K7RM 92FQ' and 'K7RM92FQ' all compare equal. Returns '' for input with no
    usable characters, which never matches a real token.
    """
    return "".join(c for c in raw.upper() if c in ALPHABET)


def format_token(token: str) -> str:
    """Group a canonical token for display: 'K7RM92FQ' -> 'K7RM-92FQ'."""
    canon = normalize(token)
    return "-".join(canon[i:i + GROUP] for i in range(0, len(canon), GROUP))


def is_canonical(raw: str) -> bool:
    """True if ``raw`` is already a token in the current format."""
    return bool(_CANONICAL.match(normalize(raw)))


def load_token(path: Path | None = None) -> str:
    """Return the API token, generating one if missing or in the old format.

    Tokens predating the short format are silently replaced. They were 32
    random urlsafe characters — secure, but unusable on a device with no
    keyboard, which is why they were changed.
    """
    path = path or api_token_path()
    try:
        token = path.read_text().strip()
        if token and is_canonical(token):
            return token
    except OSError:
        pass
    return regenerate_token(path)


def regenerate_token(path: Path | None = None) -> str:
    """Write a fresh random token and return it, grouped for display.

    Created 0600 by os.open rather than written and then chmod'ed — the latter
    leaves the token world-readable for the moment in between.
    """
    path = path or api_token_path()
    token = format_token("".join(secrets.choice(ALPHABET) for _ in range(TOKEN_LEN)))
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
