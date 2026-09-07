"""Blurred now-playing backdrop — caching and graceful absence."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player import backdrop, theme


def _art(tmp_path, name="art.png"):
    p = tmp_path / name
    surf = pygame.Surface((300, 300))
    surf.fill((200, 40, 40))
    pygame.image.save(surf, str(p))
    return str(p)


def test_no_path_is_none():
    backdrop.clear_cache()
    assert backdrop.surface("") is None


def test_missing_file_is_none(tmp_path):
    backdrop.clear_cache()
    assert backdrop.surface(str(tmp_path / "nope.png")) is None


def test_returns_a_full_screen_surface(tmp_path):
    backdrop.clear_cache()
    s = backdrop.surface(_art(tmp_path))
    assert s is not None
    assert s.get_size() == (backdrop.WIDTH, backdrop.HEIGHT)


def test_result_is_cached(tmp_path):
    """The render loop must never pay a decode twice for one album."""
    backdrop.clear_cache()
    p = _art(tmp_path)
    assert backdrop.surface(p) is backdrop.surface(p)


def test_clear_cache_forces_a_rebuild(tmp_path):
    p = _art(tmp_path)
    first = backdrop.surface(p)
    backdrop.clear_cache()
    assert backdrop.surface(p) is not first


def test_it_is_dimmed(tmp_path):
    """A bright source must come back dark enough for white text to sit on."""
    backdrop.clear_cache()
    s = backdrop.surface(_art(tmp_path))
    r, g, b = s.get_at((160, 240))[:3]
    assert r + g + b < 300


# ── for_track: the guard that keeps SQL out of the render loop ────────────────

class _CountingDB:
    def __init__(self, rows):
        self.rows = rows
        self.queries = 0

    def execute(self, *a, **k):
        self.queries += 1
        return self

    def fetchone(self):
        return self.rows


class _Status:
    def __init__(self, path):
        self.path = path
        self.artist = "A"
        self.album = "B"


def test_for_track_without_a_path_is_flat(tmp_path):
    backdrop.clear_cache()
    bg, accent = backdrop.for_track(None, _Status(""))
    assert bg is None
    assert accent == theme.ACCENT


def test_for_track_queries_once_per_track(tmp_path):
    """20 frames on one track must cost one query, not twenty."""
    from musi.player import backdrop as bd
    bd.clear_cache()
    art = _art(tmp_path, "bd.png")
    db = _CountingDB({"art_path": art, "backdrop_path": art,
                      "palette": '["#ff8800"]'})
    st = _Status("/m/1.mp3")
    for _ in range(20):
        bd.for_track(db, st)
    assert db.queries == 1


def test_for_track_reloads_when_the_track_changes(tmp_path):
    from musi.player import backdrop as bd
    bd.clear_cache()
    art = _art(tmp_path, "bd2.png")
    db = _CountingDB({"art_path": art, "backdrop_path": art,
                      "palette": '["#ff8800"]'})
    bd.for_track(db, _Status("/m/1.mp3"))
    bd.for_track(db, _Status("/m/2.mp3"))
    assert db.queries == 2
