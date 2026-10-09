"""Animations pack — tweens, screen transitions, and the off switch.

Animation is about time, so every test drives the clock explicitly (``now``)
instead of sleeping, and checks the end states that matter: a transition must
start on exactly the frame the user was looking at and land on exactly the
new screen, and turning Animations off must leave no motion anywhere.
"""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

import pytest

from musi.player import motion, prefs, transition
from musi.player.app import App
from musi.player.screen import Screen
from musi.player.transition import Transition

RED, BLUE = (200, 0, 0), (0, 0, 200)


@pytest.fixture(autouse=True)
def isolated_prefs(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSI_PREFS_PATH", str(tmp_path / "prefs.json"))
    prefs.reload()
    yield
    prefs.reload()


def _solid(colour):
    s = pygame.Surface((320, 480)).convert()
    s.fill(colour)
    return s


# ── tween + easing ────────────────────────────────────────────────────────────

def test_tween_runs_from_zero_to_one_then_stops():
    t = motion.Tween(0.2)
    assert t.progress(0.0) == 1.0          # idle until started
    t.start(now=10.0)
    assert t.progress(10.0) == 0.0
    assert t.progress(10.1) == pytest.approx(0.5)
    assert t.active(10.1)
    assert t.progress(10.3) == 1.0
    assert not t.active(10.0)              # once finished it stays finished


def test_tween_is_born_finished_when_animations_are_off():
    prefs.set("animations", False)
    t = motion.Tween(0.2)
    t.start(now=10.0)
    assert t.progress(10.0) == 1.0


@pytest.mark.parametrize("ease", [motion.ease_out_cubic,
                                  motion.ease_in_out_cubic,
                                  motion.ease_out_back])
def test_easings_start_at_zero_and_land_on_one(ease):
    assert ease(0.0) == pytest.approx(0.0)
    assert ease(1.0) == pytest.approx(1.0)


def test_bump_returns_to_rest():
    assert motion.bump(0.0) == pytest.approx(0.0)
    assert motion.bump(0.5) == pytest.approx(1.0)
    assert motion.bump(1.0) == pytest.approx(0.0, abs=1e-9)


def test_blit_alpha_leaves_a_shared_surface_opaque():
    # art surfaces are shared via caches — a leaked alpha would ghost them
    src, dest = _solid(RED), _solid(BLUE)
    motion.blit_alpha(dest, src, (0, 0), 0.5)
    assert src.get_alpha() in (None, 255)
    r, _, b, _ = dest.get_at((160, 240))
    assert 0 < r < 200 and 0 < b < 200


# ── transition composition ────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", transition.KINDS)
@pytest.mark.parametrize("forward", [True, False])
def test_every_transition_starts_on_the_old_frame_and_ends_on_the_new(kind, forward):
    old, new = _solid(RED), _solid(BLUE)
    t = Transition(kind, forward, old, now=0.0)
    out = pygame.Surface((320, 480)).convert()

    t.compose(out, new, now=0.0)
    assert out.get_at((160, 240))[:3] == RED

    t.compose(out, new, now=transition.DURATIONS[kind])
    assert out.get_at((160, 240))[:3] == BLUE
    assert out.get_at((2, 470))[:3] == BLUE


def test_slide_keeps_one_status_bar_while_the_page_moves():
    old, new = _solid(RED), _solid(BLUE)
    t = Transition("slide", True, old, now=0.0)
    out = pygame.Surface((320, 480)).convert()
    t.compose(out, new, now=transition.DURATIONS["slide"] * 0.6)
    # past halfway the incoming page owns the whole bar, edge to edge
    assert out.get_at((2, 5))[:3] == BLUE
    assert out.get_at((317, 5))[:3] == BLUE


# ── app integration ───────────────────────────────────────────────────────────

class Probe(Screen):
    def draw(self, surface, status):
        pass


def _running_app(tmp_path, depth=1):
    a = App(mpd=None, db=None, art_dir=tmp_path, lyrics_dir=tmp_path)
    a._running = True                     # transitions only run in the loop
    for _ in range(depth):
        a.push(Probe(a))
    a._transition = None
    return a


def test_push_and_pop_animate(tmp_path):
    a = _running_app(tmp_path)
    a.push(Probe(a))
    assert a.transitioning and a._transition.forward
    a._transition = None
    a.pop()
    assert a.transitioning and not a._transition.forward


def test_pop_replays_the_kind_the_screen_was_pushed_with(tmp_path):
    a = _running_app(tmp_path)
    s = Probe(a)
    s.transition = "zoom"
    a.push(s)
    a._transition = None
    a.pop()
    assert a._transition.kind == "zoom"


def test_go_home_is_one_transition_from_the_frame_on_screen(tmp_path):
    a = _running_app(tmp_path, depth=4)
    a.go_home()
    t = a._transition
    assert t is not None and not t.forward
    snap = t.snapshot
    # a second action in the same frame retargets — it never re-snapshots
    a.push(Probe(a))
    assert a._transition is t and t.snapshot is snap and t.forward


def test_no_transition_when_animations_are_off(tmp_path):
    prefs.set("animations", False)
    a = _running_app(tmp_path)
    a.push(Probe(a))
    assert not a.transitioning


def test_push_before_the_loop_runs_does_not_animate(tmp_path):
    a = App(mpd=None, db=None, art_dir=tmp_path, lyrics_dir=tmp_path)
    a.push(Probe(a))
    a.push(Probe(a))
    assert not a.transitioning


def test_draw_composes_while_transitioning_then_stops(tmp_path):
    a = _running_app(tmp_path)
    a.push(Probe(a))
    surface = pygame.display.get_surface()
    a._draw_stack(surface, None)
    assert a.transitioning
    a._transition._tween._t0 = -100.0     # long finished
    a._draw_stack(surface, None)
    assert not a.transitioning


def test_now_playing_and_menu_kinds():
    from musi.player.screens.context_menu import ContextMenuScreen
    from musi.player.screens.now_playing import NowPlayingScreen
    assert NowPlayingScreen.transition == "sheet"
    assert ContextMenuScreen.transition == "fade"


# ── now playing ───────────────────────────────────────────────────────────────

class _Status:
    title, artist, album, path = "One", "Band", "Alb", "/m/1.mp3"
    state, connected = "play", True
    duration, progress, elapsed, volume = 200.0, 0.1, 20.0, 50
    shuffle = repeat = False


class _MPD:
    def is_favorite(self, path):
        return False

    def toggle_favorite(self, path):
        return True

    def next_track(self):
        pass


class _App:
    db = None
    lyrics_dir = None

    def __init__(self):
        self.stack, self.status, self.mpd = [], _Status(), _MPD()

    def request_poll(self):
        pass

    def toggle_play(self):
        pass


def _np():
    from musi.player.screens.now_playing import NowPlayingScreen
    app = _App()
    scr = NowPlayingScreen(app)
    app.stack.append(scr)
    return scr, app


def test_first_frame_does_not_animate_a_track_change():
    scr, app = _np()
    scr.on_enter()
    scr.draw(pygame.Surface((320, 480)), app.status)
    assert not scr.animates


def test_track_change_slides_in_from_the_direction_tapped():
    from musi.player.input import Button
    scr, app = _np()
    surf = pygame.Surface((320, 480))
    scr.draw(surf, app.status)

    scr.handle(Button.NEXT, app.status)
    nxt = _Status()
    nxt.title, nxt.path = "Two", "/m/2.mp3"
    scr.draw(surf, nxt)
    assert scr.animates and scr._swap_dir == 1
    assert scr._old_title is not None


def test_favouriting_bumps_the_heart():
    scr, app = _np()
    scr.draw(pygame.Surface((320, 480)), app.status)
    scr._toggle_favorite()
    assert scr._heart.active()


def test_now_playing_is_still_when_animations_are_off():
    from musi.player.input import Button
    prefs.set("animations", False)
    scr, app = _np()
    surf = pygame.Surface((320, 480))
    scr.draw(surf, app.status)
    scr.handle(Button.NEXT, app.status)
    nxt = _Status()
    nxt.path = "/m/2.mp3"
    scr.draw(surf, nxt)
    scr._toggle_favorite()
    assert not scr.animates


# ── customization switch ──────────────────────────────────────────────────────

def test_the_switch_toggles_the_pref():
    from musi.player.screens import customization
    scr = customization.CustomizationScreen(_App())
    assert motion.enabled()
    scr.handle_touch(*customization.MOTION_ROW.center)
    assert prefs.get("animations") is False
    scr.handle_touch(*customization.MOTION_ROW.center)
    assert prefs.get("animations") is True


# ── device safety ─────────────────────────────────────────────────────────────

class _RecordingSurface(pygame.Surface):
    """Records every blit of a per-pixel-alpha source and its x."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.alpha_blits = []

    def blit(self, source, dest, *a, **k):
        if source.get_flags() & pygame.SRCALPHA:
            x = dest[0] if not isinstance(dest, pygame.Rect) else dest.x
            self.alpha_blits.append((source.get_size(), x))
        return super().blit(source, dest, *a, **k)


def test_play_pause_pop_and_ripples_use_no_layers_or_rescaling(monkeypatch):
    """The first pop/ripple drew into transparent layers and smoothscaled them:
    fine on x86, a process-killing crash on the Pi the moment play/pause was
    tapped. They must draw plain shapes onto the frame."""
    from musi.player.input import Button

    def no_smoothscale(*a, **k):
        raise AssertionError("smoothscale in the Now Playing animation path")
    monkeypatch.setattr(pygame.transform, "smoothscale", no_smoothscale)

    scr, app = _np()
    plain = pygame.Surface((320, 480))
    scr.draw(plain, app.status)                     # settle the first frame
    scr.handle(Button.PLAY_PAUSE, app.status)       # ripple
    app.status.state = "pause"                      # → pop
    scr._toggle_favorite()                          # → heart bump
    surf = _RecordingSurface((320, 480))
    before = len(surf.alpha_blits)
    for _ in range(3):
        scr.draw(surf, app.status)
    assert scr._ripple.active() and scr._pp_pop.active() and scr._heart.active()
    # nothing new beyond the screen's ordinary text blits: count per frame
    # must match a frame with no motion at all
    animated = len(surf.alpha_blits) - before
    still = _RecordingSurface((320, 480))
    scr._ripple.stop(); scr._pp_pop.stop(); scr._heart.stop()
    for _ in range(3):
        scr.draw(still, app.status)
    assert animated == len(still.alpha_blits)


def test_slide_edge_shadow_lands_on_an_even_column():
    old, new = _solid(RED), _solid(BLUE)
    for frac in (0.1, 0.33, 0.5, 0.77):
        t = Transition("slide", True, old, now=0.0)
        out = _RecordingSurface((320, 480))
        t.compose(out, new, now=transition.DURATIONS["slide"] * frac)
        assert all(x % 2 == 0 for _, x in out.alpha_blits), out.alpha_blits
