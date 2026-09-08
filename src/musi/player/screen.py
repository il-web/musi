"""Screen base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import pygame

from musi.player import statusbar
from musi.player.input import Button
from musi.player.mpd_client import PlayerStatus

if TYPE_CHECKING:
    from musi.player.app import App


class Screen(ABC):
    # Screens with continuous animation (spinners, progress popups) set this
    # True so the app keeps full frame rate and never dims/sleeps while they
    # are on top.
    animates: bool = False

    # Per-screen overrides for the inactivity timeouts, in seconds.
    # None → use the app-wide MUSI_DIM_S / MUSI_OFF_S defaults.
    dim_after: "float | None" = None
    off_after: "float | None" = None

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

        Default: a status-bar tap returns to the launcher. Going back one step
        is the left-edge swipe, resolved centrally in app.py. Screens with list
        items should override this for direct-tap navigation.
        """
        if y < statusbar.BAR_H:
            return Button.HOME
        return None

    def handle_scroll(self, dy: float) -> None:
        """Vertical drag/scroll by ``dy`` pixels (down = positive).

        List screens override this to move their scroll offset; default no-op.
        """

    def handle_scroll_start(self) -> None:
        """Finger/mouse down that may become a scroll — stop any coasting."""

    def handle_scroll_end(self) -> None:
        """Scroll gesture released — list screens start momentum coasting."""

    def handle_long_press(self, x: int, y: int) -> bool:
        """Finger held ~0.5 s without moving. Return True if handled —
        the release then does NOT fire as a tap. Default: not handled.
        """
        return False

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

    def go_back(self) -> None:
        """Back navigation — the edge swipe and the BACK button both land here.

        Default: pop one screen. Screens holding internal state (a password
        entry, a sub-mode) override this to unwind one step before popping, so
        a swipe never throws away more than the user expects.
        """
        if len(self.app.stack) > 1:
            self.app.pop()

    def handle(self, button: Button, status: PlayerStatus) -> None:
        """Handle a button press. BACK goes back one step, HOME to the launcher."""
        if button == Button.BACK:
            self.go_back()
        elif button == Button.HOME:
            self.app.go_home()
