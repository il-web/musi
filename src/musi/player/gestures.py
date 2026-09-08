"""Pure gesture resolution — no pygame, no state, no side effects.

Kept out of app.py so the thresholds live in one place and the decision can be
unit-tested directly, without synthesising touch events.
"""
from __future__ import annotations

EDGE_W       = 30     # px from the left edge a back swipe must start within
SWIPE_MIN_PX = 60     # minimum rightward travel before the swipe fires
SWIPE_RATIO  = 1.5    # horizontal travel must beat vertical by this factor


def resolve_edge_swipe(start_x: float, total_dx: float, total_dy: float) -> bool:
    """True when a drag qualifies as a left-edge back swipe.

    ``start_x`` is where the finger landed. The deltas are cumulative
    displacement since then, right and down positive.

    The ratio test is what keeps this clear of list scrolling: a finger that
    started at the edge and travelled mostly downward is a scroll, not a swipe.
    """
    if start_x > EDGE_W:
        return False
    if total_dx < SWIPE_MIN_PX:
        return False
    return total_dx > abs(total_dy) * SWIPE_RATIO
