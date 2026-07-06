"""Path configuration — override with environment variables."""

import os
from pathlib import Path

_BASE = Path.home() / ".local" / "share" / "musi"


def music_root() -> Path:
    env = os.environ.get("MUSI_MUSIC_ROOT")
    if env:
        return Path(env)
    # The Pi installer uses ~/music (run.sh exports it, but services that
    # don't go through run.sh — e.g. musi-api — rely on this fallback).
    pi_default = Path.home() / "music"
    if pi_default.is_dir():
        return pi_default
    return Path.home() / "Music"


def db_path() -> Path:
    return Path(os.environ.get("MUSI_DB_PATH", _BASE / "library.db"))


def art_dir() -> Path:
    return Path(os.environ.get("MUSI_ART_DIR", _BASE / "art"))


def api_token_path() -> Path:
    return Path(os.environ.get("MUSI_API_TOKEN_PATH", _BASE / "api-token"))
