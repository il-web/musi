"""Screen base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import pygame

from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus

if TYPE_CHECKING:
    from musi.player.app import App


class Screen(ABC):
    def __init__(self, app: "App") -> None:
        self.app = app

    def on_enter(self) -> None:
        """Called when this screen becomes the active screen."""

    def on_exit(self) -> None:
        """Called when another screen is pushed on top."""

    @abstractmethod
    def draw(self, surface: pygame.Surface, status: PlayerStatus) -> None:
        """Render the screen onto surface."""

    def handle_event(self, event: "pygame.event.Event") -> bool:
        """Handle a raw pygame event before Button mapping.

        Return True if the event was consumed (caller skips Button dispatch).
        """
        return False

    def handle_touch(self, x: int, y: int) -> "Button | None":
        """Map a touch tap to a Button. Return None to ignore the tap.

        Default: status-bar tap = BACK; bottom strip split into BACK / SELECT / PLAY_PAUSE.
        Screens with list items should override this for direct-tap navigation.
        """
        if y < 26:
            return Button.BACK
        if y > 430:
            if x < 80:
                return Button.BACK
            elif x < 240:
                return Button.SELECT
            else:
                return Button.PLAY_PAUSE
        return None

    def handle_scroll(self, dy: float) -> None:
        """Vertical drag/scroll by ``dy`` pixels (down = positive).

        List screens override this to move their scroll offset; default no-op.
        """

    # ── press / drag / release gesture (volume slider, queue reorder) ──────────

    def on_press(self, x: int, y: int) -> bool:
        """Called on touch/click down. Return True to *capture* the gesture as a
        drag — subsequent motion goes to on_drag and release to on_release,
        bypassing the default scroll/tap. Default: don't capture.
        """
        return False

    def on_drag(self, x: int, y: int) -> None:
        """Called on motion while a gesture is captured (current finger pos)."""

    def on_release(self, x: int, y: int) -> None:
        """Called when a captured gesture is released (final finger pos)."""

    def handle(self, button: Button, status: PlayerStatus) -> None:
        """Handle a button press. Default: BACK pops the screen."""
        if button == Button.BACK and len(self.app.stack) > 1:
            self.app.pop()
