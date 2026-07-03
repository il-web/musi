"""Shared icon drawing helpers."""

import math

import pygame


def draw_chevron_right(surface: pygame.Surface, cx: int, cy: int, col: tuple) -> None:
    """Right-pointing '>' chevron."""
    pts = [(cx - 4, cy - 6), (cx + 2, cy), (cx - 4, cy + 6)]
    pygame.draw.lines(surface, col, False, pts, 2)


def draw_chevron_left(surface: pygame.Surface, cx: int, cy: int, col: tuple) -> None:
    """Left-pointing '<' chevron."""
    pts = [(cx + 3, cy - 5), (cx - 2, cy), (cx + 3, cy + 5)]
    pygame.draw.lines(surface, col, False, pts, 2)


def draw_play(surface: pygame.Surface, cx: int, cy: int, col: tuple, size: str = "md") -> None:
    """Play triangle."""
    if size == "sm":
        pts = [(cx - 4, cy - 7), (cx - 4, cy + 7), (cx + 7, cy)]
    elif size == "xs":
        pts = [(cx - 4, cy - 5), (cx - 4, cy + 5), (cx + 5, cy)]
    elif size == "lg":
        pts = [(cx - 9, cy - 13), (cx - 9, cy + 13), (cx + 13, cy)]
    else:  # md
        pts = [(cx - 5, cy - 6), (cx - 5, cy + 6), (cx + 6, cy)]
    pygame.draw.polygon(surface, col, pts)


def draw_pause(surface: pygame.Surface, cx: int, cy: int, col: tuple, size: str = "md") -> None:
    """Pause bars."""
    if size == "sm":
        pygame.draw.rect(surface, col, (cx - 6, cy - 7, 4, 14), border_radius=1)
        pygame.draw.rect(surface, col, (cx + 2, cy - 7, 4, 14), border_radius=1)
    else:  # lg
        pygame.draw.rect(surface, col, (cx - 9, cy - 11, 6, 22), border_radius=2)
        pygame.draw.rect(surface, col, (cx + 3, cy - 11, 6, 22), border_radius=2)


def draw_bt_glyph(surface: pygame.Surface, cx: int, cy: int, col: tuple) -> None:
    """Bluetooth ᛒ glyph."""
    pygame.draw.line(surface, col, (cx,     cy - 7), (cx,     cy + 7), 2)
    pygame.draw.line(surface, col, (cx,     cy - 7), (cx + 5, cy - 3), 2)
    pygame.draw.line(surface, col, (cx + 5, cy - 3), (cx,     cy    ), 2)
    pygame.draw.line(surface, col, (cx,     cy    ), (cx + 5, cy + 3), 2)
    pygame.draw.line(surface, col, (cx + 5, cy + 3), (cx,     cy + 7), 2)


def draw_music_note(surface: pygame.Surface, cx: int, cy: int, col: tuple) -> None:
    """Music note glyph."""
    pygame.draw.circle(surface, col, (cx - 5, cy + 4), 5)
    pygame.draw.line(surface, col, (cx, cy + 4), (cx, cy - 10), 2)
    pygame.draw.line(surface, col, (cx, cy - 10), (cx + 8, cy - 14), 2)
    pygame.draw.line(surface, col, (cx + 8, cy - 14), (cx + 8, cy - 4), 2)
