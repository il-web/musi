"""Input abstraction — maps keyboard keys (dev) and GPIO buttons (Pi) to Button events."""

from enum import Enum, auto

import pygame


class Button(Enum):
    PLAY_PAUSE = auto()
    NEXT       = auto()
    PREV       = auto()
    UP         = auto()
    DOWN       = auto()
    SELECT     = auto()
    BACK       = auto()
    VOL_UP     = auto()
    VOL_DOWN   = auto()


# Keyboard → Button mapping for Windows development
_KEY_MAP: dict[int, Button] = {
    pygame.K_SPACE:      Button.PLAY_PAUSE,
    pygame.K_RIGHT:      Button.NEXT,
    pygame.K_LEFT:       Button.PREV,
    pygame.K_UP:         Button.UP,
    pygame.K_DOWN:       Button.DOWN,
    pygame.K_RETURN:     Button.SELECT,
    pygame.K_ESCAPE:     Button.BACK,
    pygame.K_BACKSPACE:  Button.BACK,
    pygame.K_EQUALS:     Button.VOL_UP,
    pygame.K_PLUS:       Button.VOL_UP,
    pygame.K_MINUS:      Button.VOL_DOWN,
}


def key_to_button(key: int) -> Button | None:
    return _KEY_MAP.get(key)
