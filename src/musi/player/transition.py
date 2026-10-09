"""Screen-to-screen transitions, composed by the app — screens know nothing.

push() and pop() hand the app a snapshot of the frame that was on the panel;
while the transition runs, the app draws the new top screen live into an
offscreen frame and asks Transition to combine the two. Both inputs are plain
full-screen surfaces, so every kind costs a few blits per frame (zoom adds one
smoothscale), and only for the quarter second the transition lasts.

Kinds:
  slide  — new page in from the right, old one drifts left under a shade;
           the status bar stays put. The default for drilling into things.
  sheet  — up from the bottom (Now Playing, out of the mini bar).
  fade   — cross-fade (modal overlays: the long-press menu).
  zoom   — grows out of the middle (opening an app from the launcher).
A pop plays the kind it was pushed with, backwards.
"""
from __future__ import annotations

import pygame

from musi.player import motion, statusbar

W, H = 320, 480
PARALLAX = 0.3          # the page underneath moves this fraction of the width
SHADE    = 110          # max darkening of the page underneath (0..255)
ZOOM_MIN = 0.9          # zoom starts / ends at this scale

DURATIONS = {"slide": 0.24, "sheet": 0.28, "fade": 0.15, "zoom": 0.22}
KINDS = tuple(DURATIONS)

_shade:     pygame.Surface | None = None
_edge_shad: pygame.Surface | None = None


def _shade_surf() -> pygame.Surface:
    global _shade
    if _shade is None:
        _shade = pygame.Surface((W, H))
        _shade.fill((0, 0, 0))
    return _shade


def _edge_shadow() -> pygame.Surface:
    """Soft vertical shadow cast by a sliding page onto the one beneath."""
    global _edge_shad
    if _edge_shad is None:
        w = 12
        _edge_shad = pygame.Surface((w, H), pygame.SRCALPHA)
        for i in range(w):
            _edge_shad.fill((0, 0, 0, int(70 * (i / w) ** 2)), (i, 0, 1, H))
    return _edge_shad


class Transition:
    def __init__(self, kind: str, forward: bool, snapshot: pygame.Surface,
                 now: float | None = None) -> None:
        self.kind     = kind if kind in DURATIONS else "slide"
        self.forward  = forward
        self.snapshot = snapshot
        self.frame_no = -1              # app frame that created it (see App)
        self._tween   = motion.Tween(DURATIONS[self.kind])
        self._tween.start(now)

    def retarget(self, kind: str, forward: bool) -> None:
        """A second push/pop in the same frame (go_home, menu → action):
        keep the snapshot of what was really on screen, play the latest kind."""
        self.kind    = kind if kind in DURATIONS else "slide"
        self.forward = forward
        self._tween  = motion.Tween(DURATIONS[self.kind])
        self._tween.start()

    def active(self, now: float | None = None) -> bool:
        return self._tween.active(now)

    def compose(self, out: pygame.Surface, live: pygame.Surface,
                now: float | None = None) -> None:
        """Draw this frame of the transition onto ``out``.

        ``live`` is the current top screen, freshly drawn: the incoming page
        on a push, the page being revealed on a pop.
        """
        p = motion.ease_out_cubic(self._tween.progress(now))
        # q: 0 = the old screen fully shown, 1 = the live screen fully shown.
        # Every kind is written once, in terms of the page on top (`over`)
        # moving off/onto the page beneath (`under`).
        if self.forward:
            under, over, shown = self.snapshot, live, p
        else:
            under, over, shown = live, self.snapshot, 1 - p
        getattr(self, "_" + self.kind)(out, under, over, shown)

    # each: shown = how far `over` has arrived (1 = fully on top)

    def _slide(self, out, under, over, shown) -> None:
        out.blit(under, (int(-PARALLAX * W * shown), 0))
        _shade_over(out, SHADE * shown)
        x = int(W * (1 - shown))
        out.blit(over, (x, 0))
        if x > 0:
            # even column: a per-pixel-alpha blit at an odd x can SIGBUS on
            # the Pi (blit.py) — a pixel of shadow drift is invisible
            out.blit(_edge_shadow(), ((x - _edge_shadow().get_width()) & ~1, 0))
        _fixed_bar(out, under, over, shown)

    def _sheet(self, out, under, over, shown) -> None:
        out.blit(under, (0, 0))
        _shade_over(out, SHADE * shown)
        out.blit(over, (0, int(H * (1 - shown))))

    def _fade(self, out, under, over, shown) -> None:
        out.blit(under, (0, 0))
        motion.blit_alpha(out, over, (0, 0), shown)
        _fixed_bar(out, under, over, shown)

    def _zoom(self, out, under, over, shown) -> None:
        out.blit(under, (0, 0))
        _shade_over(out, SHADE * 0.6 * shown)
        if shown <= 0:
            return
        s = motion.lerp(ZOOM_MIN, 1.0, shown)
        if s >= 0.999:
            motion.blit_alpha(out, over, (0, 0), shown)
            return
        size = (int(W * s) & ~1, int(H * s))      # even width: see blit.py
        scaled = pygame.transform.smoothscale(over, size)
        pos = ((W - size[0]) // 2 & ~1, (H - size[1]) // 2)
        motion.blit_alpha(out, scaled, pos, shown)
        _fixed_bar(out, under, over, shown)


def _fixed_bar(out, under, over, shown) -> None:
    """One status bar, never two ghosted over each other: every screen draws
    its own, so whichever page is mostly in front lends its bar to the frame."""
    front = over if shown >= 0.5 else under
    out.blit(front, (0, 0), (0, 0, W, statusbar.BAR_H))


def _shade_over(out: pygame.Surface, alpha: float) -> None:
    if alpha >= 1:
        sh = _shade_surf()
        sh.set_alpha(int(alpha))
        out.blit(sh, (0, 0))
