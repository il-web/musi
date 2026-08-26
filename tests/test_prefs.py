"""Preference store — the first thing in musi that remembers a user choice.

The device can lose power at any moment (there is no power button yet), so a
half-written prefs file is a realistic event, not a theoretical one.
"""
import json

import pytest

from musi.library import config
from musi.player import prefs


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSI_PREFS_PATH", str(tmp_path / "prefs.json"))
    prefs.reload()
    yield
    prefs.reload()


def test_missing_file_yields_defaults():
    assert prefs.get("wallpaper") == "none"


def test_set_then_get_round_trips():
    prefs.set("wallpaper", "warm")
    assert prefs.get("wallpaper") == "warm"


def test_value_survives_a_reload():
    prefs.set("wallpaper", "cool")
    prefs.reload()
    assert prefs.get("wallpaper") == "cool"


def test_write_is_atomic_and_leaves_no_temp_file(tmp_path):
    prefs.set("wallpaper", "warm")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "prefs.json"]
    assert leftovers == []


def test_corrupt_file_falls_back_to_defaults():
    config.prefs_path().write_text("{not json at all", encoding="utf-8")
    prefs.reload()
    assert prefs.get("wallpaper") == "none"


def test_corrupt_file_is_repaired_on_next_write():
    config.prefs_path().write_text("{not json at all", encoding="utf-8")
    prefs.reload()
    prefs.set("wallpaper", "cool")
    assert json.loads(config.prefs_path().read_text(encoding="utf-8")) == {
        "wallpaper": "cool"}


def test_a_non_dict_json_file_is_ignored():
    config.prefs_path().write_text("[1, 2, 3]", encoding="utf-8")
    prefs.reload()
    assert prefs.get("wallpaper") == "none"


def test_unwritable_location_does_not_raise(monkeypatch, tmp_path):
    """A read-only filesystem must not take the UI down. Storage lock does this."""
    monkeypatch.setenv("MUSI_PREFS_PATH", str(tmp_path / "nodir" / "x" / "p.json"))
    prefs.reload()

    def boom(*a, **k):
        raise OSError("read-only file system")

    monkeypatch.setattr(prefs.os, "replace", boom)
    prefs.set("wallpaper", "warm")          # must not raise
    assert prefs.get("wallpaper") == "warm"  # still applies this session


def test_unknown_key_returns_the_given_default():
    assert prefs.get("nope", "fallback") == "fallback"
