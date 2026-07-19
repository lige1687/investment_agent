"""Profit-taking layer for the two-layer sell model (spec §11.1).

The sell side is split into two layers:

1. **Risk-exit** (放量跌破 -> 2-day observe -> judge -> sell):
   Phase 0 already implemented.  HIGHEST priority, always-on, not
   regime-graded.  This layer protects against trend breakdowns.

2. **Profit-taking** (regime-driven):
   Bull = trailing drawdown, Bear = gain-ladder (Task 6).
   Only acts when the risk-exit layer is NOT active.

This module provides:
- ``should_suppress_profit_taking``: ensures risk-exit always has priority.
- ``TrailingTakeProfit``: bull regime -- sell when batch peak drawdown
  >= ``trailing_drawdown_pct`` (let profits run, loose threshold).
- ``GainLadderTakeProfit``: bear regime -- sell one batch tier when
  return hits a ladder rung (take profit directly, no drawdown wait).

Design constraints (spec §11.2, plan Task 6):
- LLM/skill gives direction only (regime state + tightness).  Gain-ladder
  thresholds (+X%/+Y%) and trailing drawdown% come from ``BacktestConfig``.
- "sell one batch tier" = sell one ``HoldingBatch`` via the engine's
  ``_select_batches_to_sell`` batch-selection (trial/high_position/confirmation
  priority).
- Bull does NOT use gain-ladder.  Bear does NOT use trailing.
- Neutral: no trailing/gain-ladder (existing cost-line/core protection only).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from app.backtest.events import BacktestEvent
    from app.backtest.models import BacktestConfig, PortfolioSnapshot
    from app.backtest.observation.regime import SectorRegime


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


# ── batch helpers (mirror engine methods, no circular import) ───────────────


def _batch_return_pct(batch: Any, nav: float) -> float:
    if batch.cost_nav <= 0:
        return 0.0
    return (nav / batch.cost_nav - 1) * 100


def _batches_by_priority(batches: list[Any], priority: list[str]) -> list[Any]:
    result: list[Any] = []
    for batch_type in priority:
        result.extend(b for b in batches if b.batch_type == batch_type)
    return result


# ── protocol for event creation (decoupled from engine) ────────────────────


class _EventFactory(Protocol):
    """Protocol for creating BacktestEvent objects (implemented by engine)."""

    def make_profit_drawdown_event(
        self,
        *,
        batch: Any,
        nav: float,
        event_date: date,
        snapshot: Any,
        batch_protection: str,
        reason: str,
        extra_details: dict[str, Any] | None = None,
    ) -> Any: ...


# ── TrailingTakeProfit (bull) ───────────────────────────────────────────────


class TrailingTakeProfit:
    """Bull regime: sell when batch peak drawdown >= trailing_drawdown_pct.

    Reuses the existing ``profit_drawdown`` event type so the engine's
    event-processing and batch-selection logic applies.  The batch is
    selected by ``target_batch_type`` and sold via ``_select_batches_to_sell``.

    Bull does NOT use gain-ladder.  In neutral/bear, ``detect`` returns None.
    """

    #: Fragile batch priority (same as engine's profit_drawdown handling).
    _PRIORITY = ["trial", "high_position", "confirmation"]

    def detect(
        self,
        batches: list[Any],
        nav: float,
        config: Any,
        regime: Any,
        snapshot: Any,
        event_date: date,
        event_factory: _EventFactory,
    ) -> Any | None:
        """Return a profit_drawdown event if trailing threshold is hit, else None."""
        if regime.state != "bull":
            return None

        threshold = config.trailing_drawdown_pct
        for batch in _batches_by_priority(batches, self._PRIORITY):
            current = _batch_return_pct(batch, nav)
            drawdown = batch.peak_return_pct - current
            if batch.peak_return_pct > 0 and drawdown >= threshold - 1e-9:
                label = _batch_label(batch.batch_type)
                return event_factory.make_profit_drawdown_event(
                    batch=batch,
                    nav=nav,
                    event_date=event_date,
                    snapshot=snapshot,
                    batch_protection="trailing",
                    reason=(
                        f"{label}基金批次最高浮盈{batch.peak_return_pct:.2f}%"
                        f"回撤{drawdown:.2f}%，触发牛市 trailing 止盈"
                    ),
                    extra_details={
                        "batch_drawdown_from_peak_pct": drawdown,
                        "trailing_drawdown_pct": threshold,
                    },
                )
        return None


# ── GainLadderTakeProfit (bear) ────────────────────────────────────────────


class GainLadderTakeProfit:
    """Bear regime: sell one batch tier when return hits a ladder rung.

    At each rung (e.g. +20%, +30%), sell one fragile batch tier.  Do NOT
    wait for drawdown -- take profit directly.  Rungs are tracked so each
    rung only fires once per backtest run.

    Bear does NOT use trailing.  In neutral/bull, ``detect`` returns None.
    """

    _PRIORITY = ["trial", "high_position", "confirmation"]

    def __init__(self):
        self._sold_rungs: list[float] = []

    def detect(
        self,
        batches: list[Any],
        nav: float,
        config: Any,
        regime: Any,
        snapshot: Any,
        event_date: date,
        event_factory: _EventFactory,
    ) -> Any | None:
        """Return a profit_drawdown event if a gain-ladder rung is hit, else None."""
        if regime.state != "bear":
            return None

        for rung in config.gain_ladder_thresholds:
            if rung in self._sold_rungs:
                continue
            for batch in _batches_by_priority(batches, self._PRIORITY):
                current = _batch_return_pct(batch, nav)
                if current >= rung - 1e-9:
                    self._sold_rungs.append(rung)
                    label = _batch_label(batch.batch_type)
                    return event_factory.make_profit_drawdown_event(
                        batch=batch,
                        nav=nav,
                        event_date=event_date,
                        snapshot=snapshot,
                        batch_protection="gain_ladder",
                        reason=(
                            f"{label}基金批次浮盈{current:.2f}%达 gain-ladder "
                            f"档位{rung:.0f}%，触发熊市分批止盈"
                        ),
                        extra_details={
                            "gain_ladder_rung": rung,
                            "batch_current_return_pct": current,
                        },
                    )
        return None


# ── helpers ────────────────────────────────────────────────────────────────


def _batch_label(batch_type: str) -> str:
    labels = {
        "core": "核心仓",
        "confirmation": "确认仓",
        "high_position": "高位/灵活仓",
        "trial": "试错仓",
    }
    return labels.get(batch_type, batch_type)

