"""Crash capture, crash-loop detection, and the rollback offer.

The capture tests crash real child processes — a native segfault and an
uncaught Python exception — because that is the whole point: faulthandler
output only exists if the process genuinely died.
"""
import os
import subprocess
import sys
import textwrap

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
import pytest

pygame.init()
pygame.display.set_mode((320, 480))

from musi.player import crashguard, updater

SRC = os.path.join(os.path.dirname(__file__), "..", "src")


@pytest.fixture(autouse=True)
def crash_dir(tmp_path, monkeypatch):
    d = tmp_path / "crash"
    monkeypatch.setenv("MUSI_CRASH_DIR", str(d))
    monkeypatch.setenv("MUSI_PREFS_PATH", str(tmp_path / "prefs.json"))
    return d


def _run_child(body: str, crash_dir) -> int:
    code = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {os.path.abspath(SRC)!r})
        from musi.player import crashguard
        crashguard.install("bad1234")
        def deep():
{textwrap.indent(textwrap.dedent(body), " " * 12)}
        deep()
    """)
    env = dict(os.environ, MUSI_CRASH_DIR=str(crash_dir))
    return subprocess.run([sys.executable, "-c", code], env=env,
                          capture_output=True, timeout=60).returncode


# ── capture ───────────────────────────────────────────────────────────────────

def test_a_native_crash_is_recorded_at_the_next_start(crash_dir):
    rc = _run_child("import faulthandler; faulthandler._sigsegv()", crash_dir)
    assert rc != 0
    crashguard.install("next")
    c = crashguard.last_crash()
    assert c is not None and c["version"] == "bad1234"
    assert "deep" in c["reason"]                  # where it died, by function
    assert "bad1234" in crashguard.read_log()


def test_an_uncaught_python_error_is_recorded(crash_dir):
    _run_child("raise ValueError('boom')", crash_dir)
    crashguard.install("next")
    c = crashguard.last_crash()
    assert c["reason"].startswith("ValueError: boom")
    assert "(deep)" in c["reason"]


def test_a_clean_exit_records_nothing(crash_dir):
    assert _run_child("pass", crash_dir) == 0
    crashguard.install("next")
    assert crashguard.last_crash() is None


def test_one_crash_is_harvested_once(crash_dir):
    _run_child("raise ValueError('boom')", crash_dir)
    crashguard.install("next")
    crashguard.install("again")
    assert len(crashguard.load_state()["crashes"]) == 1


def test_summary_of_a_fatal_error_points_at_musi_code():
    text = ('Fatal Python error: Bus error\n\nCurrent thread 0x1 (most recent call first):\n'
            '  File "/home/musi/musi/src/musi/player/screens/now_playing.py", line 437 in _scaled_icon\n'
            '  File "/usr/lib/python3/pygame/x.py", line 9 in blit\n')
    assert crashguard.summarize(text) == "Bus error — now_playing.py:437 (_scaled_icon)"


# ── crash loops ───────────────────────────────────────────────────────────────

def _crashes(version, n, now, ui_ready=True):
    state = crashguard.load_state()
    state["crashes"] = [{"t": now - 10 * i, "version": version, "reason": "Bus error",
                         "ui_ready": ui_ready} for i in range(n)]
    crashguard._save_state(state)


def test_three_crashes_after_an_update_offer_a_rollback():
    crashguard.note_update("good0000aaaa", "bad1234ffff", now=0)
    _crashes("bad1234", 3, now=1000)
    offer = crashguard.offer("bad1234", now=1000)
    assert offer == {"version": "bad1234", "target": "good0000aaaa", "count": 3,
                     "reason": "Bus error"}


@pytest.mark.parametrize("setup", ["two_crashes", "old_crashes", "no_update",
                                   "other_version", "declined", "rolled_back"])
def test_no_offer_unless_its_a_fresh_crash_loop(setup):
    now = 10_000
    crashguard.note_update("good0000", "bad1234", now=0)
    _crashes("bad1234", 2 if setup == "two_crashes" else 4,
             now=now - (crashguard.LOOP_WINDOW_S + 100 if setup == "old_crashes" else 0))
    if setup == "no_update":
        state = crashguard.load_state(); state.pop("update"); crashguard._save_state(state)
    if setup == "declined":
        crashguard.decline("bad1234")
    if setup == "rolled_back":
        crashguard.rolled_back("good0000")
    version = "other99" if setup == "other_version" else "bad1234"
    assert crashguard.offer(version, now=now) is None


def test_auto_rollback_only_when_no_frame_was_ever_drawn():
    crashguard.note_update("good0000", "bad1234", now=0)
    _crashes("bad1234", crashguard.AUTO_CRASHES, now=500, ui_ready=False)
    assert crashguard.must_auto_rollback("bad1234", now=500) == "good0000"
    _crashes("bad1234", crashguard.AUTO_CRASHES, now=500, ui_ready=True)
    assert crashguard.must_auto_rollback("bad1234", now=500) is None


def test_first_frame_marks_the_run_ready():
    crashguard.install("v1")
    crashguard.mark_ui_ready()
    assert crashguard.load_state()["run"]["ui_ready"] is True


# ── updater.rollback ──────────────────────────────────────────────────────────

def test_rollback_refuses_an_unsigned_target(monkeypatch):
    calls = []
    monkeypatch.setattr(updater, "_is_git_repo", lambda: True)
    monkeypatch.setattr(updater, "verify_signature", lambda rev: (False, "no signature"))
    monkeypatch.setattr(updater, "_git", lambda *a, **k: calls.append(a) or (0, ""))
    ok, msg = updater.rollback("good0000")
    assert not ok and "no signature" in msg
    assert not any(a[0] == "reset" for a in calls)


def test_rollback_resets_then_installs(monkeypatch):
    calls = []
    monkeypatch.setattr(updater, "_is_git_repo", lambda: True)
    monkeypatch.setattr(updater, "verify_signature", lambda rev: (True, "ok"))
    monkeypatch.setattr(updater, "_git", lambda *a, **k: calls.append(a) or (0, ""))
    monkeypatch.setattr(updater, "_install_and_restart", lambda step: (True, "Restarting…"))
    crashguard.note_update("good0000", "bad1234")
    assert updater.rollback("good0000") == (True, "Restarting…")
    assert ("reset", "--keep", "good0000") in calls
    assert "update" not in crashguard.load_state()


# ── screens ───────────────────────────────────────────────────────────────────

class _App:
    def __init__(self):
        self._stack, self.stack = [], None
        self.stack = self._stack

    def push(self, s):
        self._stack.append(s)


class _Status:
    title = artist = album = ""
    path = None
    state = "stop"
    connected = True


def test_keep_this_version_declines_and_carries_on():
    from musi.player.screens.rollback import KEEP_RECT, RollbackScreen
    from musi.player.screen import Screen

    class Next(Screen):
        def draw(self, s, st):
            pass

    app = _App()
    nxt = Next(app)
    scr = RollbackScreen(app, {"version": "bad1234", "target": "good0000",
                               "count": 3, "reason": "Bus error — x.py:1 (f)"}, then=nxt)
    app._stack.append(scr)
    scr.draw(pygame.Surface((320, 480)), _Status())
    scr.handle_touch(*KEEP_RECT.center)
    assert app._stack == [nxt]
    assert crashguard.load_state()["declined"] == "bad1234"


def test_crash_log_lists_newest_first():
    from musi.player.screens.crash_log import log_rows
    text = ("=== 2026-10-09 10:00:00 · version aaa ===\nold crash\n\n"
            "=== 2026-10-09 11:00:00 · version bbb ===\nnew crash\n\n")
    headers = [r for r, h in log_rows(text) if h]
    assert headers[0].endswith("version bbb") and headers[1].endswith("version aaa")
