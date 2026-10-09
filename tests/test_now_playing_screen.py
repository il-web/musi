"""Now Playing — hero layout, and the controls that must survive it."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player.screens import now_playing
from musi.player.screens.now_playing import NowPlayingScreen


class FakeStatus:
    title = "Song"
    artist = "Band"
    album = "Alb"
    path = "/m/1.mp3"
    state = "play"
    connected = True
    duration = 200.0
    progress = 0.25
    volume = 60
    shuffle = False
    repeat = False


class FakeMPD:
    def __init__(self):
        self.calls = []
        self.favorite = False

    def is_favorite(self, path):
        return self.favorite

    def toggle_favorite(self, path):
        self.calls.append(("toggle_favorite", path))
        self.favorite = not self.favorite
        return self.favorite

    def toggle_shuffle(self):
        self.calls.append(("toggle_shuffle",))

    def toggle_repeat(self):
        self.calls.append(("toggle_repeat",))


class FakeApp:
    db = None
    lyrics_dir = None

    def __init__(self):
        self.stack = []
        self.status = FakeStatus()
        self.mpd = FakeMPD()

    def push(self, s):
        self.stack.append(s)

    def pop(self):
        self.stack.pop()

    def toggle_play(self):
        pass

    def request_poll(self):
        pass


def test_art_bleeds_to_252():
    assert now_playing.ART_BLEED_H == 252


def test_every_control_row_fits_on_screen():
    assert now_playing.INFO_Y == 258
    assert now_playing.CTRL_Y == 362
    assert now_playing.SEC_Y == 412
    assert now_playing.VOL_Y == 452
    assert now_playing.VOL_Y + 8 < 480


def test_rows_do_not_overlap():
    assert now_playing.INFO_Y < now_playing.ARTIST_Y < now_playing.BAR_Y
    assert now_playing.BAR_Y < now_playing.CTRL_Y - 22
    assert now_playing.CTRL_Y + 22 < now_playing.SEC_Y - 18
    assert now_playing.SEC_Y + 18 < now_playing.VOL_Y - 8


def test_the_lyrics_button_is_still_there():
    """The redesign must not quietly drop lyrics — it has its own screen."""
    app = FakeApp()
    s = NowPlayingScreen(app)
    s.handle_touch(170, now_playing.SEC_Y)
    assert app.stack, "tapping lyrics should push LyricsScreen"
    assert type(app.stack[-1]).__name__ == "LyricsScreen"


def test_lyrics_does_nothing_without_a_track():
    app = FakeApp()
    app.status.path = ""
    s = NowPlayingScreen(app)
    s.handle_touch(170, now_playing.SEC_Y)
    assert app.stack == []


def test_queue_button_still_opens_the_queue():
    app = FakeApp()
    s = NowPlayingScreen(app)
    s.handle_touch(240, now_playing.SEC_Y)
    assert type(app.stack[-1]).__name__ == "QueueScreen"


def test_tapping_the_art_toggles_play():
    """The art is a captured gesture now (swipe = skip, drag down = close),
    so a tap is resolved on release — and still plays / pauses."""
    app = FakeApp()
    toggled = []
    app.toggle_play = lambda: toggled.append(True)
    s = NowPlayingScreen(app)
    assert s.on_press(160, 150) is True
    s.on_release(160, 150)
    assert toggled == [True]


class _SkipMPD(FakeMPD):
    def __init__(self):
        super().__init__()
        self.skips = []

    def next_track(self):
        self.skips.append("next")

    def prev_track(self):
        self.skips.append("prev")


def test_swiping_the_art_skips_songs():
    app = FakeApp()
    app.mpd = _SkipMPD()
    s = NowPlayingScreen(app)
    s.on_press(250, 150)
    s.on_drag(200, 152)
    s.on_drag(150, 155)
    assert s._art_dx < 0                            # the art follows the finger
    s.on_release(150, 155)
    s.on_press(80, 150)
    s.on_drag(200, 150)
    s.on_release(200, 150)
    assert app.mpd.skips == ["next", "prev"] and s._art_dx == 0


def test_a_short_swipe_springs_back_without_skipping():
    app = FakeApp()
    app.mpd = _SkipMPD()
    s = NowPlayingScreen(app)
    s.on_press(200, 150)
    s.on_drag(170, 150)
    s.on_release(170, 150)
    assert app.mpd.skips == [] and s._art_dx == 0


def test_dragging_the_art_down_hands_over_to_the_app():
    app = FakeApp()
    calls = []
    app.begin_interactive_pop = lambda axis: calls.append(("begin", axis)) or True
    app.drag_interactive_pop = lambda off: calls.append(("drag", off))
    app.end_interactive_pop = lambda: calls.append(("end",))
    s = NowPlayingScreen(app)
    s.on_press(160, 100)
    s.on_drag(162, 140)
    s.on_drag(163, 220)
    s.on_release(163, 220)
    assert calls == [("begin", "y"), ("drag", 40), ("drag", 120), ("end",)]


def test_the_left_edge_stays_the_back_swipe():
    assert NowPlayingScreen(FakeApp()).on_press(10, 150) is False


def test_status_bar_tap_goes_home():
    from musi.player.input import Button
    s = NowPlayingScreen(FakeApp())
    assert s.handle_touch(160, 10) == Button.HOME


def test_it_draws_without_art():
    s = NowPlayingScreen(FakeApp())
    surface = pygame.Surface((320, 480))
    s.draw(surface, FakeStatus())
    assert surface.get_at((160, 20))[:3] != (255, 255, 255)


# ── favourite heart (secondary row) ─────────────────────────────────────────

def test_five_secondary_zones_map_to_the_right_action():
    """fav | shuffle | repeat | lyrics | queue across the SEC_Y row."""
    app = FakeApp()
    s = NowPlayingScreen(app)
    y = now_playing.SEC_Y

    s.handle_touch(30, y)                        # favourite
    assert app.mpd.calls[-1][0] == "toggle_favorite"
    s.handle_touch(76, y)                        # shuffle
    assert app.mpd.calls[-1] == ("toggle_shuffle",)
    s.handle_touch(118, y)                       # repeat
    assert app.mpd.calls[-1] == ("toggle_repeat",)
    s.handle_touch(160, y)                       # lyrics
    assert type(app.stack[-1]).__name__ == "LyricsScreen"
    s.handle_touch(250, y)                       # queue
    assert type(app.stack[-1]).__name__ == "QueueScreen"


def test_tapping_the_heart_toggles_and_tracks_state():
    app = FakeApp()
    s = NowPlayingScreen(app)
    assert s._fav is False
    s.handle_touch(30, now_playing.SEC_Y)
    assert app.mpd.calls == [("toggle_favorite", "/m/1.mp3")]
    assert s._fav is True


def test_heart_is_inert_without_a_track():
    app = FakeApp()
    app.status.path = ""
    s = NowPlayingScreen(app)
    s.handle_touch(30, now_playing.SEC_Y)
    assert app.mpd.calls == []


def test_heart_state_follows_the_track():
    app = FakeApp()
    app.mpd.favorite = True
    s = NowPlayingScreen(app)
    s.draw(pygame.Surface((320, 480)), FakeStatus())
    assert s._fav is True
