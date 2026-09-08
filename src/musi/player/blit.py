"""Blits onto a transparent surface, kept off an ARM fast path that faults.

On the device (armv7, pygame-ce 2.5.7 / SDL 2.32.4) a per-pixel-alpha source
blitted onto a per-pixel-alpha destination is handed to SDL's ARM SIMD blitter,
which moves 8 bytes at a time with LDRD/STRD. Those instructions fault on a
4-mod-8 address, so the blit dies with SIGBUS — not an exception, the whole
process — whenever the source pitch is a multiple of 8 and the destination x is
odd. Measured on the Pi: every even x is safe for every source, every odd x
with an 8-aligned source pitch kills it. x86 never takes that path, so this
only ever shows up on the device.

Anything drawn onto a transparent cache surface therefore goes through onto().
It assumes the destination is an even number of pixels wide (320 here), which
makes every row of it start 8-byte aligned.
"""
from __future__ import annotations

import pygame


def onto(dest: pygame.Surface, source: pygame.Surface, pos) -> None:
    """Blit ``source`` onto a transparent ``dest`` at an even column.

    ``pos`` is a Rect or an (x, y) pair. An odd x moves one pixel left, which
    centred artwork does not notice — and which beats a hard crash on the Pi.
    """
    x, y = pos[0], pos[1]
    dest.blit(source, (x - (x & 1), y))
