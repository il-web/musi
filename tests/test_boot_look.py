"""Boot look — the Plymouth splash and the app's loading screen must match,
and the hand-off must never show a console."""
import os
import re
import shutil
import subprocess
from pathlib import Path

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
import pytest

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player import boot_look, splash, theme

REPO = Path(__file__).resolve().parent.parent
UPDATE_SH = REPO / "update.sh"
INSTALL_SH = REPO / "install.sh"
BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(BASH is None, reason="bash not available")


def test_shipped_images_are_current(tmp_path):
    """assets/boot is what make_assets draws today — regenerate if this fails
    (python scripts/make_boot_splash.py)."""
    fresh = boot_look.make_assets(tmp_path)
    for f in fresh:
        shipped = boot_look.ASSETS / f.name
        assert shipped.exists(), f.name
        a, b = pygame.image.load(str(f)), pygame.image.load(str(shipped))
        assert a.get_size() == b.get_size(), f.name
        assert pygame.image.tobytes(a, "RGBA") == pygame.image.tobytes(b, "RGBA"), f.name


def test_shipped_script_is_current():
    script = (REPO / "pi" / "plymouth" / "musi.script").read_text(encoding="utf-8")
    assert script == boot_look.splash_script()


def _splash_frame(t: float) -> pygame.Surface:
    """What Plymouth composites at ``t``: background, ring frames, wordmark,
    status — from the shipped images and the script's own positions."""
    s = pygame.Surface((320, 480))
    s.fill(theme.BG)
    script = boot_look.splash_script()
    for ph in sorted(boot_look.phases(t), reverse=True):
        f = int(round(ph * boot_look.FRAMES)) % boot_look.FRAMES
        s.blit(pygame.image.load(str(boot_look.ASSETS / f"ring-{f:02d}.png")), (0, 0))
    wx, wy = map(int, re.search(r"word\.SetPosition\(ox \+ (\d+), oy \+ (\d+)", script).groups())
    sx, sy = map(int, re.search(r"status\.SetPosition\(ox \+ (\d+), oy \+ (\d+)", script).groups())
    s.blit(pygame.image.load(str(boot_look.ASSETS / "wordmark.png")), (wx, wy))
    s.blit(pygame.image.load(str(boot_look.ASSETS / "status-starting.png")), (sx, sy))
    return s


@pytest.mark.parametrize("t", [0.0, 0.37, 1.1, 2.0])
def test_app_draws_exactly_what_the_splash_shows(t):
    app = pygame.Surface((320, 480))
    boot_look.draw(app, t, boot_look.STARTING, None)
    assert pygame.image.tobytes(app, "RGB") == pygame.image.tobytes(_splash_frame(t), "RGB")


def test_rings_fade_toward_the_background_without_alpha():
    r0, c0, w0 = boot_look.ring(0.0)
    r1, c1, w1 = boot_look.ring(0.97)
    assert r0 == boot_look.R0 and r1 > r0
    assert sum(c1) < sum(c0)                     # fainter as it travels
    assert len(c0) == 3                          # opaque colours only


def test_loading_screen_continues_the_bar_and_draws():
    from musi.player.screens.loading import LoadingScreen

    class App:
        status = type("S", (), {"connected": False})()

    s = LoadingScreen(App())
    s.on_enter()
    assert s._progress == boot_look.APP_START
    assert s._message == boot_look.CONNECTING
    s._started = True                            # don't start the real work
    s.draw(pygame.Surface((320, 480)), None)


# ── hand-off ──────────────────────────────────────────────────────────────────

def test_release_is_a_no_op_off_the_device(monkeypatch):
    monkeypatch.setattr(splash.sys, "platform", "win32")
    assert splash.release(run=lambda *a, **k: pytest.fail("ran")) is False


def _device(monkeypatch):
    monkeypatch.setattr(splash.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)


def test_release_quits_through_sudo_first(monkeypatch):
    """Plymouth answers only to root: the sudo rule is the way that works."""
    _device(monkeypatch)
    state = {"up": True, "calls": []}

    def run(cmd, **kw):
        state["calls"].append(cmd)
        if cmd[0] == "sudo":
            state["up"] = False

    assert splash.release(run=run, is_running=lambda: state["up"]) is True
    assert state["calls"] == [["sudo", "-n", "/usr/bin/plymouth", "quit", "--retain-splash"]]


def test_release_waits_until_the_splash_has_let_go(monkeypatch):
    """Opening the display under Plymouth = no DRM master = frozen panel."""
    _device(monkeypatch)
    t = {"now": 0.0}
    gone_at = 12.0                                   # the boot-end fallback

    def sleep(dt):
        t["now"] += dt

    up = lambda: t["now"] < gone_at                  # noqa: E731
    assert splash.release(run=lambda *a, **k: None, is_running=up,
                          sleep=sleep, clock=lambda: t["now"]) is True
    assert t["now"] >= gone_at                       # didn't return early


def test_release_does_nothing_when_no_splash(monkeypatch):
    _device(monkeypatch)
    assert splash.release(run=lambda *a, **k: pytest.fail("ran"),
                          is_running=lambda: False) is False


def test_running_reads_the_process_list(tmp_path):
    (tmp_path / "1").mkdir()
    (tmp_path / "1" / "comm").write_text("systemd")
    (tmp_path / "self").mkdir()
    assert splash.running(tmp_path) is False
    (tmp_path / "412").mkdir()
    (tmp_path / "412" / "comm").write_text("plymouthd")
    assert splash.running(tmp_path) is True


def test_ui_service_no_longer_quits_the_splash_early():
    unit = (REPO / "pi" / "musi-ui.service").read_text(encoding="utf-8")
    assert "ExecStartPost" not in unit


def test_app_releases_the_splash_before_opening_the_display():
    src = (REPO / "src" / "musi" / "player" / "app.py").read_text(encoding="utf-8")
    run = src[src.index("def run(self"):]
    assert run.index("splash.release()") < run.index("pygame.display.set_mode")


# ── update step 12 ────────────────────────────────────────────────────────────

def _extract(source: str, name: str) -> str:
    start = source.index(f"{name}() {{")
    depth = 0
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
    raise AssertionError(name)


@needs_bash
def test_root_12_installs_the_theme_and_hides_the_console(tmp_path):
    root = tmp_path / "root"
    boot = root / "boot" / "firmware"
    boot.mkdir(parents=True)
    cmdline = boot / "cmdline.txt"
    cmdline.write_text("console=serial0,115200 console=tty1 root=PARTUUID=x rootwait "
                       "fbcon=map:10 quiet\n")
    src = tmp_path / "theme"
    src.mkdir()
    (src / "musi.script").write_text("# script\n")
    (src / "ring-00.png").write_bytes(b"png")
    log = tmp_path / "calls.log"
    fake = tmp_path / "fake-systemctl"
    fake.write_text(f'#!/bin/sh\necho "$@" >> "{log.as_posix()}"\n')
    fake.chmod(0o755)
    ok = tmp_path / "fake-visudo"
    ok.write_text("#!/bin/sh\nexit 0\n")
    ok.chmod(0o755)

    body = _extract(UPDATE_SH.read_text(encoding="utf-8"), "root_12")
    script = f'set -eu\n{body}\nroot_12 "$1" "$2" "$3" "$4"\nroot_12 "$1" "$2" "$3" "$4"\n'
    proc = subprocess.run([BASH, "-c", script, "bash", root.as_posix(), fake.as_posix(),
                           src.as_posix(), ok.as_posix()], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr

    theme_dir = root / "usr" / "share" / "plymouth" / "themes" / "musi"
    assert (theme_dir / "musi.script").exists() and (theme_dir / "ring-00.png").exists()

    line = cmdline.read_text()
    assert line.count("\n") == 1                                # still one line
    toks = line.split()
    assert "console=tty3" in toks and "console=tty1" not in toks
    for tok in ("quiet", "splash", "loglevel=3", "logo.nologo",
                "vt.global_cursor_default=0", "plymouth.ignore-serial-consoles",
                "fbcon=map:10"):
        assert toks.count(tok) == 1, tok                          # idempotent

    assert "mask getty@tty1.service" in log.read_text()
    dropin = (root / "etc" / "systemd" / "system" / "plymouth-quit.service.d"
              / "musi.conf").read_text()
    assert "--retain-splash" in dropin and "$$i" in dropin
    rule = (root / "etc" / "sudoers.d" / "musi-splash").read_text()
    assert "NOPASSWD: /usr/bin/plymouth quit --retain-splash" in rule


def test_install_sh_mirrors_step_12():
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "plymouth-text" not in text
    for needle in ("/usr/local/lib/musi/plymouth", "src/musi/player/assets/boot/*.png",
                   "console=tty3", "vt.global_cursor_default=0",
                   "mask getty@tty1.service", "plymouth-quit.service.d",
                   "/usr/bin/plymouth quit --retain-splash"):
        assert needle in text, needle
    assert re.search(r"^LATEST_STEP=12$", UPDATE_SH.read_text(encoding="utf-8"), re.M)
