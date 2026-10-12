"""System update notice — install.sh over SSH, then Restart or Refresh UI."""
import os
import time

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
import pytest

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player import sysupdate

UPDATE_SH = """\
LATEST_STEP=13
REBOOT_STEPS="5 12"
user_11() { :; }
root_12() { :; }
user_13() { :; }
"""


@pytest.fixture
def dev(tmp_path):
    upd = tmp_path / "update.sh"
    upd.write_text(UPDATE_SH)
    root = tmp_path / "update-root.sh"
    state = tmp_path / "update-level"
    marker = tmp_path / "system-update.json"

    def check(**kw):
        kw.setdefault("boot_time", 1000.0)
        kw.setdefault("started", 2000.0)
        return sysupdate.check(update_sh=upd, root_script=root, state=state,
                               marker=marker, device=True, **kw)
    return check, root, state, marker


def _level(state, n, mtime):
    state.write_text(f"{n}\n")
    os.utime(state, (mtime, mtime))


def test_root_step_waiting_on_install_sh(dev):
    check, root, state, marker = dev
    _level(state, 11, 1500)
    root.write_text("LATEST_STEP=11\n")
    su = check()
    assert su.kind == "install" and (su.applied, su.latest) == (11, 13)
    assert '"from": 11' in marker.read_text()


def test_user_only_steps_need_no_install(dev):
    check, root, state, marker = dev
    _level(state, 12, 1500)                     # only user_13 left
    root.write_text("LATEST_STEP=11\n")
    assert check().kind == "none"


def test_after_install_a_reboot_step_asks_for_restart_until_rebooted(dev):
    check, root, state, marker = dev
    _level(state, 11, 1500)
    root.write_text("LATEST_STEP=11\n")
    assert check().kind == "install"
    root.write_text("LATEST_STEP=13\n")          # install.sh ran…
    _level(state, 13, 3000)                      # …and seeded the level
    assert check().kind == "reboot"              # step 12 needs a reboot
    assert check(boot_time=3500.0).kind == "none"  # rebooted since
    assert not marker.exists()


def test_after_install_without_reboot_steps_refresh_is_enough(dev):
    check, root, state, marker = dev
    _level(state, 12, 1500)
    marker.write_text('{"from": 12}')            # waiting since level 12
    _level(state, 13, 3000)
    assert check(started=2000.0).kind == "refresh"
    assert check(started=3100.0).kind == "none"   # the UI restarted since


def test_nothing_on_a_dev_machine(tmp_path):
    (tmp_path / "update.sh").write_text(UPDATE_SH)
    su = sysupdate.check(update_sh=tmp_path / "update.sh",
                         root_script=tmp_path / "none", state=tmp_path / "lvl",
                         marker=tmp_path / "m.json", device=False)
    assert su.kind == "none"


def test_real_update_sh_lists_reboot_steps():
    text = sysupdate.UPDATE_SH.read_text(encoding="utf-8")
    assert {5, 9, 12} <= sysupdate._reboot_steps(text)
    assert 12 in sysupdate._root_steps(text)


def test_notice_pops_up_once_per_state(tmp_path, monkeypatch):
    from musi.player.screens import system_update
    marker = tmp_path / "m.json"
    monkeypatch.setattr(sysupdate, "MARKER", marker)
    kind = {"k": "install"}
    monkeypatch.setattr(sysupdate, "check",
                        lambda: sysupdate.SystemUpdate(kind["k"], 11, 12))
    monkeypatch.setattr(sysupdate.mark_shown, "__defaults__", (marker,))

    class App:
        stack = []

        def push(self, s):
            self.stack.append(s)

        def pop(self):
            self.stack.pop()

    app = App()
    system_update.maybe_show(app)
    system_update.maybe_show(app)
    assert len(app.stack) == 1                    # once for "install"
    kind["k"] = "reboot"
    system_update.maybe_show(app)
    assert len(app.stack) == 2                    # and once more for "reboot"


@pytest.mark.parametrize("kind", ["install", "reboot", "refresh"])
def test_screens_draw_each_state(kind, monkeypatch):
    from musi.player.mpd_client import PlayerStatus
    from musi.player.screens.system_update import SystemUpdateScreen
    from musi.player.screens.updates import UpdatesScreen
    su = sysupdate.SystemUpdate(kind, 11, 12)
    monkeypatch.setattr(sysupdate, "check", lambda: su)
    acted = []
    monkeypatch.setattr(sysupdate, "act", acted.append)
    st = PlayerStatus(state="stop", path="", title="", artist="", album="",
                      elapsed=0.0, duration=0.0, volume=50, shuffle=False,
                      repeat=False, queue_pos=-1, queue_len=0)

    class App:
        stack = []

        def pop(self):
            pass
    s = SystemUpdateScreen(App(), su)
    surf = pygame.Surface((320, 480))
    s.draw(surf, st)
    if kind == "install":
        assert s._btn is None
    else:
        s.handle_touch(*s._btn.center)
        assert acted == [kind]

    u = UpdatesScreen(App())
    u._status = None
    u.draw(surf, st)
    assert (u._sys_btn is None) == (kind == "install")
