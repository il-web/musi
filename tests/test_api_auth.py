"""Token file handling — the file is a root-equivalent secret on the device."""
from __future__ import annotations

import os
import stat
import sys

import pytest

from musi.api import auth


def test_token_is_generated_and_stable(tmp_path):
    path = tmp_path / "api-token"
    first = auth.load_token(path)
    assert first
    assert auth.load_token(path) == first        # re-read, not regenerated


def test_regenerate_changes_the_token(tmp_path):
    path = tmp_path / "api-token"
    first = auth.load_token(path)
    assert auth.regenerate_token(path) != first


def test_token_has_enough_entropy(tmp_path):
    # token_urlsafe(24) → 24 random bytes, ~32 chars base64url
    assert len(auth.load_token(tmp_path / "api-token")) >= 30


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes only")
def test_token_file_is_never_world_readable(tmp_path):
    """Written 0600 by os.open, not written-then-chmod'ed — the latter leaves
    the token readable by every local account for the moment in between."""
    path = tmp_path / "api-token"
    auth.regenerate_token(path)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes only")
def test_regenerate_tightens_a_loose_existing_file(tmp_path):
    """O_CREAT only applies its mode to a new file, so an already-loose token
    file has to be chmod'ed back down explicitly."""
    path = tmp_path / "api-token"
    path.write_text("old\n")
    os.chmod(path, 0o644)
    auth.regenerate_token(path)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
