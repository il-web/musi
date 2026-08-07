"""OTA signature enforcement.

The update path pulls code from GitHub and then runs update.sh, which holds
sudo rights. Without a signature check, control of the GitHub account is
control of the device — so an unverified commit must never reach the disk.
"""
from __future__ import annotations

import pytest

from musi.player import updater


@pytest.fixture(autouse=True)
def _no_env_bypass(monkeypatch):
    monkeypatch.delenv("MUSI_ALLOW_UNSIGNED", raising=False)


def _fake_git(monkeypatch, responses: dict):
    """Route updater._git by its first argument."""
    calls: list[tuple] = []

    def fake(*args, timeout=30.0):
        calls.append(args)
        return responses.get(args[0], (0, ""))

    monkeypatch.setattr(updater, "_git", fake)
    return calls


def test_good_signature_passes(monkeypatch):
    _fake_git(monkeypatch, {"verify-commit": (0, "Good signature from Ilay")})
    ok, why = updater.verify_signature("origin/main")
    assert ok is True
    assert why == "signature ok"


def test_unsigned_commit_is_refused(monkeypatch):
    _fake_git(monkeypatch, {"verify-commit": (1, "error: no signature found")})
    ok, why = updater.verify_signature("origin/main")
    assert ok is False
    assert "signature" in why.lower()


def test_untrusted_key_is_refused(monkeypatch):
    _fake_git(monkeypatch, {
        "verify-commit": (1, "gpg: Can't check signature: No public key")})
    assert updater.verify_signature("origin/main")[0] is False


def test_env_bypass_is_opt_in(monkeypatch):
    _fake_git(monkeypatch, {"verify-commit": (1, "error: no signature found")})
    assert updater.verify_signature("origin/main")[0] is False
    monkeypatch.setenv("MUSI_ALLOW_UNSIGNED", "1")
    assert updater.verify_signature("origin/main")[0] is True


def test_apply_refuses_before_touching_the_working_tree(monkeypatch):
    """The pull must not run at all when verification fails — code on disk is
    already too late, update.sh escalates from there."""
    calls = _fake_git(monkeypatch, {
        "rev-parse": (0, "origin/main"),
        "fetch": (0, ""),
        "verify-commit": (1, "error: no signature found"),
    })
    ok, msg = updater.apply()
    assert ok is False
    assert "Refused" in msg
    assert not any(a[0] == "pull" for a in calls), "pull ran despite bad signature"


def test_apply_proceeds_when_signature_is_good(monkeypatch):
    calls = _fake_git(monkeypatch, {
        "rev-parse": (0, "origin/main"),
        "fetch": (0, ""),
        "verify-commit": (0, "Good signature"),
        "pull": (1, "pull blocked in test"),   # stop before pip/systemctl
    })
    ok, _ = updater.apply()
    assert ok is False                          # failed at the pull, not the gate
    assert any(a[0] == "pull" for a in calls)


def test_check_reports_unsigned_update_as_unavailable(monkeypatch):
    monkeypatch.setattr(updater, "_git", lambda *a, timeout=30.0: {
        "rev-parse":  (0, "abc1234"),
        "fetch":      (0, ""),
        "rev-list":   (0, "3"),
        "log":        (0, "feat: something"),
        "verify-commit": (1, "error: no signature found"),
    }.get(a[0], (0, "")))
    st = updater.check()
    assert st.behind == 3
    assert st.signed is False
    assert st.available is False, "an update we would refuse must not be offered"
