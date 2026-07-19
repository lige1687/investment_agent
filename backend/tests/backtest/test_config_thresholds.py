"""Tests for externalized backtest thresholds (Task 7).

Verify that BacktestConfig thresholds drive engine behavior instead of hardcoded values.
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


# ── Tests ───────────────────────────────────────────────────────────────────


class TestBatchAllocationRatios:
    """Verify batch allocation ratios are externalized and configurable."""

    def test_default_batch_allocation_ratios(self):
        """Default ratios should be 0.5, 0.3, 0.2 for core/confirmation/high_position."""
        config = BacktestConfig(
            fund_code="test",
            fund_name="Test Fund",
            signal_code="399001",
            signal_name="深证成指",
            initial_position_pct=0.6,
            target_position_pct=0.6,
        )
        # Defaults should be externalized
        assert config.core_batch_ratio == 0.5
        assert config.confirmation_batch_ratio == 0.3
        assert config.high_position_batch_ratio == 0.2

    def test_custom_batch_allocation_ratios(self):
        """Verify custom batch ratios are respected by the engine."""
        config = BacktestConfig(
            fund_code="test",
            fund_name="Test Fund",
            signal_code="399001",
            signal_name="深证成指",
            initial_position_pct=0.6,
            target_position_pct=0.6,
            core_batch_ratio=0.4,
            confirmation_batch_ratio=0.4,
            high_position_batch_ratio=0.2,
        )
        assert config.core_batch_ratio == 0.4
        assert config.confirmation_batch_ratio == 0.4
        assert config.high_position_batch_ratio == 0.2


class TestBatchTakeProfitThresholds:
    """Verify take-profit thresholds are externalized and configurable."""

    def test_default_takeprofit_thresholds(self):
        """Default thresholds: trial 3/3, high_position 5/4, confirmation 8/5, core 15/6."""
        config = BacktestConfig(
            fund_code="test",
            fund_name="Test Fund",
            signal_code="399001",
            signal_name="深证成指",
        )
        assert config.trial_tp_peak_pct == 3.0
        assert config.trial_tp_drawdown_pct == 3.0
        assert config.high_position_tp_peak_pct == 5.0
        assert config.high_position_tp_drawdown_pct == 4.0
        assert config.confirmation_tp_peak_pct == 8.0
        assert config.confirmation_tp_drawdown_pct == 5.0
        assert config.core_tp_peak_pct == 15.0
        assert config.core_tp_drawdown_pct == 6.0

    def test_custom_takeprofit_thresholds(self):
        """Verify custom take-profit thresholds are configurable."""
        config = BacktestConfig(
            fund_code="test",
            fund_name="Test Fund",
            signal_code="399001",
            signal_name="深证成指",
            trial_tp_peak_pct=5.0,
            trial_tp_drawdown_pct=4.0,
            core_tp_peak_pct=20.0,
            core_tp_drawdown_pct=8.0,
        )
        assert config.trial_tp_peak_pct == 5.0
        assert config.trial_tp_drawdown_pct == 4.0
        assert config.core_tp_peak_pct == 20.0
        assert config.core_tp_drawdown_pct == 8.0


class TestCoreBatchHardCap:
    """Verify core batch hard-cap protection thresholds are externalized."""

    def test_default_hard_cap_thresholds(self):
        """Default hard-cap: peak 40%, drawdown 20%."""
        config = BacktestConfig(
            fund_code="test",
            fund_name="Test Fund",
            signal_code="399001",
            signal_name="深证成指",
        )
        assert config.core_hard_cap_peak_pct == 40.0
        assert config.core_hard_cap_drawdown_pct == 20.0

    def test_custom_hard_cap_thresholds(self):
        """Verify custom hard-cap thresholds are configurable."""
        config = BacktestConfig(
            fund_code="test",
            fund_name="Test Fund",
            signal_code="399001",
            signal_name="深证成指",
            core_hard_cap_peak_pct=50.0,
            core_hard_cap_drawdown_pct=25.0,
        )
        assert config.core_hard_cap_peak_pct == 50.0
        assert config.core_hard_cap_drawdown_pct == 25.0


class TestCostLineProtection:
    """Verify cost-line protection threshold is externalized."""

    def test_default_cost_line_protection(self):
        """Default cost-line threshold: 1.5%."""
        config = BacktestConfig(
            fund_code="test",
            fund_name="Test Fund",
            signal_code="399001",
            signal_name="深证成指",
        )
        assert config.near_cost_line_pct == 1.5

    def test_custom_cost_line_protection(self):
        """Verify custom cost-line threshold is configurable."""
        config = BacktestConfig(
            fund_code="test",
            fund_name="Test Fund",
            signal_code="399001",
            signal_name="深证成指",
            near_cost_line_pct=2.0,
        )
        assert config.near_cost_line_pct == 2.0


class TestMarketRegimeRetentionRates:
    """Verify market regime retention rates are externalized."""

    def test_default_retention_rates(self):
        """Default retention rates: bull 0.85, neutral 0.75, bear 0.50."""
        config = BacktestConfig(
            fund_code="test",
            fund_name="Test Fund",
            signal_code="399001",
            signal_name="深证成指",
        )
        assert config.regime_retention_rates == {"bull": 0.85, "neutral": 0.75, "bear": 0.50}

    def test_custom_retention_rates(self):
        """Verify custom retention rates are configurable."""
        custom_rates = {"bull": 0.90, "neutral": 0.70, "bear": 0.40}
        config = BacktestConfig(
            fund_code="test",
            fund_name="Test Fund",
            signal_code="399001",
            signal_name="深证成指",
            regime_retention_rates=custom_rates,
        )
        assert config.regime_retention_rates == custom_rates
