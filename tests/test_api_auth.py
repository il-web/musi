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


def test_token_is_short_and_typeable(tmp_path):
    """8 chars grouped as XXXX-XXXX — readable off a 3.5" screen."""
    token = auth.load_token(tmp_path / "api-token")
    assert len(token) == 9 and token[4] == "-"
    assert len(auth.normalize(token)) == auth.TOKEN_LEN


def test_token_alphabet_has_no_look_alikes(tmp_path):
    """0/O and 1/I are indistinguishable on the device font — and this token
    gets copied by eye, so they must not appear at all."""
    for _ in range(200):
        token = auth.normalize(auth.regenerate_token(tmp_path / "api-token"))
        assert not (set(token) & set("01IO")), token
        assert set(token) <= set(auth.ALPHABET)


def test_normalize_accepts_however_the_user_types_it():
    assert auth.normalize("k7rm-92fq") == "K7RM92FQ"
    assert auth.normalize("K7RM 92FQ") == "K7RM92FQ"
    assert auth.normalize("K7RM92FQ")  == "K7RM92FQ"


def test_normalize_rejects_junk():
    """Junk must not normalize to something that could match a real token."""
    assert auth.normalize("") == ""
    assert auth.normalize("!!!") == ""
    assert auth.normalize("0110") == ""      # every char is a dropped look-alike


def test_old_long_tokens_are_replaced(tmp_path):
    """Pre-existing 32-char urlsafe tokens are secure but unusable without a
    keyboard, so they upgrade to the short format on next load."""
    path = tmp_path / "api-token"
    path.write_text("Xk3_long-legacy-token-abcdefghijklmno\n")
    token = auth.load_token(path)
    assert auth.is_canonical(token)
    assert token == path.read_text().strip()   # persisted, not just returned


def test_a_canonical_token_is_left_alone(tmp_path):
    path = tmp_path / "api-token"
    first = auth.load_token(path)
    assert auth.load_token(path) == first


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
