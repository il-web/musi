"""Headless render of the new screens against the dev library.

    python scripts/shoot_launcher.py out/

Writes launcher-0..3.png, launcher-drag.png, music-0..3.png, clock.png,
sleep.png. Requires dev_library.db in the repo root — rebuild it by scanning a
real music folder if it is missing. Never point a live app at dev_library.db
with a different MUSI_MUSIC_ROOT: the debounced rescan prunes the whole table.
"""
import os
import sys
from pathlib import Path

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.display.set_mode((320, 480))

from musi.library.db import open_db


class Status:
    title = "Instant Crush"
    artist = "Daft Punk"
    album = "Random Access Memories"
    path = ""
    state = "play"
    connected = True
    duration = 337.0
    progress = 0.42


class App:
    def __init__(self, db):
        self.db = db
        self.stack = []

    def push(self, s):
        self.stack.append(s)

    def pop(self):
        self.stack.pop()

    def toggle_play(self):
        pass

    def sleep_remaining(self):
        return 2400.0

    def request_poll(self):
        pass


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "out")
    out.mkdir(parents=True, exist_ok=True)

    app = App(open_db(Path("dev_library.db")))
    surface = pygame.Surface((320, 480))

    from musi.player.screens.launcher import LauncherScreen
    from musi.player.screens.music import MusicScreen
    from musi.player.screens.clock import ClockScreen
    from musi.player.screens.sleep import SleepScreen

    launcher = LauncherScreen(app)
    app.stack.append(launcher)
    for i in range(4):
        launcher._car.index = i
        launcher.draw(surface, Status())
        pygame.image.save(surface, str(out / f"launcher-{i}.png"))

    launcher._car.index = 0
    launcher.on_press(240, 160)
    launcher.on_drag(150, 160)
    launcher.draw(surface, Status())
    pygame.image.save(surface, str(out / "launcher-drag.png"))
    launcher.on_release(150, 160)

    music = MusicScreen(app)
    app.stack.append(music)
    music.on_enter()            # tab 0's child loads its rows here, not in set_tab
    for i in range(4):
        music.set_tab(i)
        music.draw(surface, Status())
        pygame.image.save(surface, str(out / f"music-{i}.png"))

    for name, screen in (("clock", ClockScreen(app)), ("sleep", SleepScreen(app))):
        screen.draw(surface, Status())
        pygame.image.save(surface, str(out / f"{name}.png"))

    print(f"wrote {len(list(out.glob('*.png')))} frames to {out}")


if __name__ == "__main__":
    main()
