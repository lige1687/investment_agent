"""Test buy-side regime de-grading (Task 8)."""

import pytest
from datetime import date

from app.backtest.models import BacktestConfig, ProsperityConfig
from app.backtest.strategy import RuleBasedStrategyAgent
from app.backtest.events import BacktestEvent
from app.backtest.models import PortfolioSnapshot


def test_buy_strategy_bear_regime_downgrades():
    """Strategy._decide_buy downgrades allocation in bear regime."""
    config = BacktestConfig(
        fund_code="TEST001",
        fund_name="Test Fund",
        signal_code="000001.SZ",
        signal_name="Test Signal",
        initial_cash=100_000.0,
        target_position_pct=0.2,
    )

    strategy = RuleBasedStrategyAgent(config)

    # Create a buy_confirmation event with bear regime
    snapshot = PortfolioSnapshot(
        date=date(2024, 1, 1),
        cash=100_000.0,
        shares=0,
        nav=1.0,
        equity=100_000.0,
        position_pct=0.0,
        cumulative_return_pct=0.0,
        peak_return_pct=0.0,
    )

    event = BacktestEvent(
        event_type="buy_confirmation",
        date=date(2024, 1, 1),
        reason="Test buy confirmation",
        details={
            "original_buy_signal": {"signal_level": "strong_buy"},
            "market_regime": "bear",
        },
        snapshot=snapshot,
    )

    decision = strategy.decide(event)

    # In bear regime, target 20% becomes 6% (30% of 20%)
    expected_allocation = 0.2 * 0.3  # = 0.06 = 6%
    assert decision.target_position_delta_pct == expected_allocation, (
        f"Expected {expected_allocation}, got {decision.target_position_delta_pct}"
    )
    assert "降档" in decision.reason, f"Expected downgrade reason, got: {decision.reason}"


def test_buy_strategy_neutral_regime_downgrades():
    """Strategy._decide_buy downgrades allocation in neutral regime."""
    config = BacktestConfig(
        fund_code="TEST001",
        fund_name="Test Fund",
        signal_code="000001.SZ",
        signal_name="Test Signal",
        initial_cash=100_000.0,
        target_position_pct=0.2,
    )

    strategy = RuleBasedStrategyAgent(config)

    snapshot = PortfolioSnapshot(
        date=date(2024, 1, 1),
        cash=100_000.0,
        shares=0,
        nav=1.0,
        equity=100_000.0,
        position_pct=0.0,
        cumulative_return_pct=0.0,
        peak_return_pct=0.0,
    )

    event = BacktestEvent(
        event_type="buy_confirmation",
        date=date(2024, 1, 1),
        reason="Test buy confirmation",
        details={
            "original_buy_signal": {"signal_level": "strong_buy"},
            "market_regime": "neutral",
        },
        snapshot=snapshot,
    )

    decision = strategy.decide(event)

    # In neutral regime, also downgrade to 6%
    expected_allocation = 0.2 * 0.3
    assert decision.target_position_delta_pct == expected_allocation


def test_buy_strategy_bull_regime_full_allocation():
    """Strategy._decide_buy uses full allocation in bull regime."""
    config = BacktestConfig(
        fund_code="TEST001",
        fund_name="Test Fund",
        signal_code="000001.SZ",
        signal_name="Test Signal",
        initial_cash=100_000.0,
        target_position_pct=0.2,
    )

    strategy = RuleBasedStrategyAgent(config)

    snapshot = PortfolioSnapshot(
        date=date(2024, 1, 1),
        cash=100_000.0,
        shares=0,
        nav=1.0,
        equity=100_000.0,
        position_pct=0.0,
        cumulative_return_pct=0.0,
        peak_return_pct=0.0,
    )

    event = BacktestEvent(
        event_type="buy_confirmation",
        date=date(2024, 1, 1),
        reason="Test buy confirmation",
        details={
            "original_buy_signal": {"signal_level": "strong_buy"},
            "market_regime": "bull",
        },
        snapshot=snapshot,
    )

    decision = strategy.decide(event)

    # In bull regime with strong_buy, use full 20%
    expected_allocation = 0.2  # 100% of target
    assert decision.target_position_delta_pct == expected_allocation


def test_buy_strategy_prosperity_rejection():
    """Strategy._decide_buy rejects buy when prosperity < 50."""
    config = BacktestConfig(
        fund_code="TEST001",
        fund_name="Test Fund",
        signal_code="000001.SZ",
        signal_name="Test Signal",
        initial_cash=100_000.0,
        target_position_pct=0.2,
        prosperity=ProsperityConfig(score=40.0),  # < 50
    )

    strategy = RuleBasedStrategyAgent(config)

    snapshot = PortfolioSnapshot(
        date=date(2024, 1, 1),
        cash=100_000.0,
        shares=0,
        nav=1.0,
        equity=100_000.0,
        position_pct=0.0,
        cumulative_return_pct=0.0,
        peak_return_pct=0.0,
    )

    event = BacktestEvent(
        event_type="buy_confirmation",
        date=date(2024, 1, 1),
        reason="Test buy confirmation",
        details={
            "original_buy_signal": {"signal_level": "strong_buy"},
            "market_regime": "rejected",  # Engine sets this when prosperity < 50
        },
        snapshot=snapshot,
    )

    decision = strategy.decide(event)

    # Should reject
    assert decision.action == "hold", f"Expected hold, got {decision.action}"
    assert "经济景气度" in decision.reason
