"""Contract test 5: regime changes within a single backtest run (Task 11 Step 2).

Verifies that ``engine.run()`` consults the per-index regime lookup for BOTH
the buy side (sizing) and the sell side (profit-taking mode) when a
``SectorRegimeProvider`` returns DIFFERENT states at different indices within
ONE run.

Regression guard: ``engine.py:350`` used to default ``regime_for_buy="neutral"``
when no provider was passed, silently downgrading every strong_buy from 20%
target to 6% (via ``strategy.py:175-177``, ``buy_scale=0.3``).  The production
wiring is now fixed, but without this test there is no guard on the per-index
regime lookup path -- a single ``engine.run()`` where the provider returns
bull early and bear late must produce a full-sized bull buy AND a downgraded
bear buy.

Tests use ``RegimeChangeProvider`` (a variant of ``FakeRegimeProvider`` from
``test_profit_taking.py`` that switches state at a split index) plus the
``DeterministicJudge`` default.  No real LLM / skill / network calls.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from app.backtest.engine import BacktestEngine
from app.backtest.models import (
    BacktestConfig,
    FundNavPoint,
    ProsperityConfig,
    SignalBar,
)
from app.backtest.observation.regime import SectorRegime

# ── helpers ─────────────────────────────────────────────────────────────────


def _navs(values: list[float]) -> list[FundNavPoint]:
    start = date(2026, 1, 1)
    return [
        FundNavPoint(date=start + timedelta(days=i), nav=v)
        for i, v in enumerate(values)
    ]


def _bars(closes: list[float], volumes: list[float]) -> list[SignalBar]:
    start = date(2026, 1, 1)
    return [
        SignalBar(
            date=start + timedelta(days=i),
            open=c,
            high=c + 0.2,
            low=c - 0.2,
            close=c,
            volume=volumes[i],
            amount=c * volumes[i],
        )
        for i, c in enumerate(closes)
    ]


def _config(**overrides: Any) -> BacktestConfig:
    values: dict[str, Any] = {
        "fund_code": "001513",
        "fund_name": "test",
        "signal_code": "sh515880",
        "signal_name": "通信ETF",
        "initial_cash": 100_000.0,
        "initial_position_pct": 0.0,
        "target_position_pct": 0.2,
        "buy_ma_window": 3,
        "buy_volume_window": 3,
        "buy_volume_ratio": 1.2,
        "buy_stand_days": 2,
        "expma_window": 3,
        "breakdown_volume_ratio": 1.0,
        # Disable the EventDetector's account-level profit_drawdown so the
        # regime-conditional layer (trailing / gain-ladder) is isolated.
        "profit_drawdown_trigger_pct": 100.0,
        "stop_loss_trigger_pct": 20.0,
        "prosperity": ProsperityConfig(score=8.0, reasons=["test"]),
    }
    values.update(overrides)
    return BacktestConfig(**values)


class RegimeChangeProvider:
    """Returns different ``SectorRegime`` states before/after ``split_index``.

    Mirrors ``FakeRegimeProvider`` from ``test_profit_taking.py`` but switches
    the regime state at ``split_index`` so a single ``engine.run()`` sees a
    regime transition (e.g. bull -> bear) within one backtest.  This is the
    key fake for contract test 5: the engine must call ``assess`` per-index
    and look up the result per-index for BOTH buy sizing and sell mode.
    """

    def __init__(
        self,
        split_index: int,
        early_state: str = "bull",
        late_state: str = "bear",
        early_tightness: str = "loose",
        late_tightness: str = "tight",
    ):
        self._split_index = split_index
        self._early = SectorRegime(
            state=early_state,  # type: ignore[arg-type]
            take_profit_tightness=early_tightness,  # type: ignore[arg-type]
            reason="fake early regime",
            skill_versions=["fake-v1"],
            source="skill",
        )
        self._late = SectorRegime(
            state=late_state,  # type: ignore[arg-type]
            take_profit_tightness=late_tightness,  # type: ignore[arg-type]
            reason="fake late regime",
            skill_versions=["fake-v1"],
            source="skill",
        )

    async def assess(self, symbol, signal_bars, as_of_index, config):
        if as_of_index < self._split_index:
            return self._early
        return self._late


# ── primary: buy sizing adapts across regime boundary ──────────────────────
#
# Regime: bull for indices 0-7, bear for indices 8-14 (split at index 8).
# Signal:  [10, 10, 10, 10, 11, 11, 11, 11, 11, 10, 11, 11, 11, 11, 11]
#                                     ^buy trigger          ^buy trigger
# Volume:  [100,100,100,100,200,100,100,100,100, 50,200,100,100,100,100]
# Fund nav:[1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,0.5,0.5,0.5,0.5,0.5,0.5,0.5]
#
# Buy trigger 1 at index 4 -> observe [5,6] -> confirm at index 6 (bull regime)
#   -> trade executes at index 7 (nav=1.0), strong_buy + bull -> full 20% target
#   -> cash_delta = -0.20 * 100,000 = -20,000
# Nav drops at index 8 -> position_pct falls below target, allowing a 2nd buy
# Buy trigger 2 at index 10 -> observe [11,12] -> confirm at index 12 (bear regime)
#   -> trade executes at index 13 (nav=0.5), strong_buy + bear -> downgrade to 6%
#   -> cash_delta = -0.06 * 90,000 = -5,400 (equity dropped to 90,000 because
#      nav fell to 0.5; without the regime downgrade it would be 0.20 * 90,000 = 18,000)
#
# The NAV drop is required: after a full bull buy the position is exactly at
# target, so no second buy can fire unless the position value falls first.


@pytest.mark.asyncio
async def test_buy_sizing_adapts_when_regime_changes_mid_run():
    """Per-index regime lookup: bull-window buy sizes full, bear-window downgrades."""
    config = _config(
        initial_position_pct=0.0,
        target_position_pct=0.2,
        profit_drawdown_trigger_pct=100.0,
    )
    engine = BacktestEngine()
    regime_provider = RegimeChangeProvider(
        split_index=8, early_state="bull", late_state="bear"
    )

    result = await engine.run(
        config=config,
        fund_nav=_navs(
            [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]
        ),
        signal_bars=_bars(
            closes=[10, 10, 10, 10, 11, 11, 11, 11, 11, 10, 11, 11, 11, 11, 11],
            volumes=[
                100, 100, 100, 100, 200, 100, 100, 100, 100, 50, 200, 100, 100, 100, 100,
            ],
        ),
        regime_provider=regime_provider,
    )

    # ── Both buys must occur in the SAME run (proves per-index lookup) ──
    buy_trades = [t for t in result.trades if t.action == "buy"]
    assert len(buy_trades) == 2, (
        f"expected exactly 2 buys (one per regime window), got {len(buy_trades)}"
    )

    # ── Buy 1: bull window, strong_buy -> full 20% target ──
    bull_buy = buy_trades[0]
    assert bull_buy.date == date(2026, 1, 8), (
        f"bull-window buy should execute at index 7 (2026-01-08), got {bull_buy.date}"
    )
    # equity at buy 1 == initial_cash (no prior position, nav=1.0)
    # cash_delta = -0.20 * initial_cash = -20,000
    assert bull_buy.cash_delta == pytest.approx(-20_000.0), (
        f"bull + strong_buy should size at full 20% target: "
        f"cash_delta = -0.20 * initial_cash = -20,000, got {bull_buy.cash_delta}"
    )

    # ── Buy 2: bear window, strong_buy -> downgrade to 6% of equity ──
    bear_buy = buy_trades[1]
    assert bear_buy.date == date(2026, 1, 14), (
        f"bear-window buy should execute at index 13 (2026-01-14), got {bear_buy.date}"
    )
    # equity at buy 2 = 80,000 (cash) + 20,000 * 0.5 (position at nav=0.5) = 90,000
    # 6% of 90,000 = 5,400 (the NAV drop is what allows the 2nd buy to fire at all;
    # without the regime downgrade it would be 0.20 * 90,000 = 18,000)
    assert bear_buy.cash_delta == pytest.approx(-5_400.0), (
        f"bear + strong_buy should downgrade to 6% of equity: "
        f"cash_delta = -0.06 * 90,000 = -5,400, got {bear_buy.cash_delta}"
    )

    # ── Cross-check via decision.target_position_delta_pct (equity-independent) ──
    # This is the cleanest assertion of the 20% vs 6% math: it directly reflects
    # buy_scale (1.0 for bull+strong_buy, 0.3 for bear/neutral) applied to the
    # 0.20 effective_target.
    buy_conf_events = [
        e for e in result.events if e["event_type"] == "buy_confirmation"
    ]
    assert len(buy_conf_events) == 2, (
        f"expected 2 buy_confirmation events, got {len(buy_conf_events)}"
    )
    bull_conf = [
        e for e in buy_conf_events if e["details"]["market_regime"] == "bull"
    ]
    bear_conf = [
        e for e in buy_conf_events if e["details"]["market_regime"] == "bear"
    ]
    assert len(bull_conf) == 1, "exactly one buy_confirmation should carry bull regime"
    assert len(bear_conf) == 1, "exactly one buy_confirmation should carry bear regime"

    bull_delta = bull_conf[0]["decision"]["target_position_delta_pct"]
    bear_delta = bear_conf[0]["decision"]["target_position_delta_pct"]
    assert bull_delta == pytest.approx(0.20, abs=1e-6), (
        f"bull + strong_buy target_position_delta_pct should be 0.20 (full target), "
        f"got {bull_delta}"
    )
    assert bear_delta == pytest.approx(0.06, abs=1e-6), (
        f"bear + strong_buy target_position_delta_pct should be 0.06 "
        f"(downgraded to 30% of 0.20 target), got {bear_delta}"
    )

    # ── The bear/bull buy_scale ratio is exactly 0.30 (the downgrade) ──
    # bear_delta / bull_delta = 0.06 / 0.20 = 0.30 = buy_scale for bear.
    # Without the per-index regime lookup, both deltas would be 0.06 (the
    # original bug: regime_for_buy defaulted to "neutral" -> buy_scale=0.3).
    assert bear_delta / bull_delta == pytest.approx(0.30, abs=1e-6), (
        f"bear/bull buy_scale ratio should be 0.30 (6% / 20%), "
        f"got {bear_delta / bull_delta}"
    )


# ── secondary: sell side switches profit-taking mode by regime ─────────────
#
# Regime: bull for indices 0-2, bear for indices 3-5 (split at index 3).
# Signal:  [10, 10.1, 10.2, 10.3, 10.4, 10.5]  (steady rise, no L1 triggers)
# Volume:  [100, 100, 100, 100, 100, 100]      (vr=1.0, below buy/sell thresholds)
# Fund nav:[1.0, 1.15, 1.05, 1.05, 1.25, 1.25]
#
# Initial position 20% (core 10% + confirmation 6% + high_position 4%).
# Index 1: nav=1.15 -> all batches peak at +15%
# Index 2 (bull): nav=1.05 -> high_position drawdown 10% >= trailing_drawdown_pct
#   -> trailing fires on high_position, sell executes at index 3
# Index 4 (bear): nav=1.25 -> confirmation +25% >= gain_ladder rung 20%
#   -> gain-ladder fires on confirmation, sell executes at index 5
#
# This proves the sell side also consults the per-index regime: trailing only
# fires in the bull window (regime.state == "bull"), gain-ladder only fires in
# the bear window (regime.state == "bear"), and both occur in ONE run.


@pytest.mark.asyncio
async def test_sell_side_switches_profit_taking_by_regime():
    """Sell side consults per-index regime: trailing in bull, gain-ladder in bear."""
    config = _config(
        initial_position_pct=0.2,
        target_position_pct=0.2,
        profit_drawdown_trigger_pct=100.0,
        trailing_drawdown_pct=10.0,
        gain_ladder_thresholds=(20.0, 30.0),
    )
    engine = BacktestEngine()
    regime_provider = RegimeChangeProvider(
        split_index=3, early_state="bull", late_state="bear"
    )

    result = await engine.run(
        config=config,
        fund_nav=_navs([1.0, 1.15, 1.05, 1.05, 1.25, 1.25]),
        signal_bars=_bars(
            closes=[10.0, 10.1, 10.2, 10.3, 10.4, 10.5],
            volumes=[100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
        ),
        regime_provider=regime_provider,
    )

    # ── Trailing event fires in the BULL window (index 2 = 2026-01-03) ──
    trailing_events = [
        e
        for e in result.events
        if e["event_type"] == "profit_drawdown"
        and e["details"].get("batch_protection") == "trailing"
    ]
    assert len(trailing_events) >= 1, (
        "trailing take-profit should fire in the bull window"
    )
    assert date.fromisoformat(trailing_events[0]["date"]) == date(2026, 1, 3), (
        f"trailing should fire at index 2 (2026-01-03, bull window), "
        f"got {trailing_events[0]['date']}"
    )

    # ── Gain-ladder event fires in the BEAR window (index 4 = 2026-01-05) ──
    gain_ladder_events = [
        e
        for e in result.events
        if e["event_type"] == "profit_drawdown"
        and e["details"].get("batch_protection") == "gain_ladder"
    ]
    assert len(gain_ladder_events) >= 1, (
        "gain-ladder take-profit should fire in the bear window"
    )
    assert date.fromisoformat(gain_ladder_events[0]["date"]) == date(2026, 1, 5), (
        f"gain-ladder should fire at index 4 (2026-01-05, bear window), "
        f"got {gain_ladder_events[0]['date']}"
    )

    # ── Both sells execute (trailing T+1 at index 3, gain-ladder T+1 at index 5) ──
    sell_trades = [t for t in result.trades if t.action == "sell"]
    assert len(sell_trades) == 2, (
        f"expected 2 sells (trailing + gain-ladder), got {len(sell_trades)}"
    )
    # Trailing sold the high_position batch on 2026-01-04 (index 3)
    assert sell_trades[0].date == date(2026, 1, 4), (
        f"trailing sell should execute at index 3 (2026-01-04), "
        f"got {sell_trades[0].date}"
    )
    assert sell_trades[0].batch_type == "high_position", (
        f"trailing should sell high_position batch, got {sell_trades[0].batch_type}"
    )
    # Gain-ladder sold the confirmation batch on 2026-01-06 (index 5)
    assert sell_trades[1].date == date(2026, 1, 6), (
        f"gain-ladder sell should execute at index 5 (2026-01-06), "
        f"got {sell_trades[1].date}"
    )
    assert sell_trades[1].batch_type == "confirmation", (
        f"gain-ladder should sell confirmation batch, got {sell_trades[1].batch_type}"
    )
