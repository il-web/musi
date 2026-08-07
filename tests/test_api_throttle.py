"""Login throttle.

The token is only 8 characters, which is safe *because* guessing is rate
limited. If these tests are ever deleted, the token must get longer again.
"""
from __future__ import annotations

import pytest

from musi.api.server import FAIL_FREE, LOCK_BASE_S, LOCK_MAX_S, LoginThrottle


def test_first_attempts_are_not_throttled():
    """FAIL_FREE tries are allowed; the gate checks before recording, so the
    caller is only refused on the attempt *after* the last free one."""
    t = LoginThrottle()
    for _ in range(FAIL_FREE - 1):
        t.record_failure("10.0.0.5", now=0.0)
    assert t.retry_after("10.0.0.5", now=0.0) == 0.0


def test_lockout_starts_after_the_free_attempts():
    t = LoginThrottle()
    for _ in range(FAIL_FREE):
        t.record_failure("10.0.0.5", now=0.0)
    assert t.retry_after("10.0.0.5", now=0.0) == pytest.approx(LOCK_BASE_S)


def test_lockout_doubles_and_is_capped():
    t = LoginThrottle()
    for _ in range(FAIL_FREE + 1):
        t.record_failure("10.0.0.5", now=0.0)
    assert t.retry_after("10.0.0.5", now=0.0) == pytest.approx(LOCK_BASE_S * 2)

    for _ in range(40):
        t.record_failure("10.0.0.5", now=0.0)
    assert t.retry_after("10.0.0.5", now=0.0) == pytest.approx(LOCK_MAX_S)


def test_lockout_expires():
    t = LoginThrottle()
    for _ in range(FAIL_FREE):
        t.record_failure("10.0.0.5", now=0.0)
    assert t.retry_after("10.0.0.5", now=LOCK_BASE_S + 1) == 0.0


def test_success_clears_the_counter():
    t = LoginThrottle()
    for _ in range(FAIL_FREE):
        t.record_failure("10.0.0.5", now=0.0)
    t.record_success("10.0.0.5")
    assert t.retry_after("10.0.0.5", now=0.0) == 0.0


def test_addresses_are_independent():
    """One attacker must not lock the owner out of their own device."""
    t = LoginThrottle()
    for _ in range(FAIL_FREE + 3):
        t.record_failure("10.0.0.99", now=0.0)
    assert t.retry_after("10.0.0.99", now=0.0) > 0
    assert t.retry_after("10.0.0.5", now=0.0) == 0.0


def test_brute_force_is_not_feasible():
    """Sanity-check the arithmetic the short token depends on.

    32**8 combinations at one attempt per LOCK_MAX_S, once throttling is in
    force, is far longer than any attacker will sit on your WiFi.
    """
    combos = 32 ** 8
    years = combos * LOCK_MAX_S / 2 / (365 * 24 * 3600)
    assert years > 1_000_000
