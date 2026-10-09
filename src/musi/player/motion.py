"""Motion primitives — easing curves and a tiny time-based tween.

Everything animated in the player goes through Tween, so the "Animations" pref
in Customization switches all of it off in one place: a tween started while
motion is disabled is born finished, and screens simply draw their end state.

Durations are short on purpose (150–300 ms). The panel is fed over SPI, so the
frame rate under load is lower than a phone's; a quick ease-out hides that,
a long animation would show every step.
"""
from __future__ import annotations

import math
import time

from musi.player import prefs


def enabled() -> bool:
    """The user's Animations toggle (Customization). Read every call — cheap."""
    return bool(prefs.get("animations"))


# ── easing (t in 0..1 → 0..1) ─────────────────────────────────────────────────

def ease_out_cubic(t: float) -> float:
    t = _clamp(t)
    return 1 - (1 - t) ** 3


def ease_in_out_cubic(t: float) -> float:
    t = _clamp(t)
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_out_back(t: float, overshoot: float = 1.7) -> float:
    """Overshoots past 1 and settles back — for small 'pop' effects."""
    t = _clamp(t)
    c3 = overshoot + 1
    return 1 + c3 * (t - 1) ** 3 + overshoot * (t - 1) ** 2


def bump(t: float) -> float:
    """0 → 1 → 0 over the tween — a pulse that ends where it started."""
    return math.sin(math.pi * _clamp(t))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_colour(a: tuple, b: tuple, t: float) -> tuple[int, int, int]:
    return tuple(int(round(lerp(x, y, t))) for x, y in zip(a[:3], b[:3]))


def blit_alpha(dest, src, pos, a: float) -> None:
    """Blit ``src`` at opacity ``a`` (0..1), leaving its own alpha untouched —
    art surfaces are shared through caches, so a lingering set_alpha would
    leak into every other screen that draws them."""
    if a <= 0:
        return
    if a >= 1:
        dest.blit(src, pos)
        return
    prev = src.get_alpha()
    src.set_alpha(int(255 * a))
    dest.blit(src, pos)
    src.set_alpha(prev)


def _clamp(t: float) -> float:
    return 0.0 if t < 0 else 1.0 if t > 1 else t


# ── tween ─────────────────────────────────────────────────────────────────────

class Tween:
    """Linear 0→1 progress over ``duration`` seconds; apply an easing on read.

    Idle until start(). ``now`` is injectable everywhere so tests can step
    time without sleeping.
    """

    def __init__(self, duration: float) -> None:
        self.duration = duration
        self._t0: float | None = None

    def start(self, now: float | None = None) -> None:
        """(Re)start from 0 — or finish at once if animations are off."""
        if not enabled():
            self._t0 = None
            return
        self._t0 = time.monotonic() if now is None else now

    def stop(self) -> None:
        self._t0 = None

    def progress(self, now: float | None = None) -> float:
        """0..1; 1 when finished or never started."""
        if self._t0 is None:
            return 1.0
        now = time.monotonic() if now is None else now
        p = (now - self._t0) / self.duration if self.duration > 0 else 1.0
        if p >= 1.0:
            self._t0 = None             # finished — stop costing frames
            return 1.0
        return max(0.0, p)

    def active(self, now: float | None = None) -> bool:
        return self.progress(now) < 1.0
