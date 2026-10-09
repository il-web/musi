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
