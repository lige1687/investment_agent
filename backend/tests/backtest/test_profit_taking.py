"""Tests for the two-layer sell model with risk-exit priority (Task 5).

The sell side is split into two layers:
- Risk-exit (放量跌破 -> observe -> judge -> sell): HIGHEST priority
- Profit-taking (regime-driven): suppressed while risk-exit is active

Tests use DeterministicJudge + a fake regime provider for determinism.
No real LLM / skill / network calls.
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
from app.backtest.profit_taking import should_suppress_profit_taking

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
        "initial_position_pct": 0.8,
        "target_position_pct": 0.8,
        "buy_ma_window": 3,
        "buy_volume_window": 3,
        "buy_volume_ratio": 1.2,
        "buy_stand_days": 2,
        "expma_window": 3,
        "breakdown_volume_ratio": 1.0,
        "profit_drawdown_trigger_pct": 5.0,
        "stop_loss_trigger_pct": 20.0,
        "prosperity": ProsperityConfig(score=8.0, reasons=["test"]),
    }
    values.update(overrides)
    return BacktestConfig(**values)


class FakeRegimeProvider:
    """Returns a fixed SectorRegime for every assess() call."""

    def __init__(self, state: str = "neutral", tightness: str = "normal"):
        self._regime = SectorRegime(
            state=state,  # type: ignore[arg-type]
            take_profit_tightness=tightness,  # type: ignore[arg-type]
            reason="fake regime",
            skill_versions=["fake-v1"],
            source="skill",
        )

    async def assess(self, symbol, signal_bars, as_of_index, config):
        return self._regime


# ── unit: should_suppress_profit_taking ─────────────────────────────────────


def test_suppress_when_sell_observation_active():
    assert (
        should_suppress_profit_taking(
            sell_observation_active=True,
            risk_exit_triggered_today=False,
            post_sell_observation_active=False,
        )
        is True
    )


def test_no_suppress_when_trend_intact():
    assert (
        should_suppress_profit_taking(
            sell_observation_active=False,
            risk_exit_triggered_today=False,
            post_sell_observation_active=False,
        )
        is False
    )


def test_suppress_when_risk_exit_triggered_today():
    assert (
        should_suppress_profit_taking(
            sell_observation_active=False,
            risk_exit_triggered_today=True,
            post_sell_observation_active=False,
        )
        is True
    )


def test_suppress_when_post_sell_observation_active():
    assert (
        should_suppress_profit_taking(
            sell_observation_active=False,
            risk_exit_triggered_today=False,
            post_sell_observation_active=True,
        )
        is True
    )


# ── integration: breakdown-observe suppresses profit-taking ────────────────
#
# Signal:  [10, 10, 10, 10, 12, 12, 11, 10, 10, 10]
#                                          ^  ^  ^
#                                  trigger  obs obs  execute
# Fund nav: [1.0, 1.0, 1.0, 1.0, 1.2, 1.3, 1.25, 1.15, 1.1, 1.05]
#
# Sell trigger at index 6 (close=11 < EXPMA=11.25, prev close=12 >= EXPMA=11.5).
# Observation window [7, 8]: both bars below EXPMA -> DeterministicJudge confirms.
# Sell executes at index 9 (T+3).
#
# During observation (indices 6-8), the portfolio drawdown from peak (24%)
# exceeds profit_drawdown_trigger_pct (5%), so profit_drawdown WOULD fire
# from the EventDetector -- but it must be suppressed by the risk-exit layer.


@pytest.mark.asyncio
async def test_breakdown_observation_suppresses_profit_taking():
    """(a) While sell-observation is active, no profit_drawdown events fire."""
    config = _config()
    engine = BacktestEngine()
    regime_provider = FakeRegimeProvider(state="neutral")

    result = await engine.run(
        config=config,
        fund_nav=_navs([1.0, 1.0, 1.0, 1.0, 1.2, 1.3, 1.25, 1.15, 1.1, 1.05]),
        signal_bars=_bars(
            closes=[10, 10, 10, 10, 12, 12, 11, 10, 10, 10],
            volumes=[100, 100, 100, 100, 150, 100, 150, 100, 100, 100],
        ),
        regime_provider=regime_provider,
    )

    # Dates for indices 6, 7, 8 (observation window) and 9 (execution)
    obs_dates = {
        date(2026, 1, 7),  # index 6 (trigger day)
        date(2026, 1, 8),  # index 7 (obs day 1)
        date(2026, 1, 9),  # index 8 (obs day 2, confirmation)
    }

    # No profit_drawdown events during the observation window
    profit_events_during_obs = [
        e
        for e in result.events
        if e["event_type"] == "profit_drawdown"
        and date.fromisoformat(e["date"]) in obs_dates
    ]
    assert (
        profit_events_during_obs == []
    ), "profit_drawdown should be suppressed during sell-observation window"

    # The risk-exit sell should fire (technical_breakdown)
    sell_trades = [t for t in result.trades if t.action == "sell"]
    assert len(sell_trades) >= 1, "risk-exit sell should execute"
    risk_exit_sells = [t for t in sell_trades if t.event_type == "technical_breakdown"]
    assert len(risk_exit_sells) >= 1, "at least one sell should be from risk-exit"


@pytest.mark.asyncio
async def test_risk_exit_execution_day_suppresses_profit_taking():
    """(c) On the execution day, only the risk-exit sells, no profit_drawdown."""
    config = _config()
    engine = BacktestEngine()
    regime_provider = FakeRegimeProvider(state="neutral")

    result = await engine.run(
        config=config,
        fund_nav=_navs([1.0, 1.0, 1.0, 1.0, 1.2, 1.3, 1.25, 1.15, 1.1, 1.05]),
        signal_bars=_bars(
            closes=[10, 10, 10, 10, 12, 12, 11, 10, 10, 10],
            volumes=[100, 100, 100, 100, 150, 100, 150, 100, 100, 100],
        ),
        regime_provider=regime_provider,
    )

    exec_date = date(2026, 1, 10)  # index 9

    # No profit_drawdown events on the execution day
    profit_events_on_exec = [
        e
        for e in result.events
        if e["event_type"] == "profit_drawdown"
        and date.fromisoformat(e["date"]) == exec_date
    ]
    assert (
        profit_events_on_exec == []
    ), "profit_drawdown should be suppressed on risk-exit execution day"

    # The sell on or after exec_date should be from technical_breakdown
    exec_sells = [
        t for t in result.trades if t.action == "sell" and t.date >= exec_date
    ]
    assert len(exec_sells) >= 1
    assert all(
        t.event_type == "technical_breakdown" for t in exec_sells
    ), "sells on execution day should be from risk-exit, not profit-taking"


# ── integration: trend intact -> profit-taking fires normally ───────────────
#
# Signal:  [10, 10.1, 10.2, 10.3, 10.4]  (steady rise, no breakdown)
# Fund nav: [1.0, 1.1, 1.3, 1.2, 1.18]   (peak at 1.3, drawdown to 1.18)
#
# No sell trigger -> no observation window -> profit-taking acts normally.
# Portfolio peaks at ~24% (nav 1.3), draws down to ~14% (nav 1.18),
# drawdown ~9.6% >= profit_drawdown_trigger_pct (5%) -> profit_drawdown fires.


@pytest.mark.asyncio
async def test_trend_intact_profit_taking_fires_normally():
    """(b) When trend is intact and no risk-exit is active, profit-taking fires."""
    config = _config()
    engine = BacktestEngine()
    regime_provider = FakeRegimeProvider(state="neutral")

    result = await engine.run(
        config=config,
        fund_nav=_navs([1.0, 1.1, 1.3, 1.2, 1.18]),
        signal_bars=_bars(
            closes=[10.0, 10.1, 10.2, 10.3, 10.4],
            volumes=[100.0, 100.0, 100.0, 100.0, 100.0],
        ),
        regime_provider=regime_provider,
    )

    # profit_drawdown event should appear
    profit_events = [e for e in result.events if e["event_type"] == "profit_drawdown"]
    assert (
        len(profit_events) >= 1
    ), "profit_drawdown should fire when trend is intact and no risk-exit active"

    # A sell should execute
    sell_trades = [t for t in result.trades if t.action == "sell"]
    assert len(sell_trades) >= 1, "profit-taking sell should execute"


@pytest.mark.asyncio
async def test_no_sell_trigger_no_observation_profit_takes():
    """Additional: no breakdown trigger means no observation window at all."""
    config = _config()
    engine = BacktestEngine()

    result = await engine.run(
        config=config,
        fund_nav=_navs([1.0, 1.1, 1.3, 1.2, 1.18]),
        signal_bars=_bars(
            closes=[10.0, 10.1, 10.2, 10.3, 10.4],
            volumes=[100.0, 100.0, 100.0, 100.0, 100.0],
        ),
    )

    # No technical_breakdown events (no sell trigger)
    breakdown_events = [
        e for e in result.events if e["event_type"] == "technical_breakdown"
    ]
    assert len(breakdown_events) == 0


# ── Task 6: bull trailing + bear gain-ladder ───────────────────────────────
#
# Tests use profit_drawdown_trigger_pct=100 to disable the EventDetector's
# account-level profit_drawdown, isolating the regime-conditional layer.


@pytest.mark.asyncio
async def test_bull_trailing_sells_on_drawdown():
    """Bull + batch peak 15% draws down to 5% (10% drawdown) -> trailing sells."""
    config = _config(
        initial_position_pct=0.2,
        target_position_pct=0.2,
        profit_drawdown_trigger_pct=100.0,  # disable EventDetector profit_drawdown
        trailing_drawdown_pct=10.0,
    )
    engine = BacktestEngine()
    regime_provider = FakeRegimeProvider(state="bull", tightness="loose")

    result = await engine.run(
        config=config,
        fund_nav=_navs([1.0, 1.15, 1.05, 1.05]),
        signal_bars=_bars(
            closes=[10, 10.1, 10.2, 10.2],
            volumes=[100, 100, 100, 100],
        ),
        regime_provider=regime_provider,
    )

    sell_trades = [t for t in result.trades if t.action == "sell"]
    assert len(sell_trades) >= 1, "trailing should sell in bull regime"
    # The sell should be from profit_drawdown (trailing)
    assert all(t.event_type == "profit_drawdown" for t in sell_trades)
    # Verify a trailing event was emitted
    trailing_events = [
        e
        for e in result.events
        if e["event_type"] == "profit_drawdown"
        and e["details"].get("batch_protection") == "trailing"
    ]
    assert len(trailing_events) >= 1


@pytest.mark.asyncio
async def test_bear_gain_ladder_sells_at_rungs():
    """Bear +20% -> gain-ladder sells one tier, +30% -> another, between no sell."""
    config = _config(
        initial_position_pct=0.2,
        target_position_pct=0.2,
        profit_drawdown_trigger_pct=100.0,
        gain_ladder_thresholds=(20.0, 30.0),
    )
    engine = BacktestEngine()
    regime_provider = FakeRegimeProvider(state="bear", tightness="tight")

    result = await engine.run(
        config=config,
        fund_nav=_navs([1.0, 1.20, 1.25, 1.30, 1.30]),
        signal_bars=_bars(
            closes=[10, 10.1, 10.2, 10.3, 10.3],
            volumes=[100, 100, 100, 100, 100],
        ),
        regime_provider=regime_provider,
    )

    sell_trades = [t for t in result.trades if t.action == "sell"]
    assert len(sell_trades) == 2, f"expected 2 gain-ladder sells, got {len(sell_trades)}"

    # First sell at +20% rung (executes day after trigger)
    assert sell_trades[0].date == date(2026, 1, 3)  # index 2
    assert sell_trades[0].batch_type == "high_position"

    # Second sell at +30% rung (executes day after trigger)
    assert sell_trades[1].date == date(2026, 1, 5)  # index 4
    assert sell_trades[1].batch_type == "confirmation"

    # No sell between rungs (index 3 = 2026-01-04)
    sell_dates = {t.date for t in sell_trades}
    assert date(2026, 1, 4) not in sell_dates, "no sell between rungs"

    # Verify gain_ladder events
    gl_events = [
        e
        for e in result.events
        if e["event_type"] == "profit_drawdown"
        and e["details"].get("batch_protection") == "gain_ladder"
    ]
    assert len(gl_events) == 2


@pytest.mark.asyncio
async def test_bull_does_not_gain_ladder():
    """Bull regime: batch return hits +20% but gain-ladder must NOT fire."""
    config = _config(
        initial_position_pct=0.2,
        target_position_pct=0.2,
        profit_drawdown_trigger_pct=100.0,
        gain_ladder_thresholds=(20.0, 30.0),
        trailing_drawdown_pct=50.0,  # high threshold so trailing doesn't fire either
    )
    engine = BacktestEngine()
    regime_provider = FakeRegimeProvider(state="bull", tightness="loose")

    result = await engine.run(
        config=config,
        fund_nav=_navs([1.0, 1.20, 1.20]),
        signal_bars=_bars(
            closes=[10, 10.1, 10.2],
            volumes=[100, 100, 100],
        ),
        regime_provider=regime_provider,
    )

    sell_trades = [t for t in result.trades if t.action == "sell"]
    assert len(sell_trades) == 0, "bull must not gain-ladder or trailing (no drawdown)"

    gl_events = [
        e
        for e in result.events
        if e["details"].get("batch_protection") == "gain_ladder"
    ]
    assert len(gl_events) == 0


@pytest.mark.asyncio
async def test_bear_does_not_trailing():
    """Bear regime: batch drawdown hits threshold but trailing must NOT fire."""
    config = _config(
        initial_position_pct=0.2,
        target_position_pct=0.2,
        profit_drawdown_trigger_pct=100.0,
        trailing_drawdown_pct=10.0,
        gain_ladder_thresholds=(50.0, 60.0),  # high rungs so gain-ladder doesn't fire
    )
    engine = BacktestEngine()
    regime_provider = FakeRegimeProvider(state="bear", tightness="tight")

    result = await engine.run(
        config=config,
        fund_nav=_navs([1.0, 1.15, 1.05, 1.05]),
        signal_bars=_bars(
            closes=[10, 10.1, 10.2, 10.2],
            volumes=[100, 100, 100, 100],
        ),
        regime_provider=regime_provider,
    )

    sell_trades = [t for t in result.trades if t.action == "sell"]
    assert len(sell_trades) == 0, "bear must not trailing"

    trailing_events = [
        e
        for e in result.events
        if e["details"].get("batch_protection") == "trailing"
    ]
    assert len(trailing_events) == 0
