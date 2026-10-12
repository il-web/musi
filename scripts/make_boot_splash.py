"""Regenerate the boot splash: images in src/musi/player/assets/boot/ and
pi/plymouth/musi.script. Run after changing src/musi/player/boot_look.py:

    python scripts/make_boot_splash.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((1, 1))

from musi.player import boot_look  # noqa: E402

for old in boot_look.ASSETS.glob("*.png"):
    old.unlink()
files = boot_look.make_assets()
script = REPO / "pi" / "plymouth" / "musi.script"
script.write_text(boot_look.splash_script(), encoding="utf-8", newline="\n")
print(f"{len(files)} images -> {boot_look.ASSETS}")
print(f"script -> {script}")
