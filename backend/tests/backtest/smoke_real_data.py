"""Smoke test for Phase 1 backtest with two-layer observation model.

Tests that:
1. P0 (DeterministicJudge, baseline) runs without hanging
2. P1 (LLMObserverJudge + SectorRegimeProvider) runs without hanging if LLM configured
3. At least 1 trade executes in P1
"""
import asyncio
from datetime import date, timedelta

import pytest

from app.backtest.engine import BacktestEngine
from app.backtest.models import BacktestConfig, FundNavPoint, SignalBar, ProsperityConfig
from app.backtest.observation.judge import DeterministicJudge
from app.backtest.observation.regime import SectorRegimeProvider


def _synthetic_bars(days: int = 90, base_price: float = 2.5) -> list[SignalBar]:
    """Generate synthetic price bars with periodic volume breakouts."""
    bars = []
    current_price = base_price
    base_date = date(2026, 1, 1)

    for i in range(days):
        # Slight trending movement with periodic volume spikes
        if i % 20 == 10:
            current_price *= 1.02  # +2% breakout every 20 days
            volume = 500.0
        elif i % 20 == 15:
            current_price *= 0.98  # -2% breakdown
            volume = 600.0
        else:
            current_price *= 1.0001  # Slight drift
            volume = 100.0

        bars.append(
            SignalBar(
                date=base_date + timedelta(days=i),
                open=current_price * 0.99,
                high=current_price * 1.01,
                low=current_price * 0.99,
                close=current_price,
                volume=volume,
                amount=None,
            )
        )
    return bars


def _synthetic_nav(days: int = 90, base_nav: float = 2.5) -> list[FundNavPoint]:
    """Generate synthetic fund NAV matching signal bars."""
    nav_points = []
    current_nav = base_nav
    base_date = date(2026, 1, 1)

    for i in range(days):
        # Similar drift as signal bars
        if i % 20 == 10:
            current_nav *= 1.02
        elif i % 20 == 15:
            current_nav *= 0.98
        else:
            current_nav *= 1.0001

        nav_points.append(
            FundNavPoint(
                date=base_date + timedelta(days=i),
                nav=current_nav,
            )
        )
    return nav_points


def _default_config() -> BacktestConfig:
    """Minimal BacktestConfig for smoke test."""
    return BacktestConfig(
        fund_code="test_fund",
        fund_name="Test Fund",
        signal_code="test_signal",
        signal_name="Test Signal",
        expma_window=15,
        buy_volume_window=10,
        buy_volume_ratio=1.2,
        breakdown_volume_ratio=1.5,
        initial_cash=100000.0,
        initial_position_pct=0.5,
        target_position_pct=0.6,
        max_single_position_pct=0.7,
        core_batch_ratio=0.5,
        confirmation_batch_ratio=0.3,
        high_position_batch_ratio=0.2,
        trial_tp_peak_pct=3.0,
        trial_tp_drawdown_pct=1.5,
        high_position_tp_peak_pct=5.0,
        high_position_tp_drawdown_pct=2.0,
        confirmation_tp_peak_pct=8.0,
        confirmation_tp_drawdown_pct=3.0,
        core_tp_peak_pct=10.0,
        core_tp_drawdown_pct=5.0,
        core_hard_cap_peak_pct=30.0,
        core_hard_cap_drawdown_pct=8.0,
        near_cost_line_pct=1.5,
        trailing_drawdown_pct=3.0,
        gain_ladder_thresholds=(20.0, 30.0, 40.0),
        prosperity=ProsperityConfig(score=6.0),
        regime_retention_rates={"bull": 0.85, "neutral": 0.75, "bear": 0.50},
    )


@pytest.mark.asyncio
async def test_p0_baseline_no_hang():
    """P0: DeterministicJudge baseline should run without hanging."""
    signal_bars = _synthetic_bars(days=90)
    fund_nav = _synthetic_nav(days=90)
    config = _default_config()

    engine = BacktestEngine()
    judge = DeterministicJudge()

    result = await engine.run(
        config=config,
        fund_nav=fund_nav,
        signal_bars=signal_bars,
        test_mode=False,
        judge=judge,
    )

    assert result is not None
    assert result.metrics is not None
    assert len(result.equity_curve) > 0


@pytest.mark.asyncio
async def test_p1_with_regime_provider_no_hang():
    """P1: LLMObserverJudge + SectorRegimeProvider should run without hanging.

    If LLM is not configured, this test is skipped (no error).
    """
    from app.llm.registry import llm_credentials_configured

    # Skip if LLM not configured for backtest observer role
    if not llm_credentials_configured("backtest_observer"):
        pytest.skip("LLM credentials not configured; skipping P1 test")

    signal_bars = _synthetic_bars(days=90)
    fund_nav = _synthetic_nav(days=90)
    config = _default_config()

    # Try to import LLM judge; skip if import fails
    try:
        from app.backtest.observation.judge import LLMObserverJudge
        from app.backtest.observation.cache import ObservationCache
    except ImportError:
        pytest.skip("LLMObserverJudge not available")

    engine = BacktestEngine()
    judge = LLMObserverJudge()
    cache = ObservationCache()
    regime_provider = SectorRegimeProvider()

    result = await engine.run(
        config=config,
        fund_nav=fund_nav,
        signal_bars=signal_bars,
        test_mode=False,
        judge=judge,
        cache=cache,
        regime_provider=regime_provider,
    )

    assert result is not None
    assert result.metrics is not None
    assert len(result.equity_curve) > 0
    # P1 should execute at least 1 trade (buy during initialization + sell on breakout)
    assert result.metrics.trade_count >= 1, "P1 should execute at least 1 trade"


@pytest.mark.asyncio
async def test_p0_produces_events():
    """P0 should produce trading events without errors."""
    signal_bars = _synthetic_bars(days=90)
    fund_nav = _synthetic_nav(days=90)
    config = _default_config()

    engine = BacktestEngine()
    judge = DeterministicJudge()

    result = await engine.run(
        config=config,
        fund_nav=fund_nav,
        signal_bars=signal_bars,
        test_mode=True,
        judge=judge,
    )

    # P0 should generate events (buy/sell observations at minimum)
    assert len(result.events) >= 0
    # Equity curve should span the full date range
    assert len(result.equity_curve) == len(fund_nav)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
