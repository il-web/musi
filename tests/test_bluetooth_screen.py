"""Bluetooth screen — a long device list must scroll."""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player.screens.bluetooth import ITEM_H, BluetoothScreen, _Device


class _App:
    stack: list = []


class _Status:
    title = artist = album = ""
    path = None
    state = "stop"
    connected = True


def test_a_long_device_list_scrolls():
    scr = BluetoothScreen(_App())
    # as _fetch leaves things (it runs on a worker thread)
    scr._devices = [_Device(mac=f"AA:{i:02d}", name=f"Speaker {i}") for i in range(12)]
    scr._info_msg = ""
    scr.draw(pygame.Surface((320, 480)), _Status())

    assert scr._klist.max_offset > 0
    scr.handle_scroll_start()
    scr.handle_scroll(-3 * ITEM_H)          # finger drags up
    scr.handle_scroll_end()
    assert scr._klist.first_visible() >= 2


# ── scanning ──────────────────────────────────────────────────────────────────

from musi.player.screens import bluetooth as bt  # noqa: E402


class FakeProc:
    def __init__(self, out):
        self.out = out

    def poll(self):
        return 1

    def kill(self):
        pass

    def communicate(self):
        return self.out, None


def _scan_with(monkeypatch, outputs):
    """Run _scan_thread with bluetoothctl faked: each scan attempt returns
    the next canned output; every other bluetoothctl call is recorded."""
    calls = []
    outs = iter(outputs)
    monkeypatch.setattr(bt.subprocess, "Popen", lambda *a, **k: FakeProc(next(outs)))
    monkeypatch.setattr(bt, "_bt", lambda *a: calls.append(a))
    monkeypatch.setattr(bt.time, "sleep", lambda s: None)
    scr = BluetoothScreen(_App())
    monkeypatch.setattr(scr, "_fetch", lambda: None)
    scr._scanning = True
    scr._scan_thread()
    return scr, calls


STUCK = "Failed to start discovery: org.bluez.Error.InProgress\n"


def test_a_stuck_scan_is_cleared_and_retried(monkeypatch):
    scr, calls = _scan_with(monkeypatch, [STUCK, "Discovery started\n"])
    assert ("scan", "off") in calls
    assert ("power", "off") not in calls          # first remedy was enough
    assert scr._action_msg == "" and not scr._scanning


def test_still_stuck_power_cycles_the_radio(monkeypatch):
    scr, calls = _scan_with(monkeypatch, [STUCK, STUCK, "Discovery started\n"])
    assert ("power", "off") in calls
    assert scr._action_msg == ""


def test_a_scan_that_never_starts_says_why(monkeypatch):
    scr, _ = _scan_with(monkeypatch, [STUCK, STUCK, STUCK])
    assert scr._action_msg == "Scan failed: InProgress"


def test_a_device_named_error_is_not_a_failure(monkeypatch):
    scr, calls = _scan_with(monkeypatch, ["[NEW] Device AA:BB Error Speaker\n"])
    assert scr._action_msg == "" and ("scan", "off") not in calls


def test_unnamed_audio_devices_are_listed_and_beacons_are_not():
    assert bt._is_bare_address("AA-BB-CC-DD-EE-FF", "AA:BB:CC:DD:EE:FF")
    assert not bt._is_bare_address("AirPods Pro", "AA:BB:CC:DD:EE:FF")
    assert bt._looks_like_audio("\tIcon: audio-headphones\n")
    assert bt._looks_like_audio("\tUUID: Audio Sink (0000110b-...)\n")
    assert not bt._looks_like_audio("\tManufacturerData Key: 0x004c\n")
