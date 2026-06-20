"""Path configuration — override with environment variables."""

import os
from pathlib import Path

_BASE = Path.home() / ".local" / "share" / "musi"


def music_root() -> Path:
    return Path(os.environ.get("MUSI_MUSIC_ROOT", Path.home() / "Music"))


def db_path() -> Path:
    return Path(os.environ.get("MUSI_DB_PATH", _BASE / "library.db"))


def art_dir() -> Path:
    return Path(os.environ.get("MUSI_ART_DIR", _BASE / "art"))
