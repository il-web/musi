"""Power screen — the UI refresh action restarts only the player service."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player.screens import power as power_mod


class FakeStatus:
    title = ""
    artist = ""
    album = ""
    path = ""
    state = "stop"
    connected = True
    duration = 0.0
    progress = 0.0


class FakeApp:
    db = None

    def __init__(self):
        self.stack = [None, None]

    def pop(self):
        self.stack.pop()


def _screen(monkeypatch):
    """Power screen with hardening stubbed — no real overlayfs probing."""
    monkeypatch.setattr(power_mod.hardening, "overlay_active", lambda: False)
    monkeypatch.setattr(power_mod.hardening, "overlay_configured", lambda: False)
    s = power_mod.PowerScreen(FakeApp())
    s.on_enter()
    return s


def _tap(screen, rect):
    screen.handle_touch(rect.centerx, rect.centery)


def test_refresh_rect_does_not_overlap_the_other_actions():
    rects = [power_mod.SHUTDOWN_RECT, power_mod.REBOOT_RECT,
             power_mod.REFRESH_RECT, power_mod.LOCK_RECT]
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            assert not a.colliderect(b), f"{a} overlaps {b}"


def test_refresh_asks_for_confirmation_first(monkeypatch):
    calls = []
    monkeypatch.setattr(power_mod.subprocess, "Popen",
                        lambda *a, **k: calls.append(a))
    s = _screen(monkeypatch)
    _tap(s, power_mod.REFRESH_RECT)
    assert s._pending == "refresh"
    assert calls == []              # nothing ran on the first tap


def test_confirming_refresh_restarts_the_user_service(monkeypatch):
    calls = []
    monkeypatch.setattr(power_mod.subprocess, "Popen",
                        lambda *a, **k: calls.append(a[0]))
    s = _screen(monkeypatch)
    _tap(s, power_mod.REFRESH_RECT)
    _tap(s, power_mod.CONFIRM_RECT)
    assert calls == [["systemctl", "--user", "restart", "musi-ui"]]


def test_refresh_never_touches_sudo_or_the_whole_system(monkeypatch):
    """A UI refresh must not reboot the Pi — and needs no sudoers entry."""
    calls = []
    monkeypatch.setattr(power_mod.subprocess, "Popen",
                        lambda *a, **k: calls.append(a[0]))
    s = _screen(monkeypatch)
    _tap(s, power_mod.REFRESH_RECT)
    _tap(s, power_mod.CONFIRM_RECT)
    argv = calls[0]
    assert "sudo" not in argv
    assert "reboot" not in argv and "poweroff" not in argv


def test_cancelling_refresh_runs_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(power_mod.subprocess, "Popen",
                        lambda *a, **k: calls.append(a[0]))
    s = _screen(monkeypatch)
    _tap(s, power_mod.REFRESH_RECT)
    _tap(s, power_mod.CANCEL_RECT)
    assert s._pending is None
    assert calls == []


def test_reboot_still_uses_sudo_systemctl(monkeypatch):
    """The existing actions must be unaffected by the new one."""
    calls = []
    monkeypatch.setattr(power_mod.subprocess, "Popen",
                        lambda *a, **k: calls.append(a[0]))
    s = _screen(monkeypatch)
    _tap(s, power_mod.REBOOT_RECT)
    _tap(s, power_mod.CONFIRM_RECT)
    assert calls == [["sudo", "systemctl", "reboot", "-i"]]


def test_draw_runs_in_both_states(monkeypatch):
    surface = pygame.Surface((320, 480))
    s = _screen(monkeypatch)
    s.draw(surface, FakeStatus())
    _tap(s, power_mod.REFRESH_RECT)
    s.draw(surface, FakeStatus())
