"""Profit-taking layer for the two-layer sell model (spec §11.1).

The sell side is split into two layers:

1. **Risk-exit** (放量跌破 -> 2-day observe -> judge -> sell):
   Phase 0 already implemented.  HIGHEST priority, always-on, not
   regime-graded.  This layer protects against trend breakdowns.

2. **Profit-taking** (regime-driven):
   Bull = trailing drawdown, Bear = gain-ladder (Task 6).
   Only acts when the risk-exit layer is NOT active.

This module provides the suppression logic that ensures the risk-exit
layer always has priority over profit-taking.  The core rule (spec §11.1):

    While a sell_observation window is active OR a risk-exit
    (technical_breakdown confirmed sell) triggered today,
    suppress profit-taking for that day.

Profit-taking triggers independently when the trend is unbroken and no
risk-exit is in progress -- it does NOT depend on the breakdown-observe
path.  This avoids re-introducing dormancy in the other direction.
"""

from __future__ import annotations


def should_suppress_profit_taking(
    *,
    sell_observation_active: bool,
    risk_exit_triggered_today: bool,
    post_sell_observation_active: bool,
) -> bool:
    """Determine whether profit-taking should be suppressed today.

    Parameters
    ----------
    sell_observation_active : bool
        True when a sell-observation window is in progress
        (``sell_observation_start_index <= index <= sell_observation_until_index``)
        or today is a sell-trigger day (the window starts today).
    risk_exit_triggered_today : bool
        True when a risk-exit sell (``technical_breakdown``) was executed
        today via ``_execute_pending``.
    post_sell_observation_active : bool
        True when a post-sell observation window is in progress
        (existing behaviour: suppress batch-level profit protection).

    Returns
    -------
    bool
        True = suppress profit-taking (risk-exit has priority).
        False = profit-taking may act normally.

    The suppression is deliberately scoped: it only fires when the
    risk-exit layer is genuinely active.  When the trend is intact and
    no risk-exit is in progress, profit-taking acts normally -- this
    avoids over-suppressing and re-introducing sell-side dormancy.
    """
    return (
        sell_observation_active
        or risk_exit_triggered_today
        or post_sell_observation_active
    )
