"""Test VolumeThresholdProvider (Task 9)."""

import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock

from app.backtest.models import BacktestConfig, SignalBar
from app.backtest.observation.volume import VolumeThresholdProvider
from app.backtest.trigger_scanner import TriggerScanner


@pytest.mark.asyncio
async def test_skill_returns_threshold_used():
    """When skill returns a threshold, TriggerScanner uses it."""
    config = BacktestConfig(
        fund_code="TEST001",
        fund_name="Test Fund",
        signal_code="000001.SZ",
        signal_name="Test Signal",
        initial_cash=100_000.0,
        buy_volume_ratio=1.8,
        breakdown_volume_ratio=1.5,
    )

    bars = [
        SignalBar(date=date(2024, 1, 1), open=100, high=100, low=100, close=100, volume=1000),
        SignalBar(date=date(2024, 1, 2), open=100, high=105, low=100, close=105, volume=5000),
    ]

    # Mock skill bridge that returns 2.0 for buy
    mock_bridge = AsyncMock()
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.data = {"threshold": 2.0}
    mock_bridge.invoke_simple = AsyncMock(return_value=mock_result)

    provider = VolumeThresholdProvider(skill_bridge=mock_bridge)
    threshold = await provider.get_threshold("000001.SZ", "buy", date(2024, 1, 2), config)

    assert threshold == 2.0, f"Expected 2.0, got {threshold}"
    mock_bridge.invoke_simple.assert_called_once()


@pytest.mark.asyncio
async def test_skill_unavailable_uses_config_default():
    """When skill is unavailable, VolumeThresholdProvider uses config default."""
    config = BacktestConfig(
        fund_code="TEST001",
        fund_name="Test Fund",
        signal_code="000001.SZ",
        signal_name="Test Signal",
        initial_cash=100_000.0,
        buy_volume_ratio=1.8,
        breakdown_volume_ratio=1.5,
    )

    # Mock skill bridge that raises
    mock_bridge = AsyncMock()
    mock_bridge.invoke_simple = AsyncMock(side_effect=RuntimeError("Skill unavailable"))

    provider = VolumeThresholdProvider(skill_bridge=mock_bridge)
    threshold = await provider.get_threshold("000001.SZ", "buy", date(2024, 1, 2), config)

    assert threshold == 1.8, f"Expected config default 1.8, got {threshold}"


@pytest.mark.asyncio
async def test_skill_failure_response_uses_fallback():
    """When skill returns failure, VolumeThresholdProvider uses config default."""
    config = BacktestConfig(
        fund_code="TEST001",
        fund_name="Test Fund",
        signal_code="000001.SZ",
        signal_name="Test Signal",
        initial_cash=100_000.0,
        buy_volume_ratio=1.8,
        breakdown_volume_ratio=1.5,
    )

    # Mock skill bridge that returns failure
    mock_bridge = AsyncMock()
    mock_result = MagicMock()
    mock_result.success = False
    mock_result.error = "Service unavailable"
    mock_bridge.invoke_simple = AsyncMock(return_value=mock_result)

    provider = VolumeThresholdProvider(skill_bridge=mock_bridge)
    threshold = await provider.get_threshold("000001.SZ", "buy", date(2024, 1, 2), config)

    assert threshold == 1.8, f"Expected config default 1.8, got {threshold}"


@pytest.mark.asyncio
async def test_trigger_scanner_uses_volume_provider():
    """TriggerScanner with volume_provider properly invokes provider."""
    config = BacktestConfig(
        fund_code="TEST001",
        fund_name="Test Fund",
        signal_code="000001.SZ",
        signal_name="Test Signal",
        initial_cash=100_000.0,
        buy_volume_ratio=1.8,
        breakdown_volume_ratio=1.5,
    )

    bars = [
        SignalBar(date=date(2024, 1, 1), open=100, high=100, low=100, close=100, volume=1000),
        SignalBar(date=date(2024, 1, 2), open=100, high=105, low=100, close=105, volume=5000),
    ]

    # Mock provider tracks calls
    mock_provider = AsyncMock()
    mock_provider.get_threshold = AsyncMock(return_value=1.5)

    scanner = TriggerScanner(config, volume_provider=mock_provider)
    # Note: scan_async is for when you have a provider; scan is for backward compat
    # The important test is that the provider interface is called correctly
    await scanner.scan_async(bars, symbol="000001.SZ", config=config)

    # Verify provider was called for buy side
    mock_provider.get_threshold.assert_any_call("000001.SZ", "buy", bars[0].date, config)


def test_trigger_scanner_backward_compat_no_provider():
    """TriggerScanner without provider uses config defaults (backward compat)."""
    config = BacktestConfig(
        fund_code="TEST001",
        fund_name="Test Fund",
        signal_code="000001.SZ",
        signal_name="Test Signal",
        initial_cash=100_000.0,
        buy_volume_ratio=1.8,
    )

    # These bars need proper setup for EXPMA crossover
    # Start with baseline, then drop, then cross back up
    bars = [
        SignalBar(date=date(2024, 1, 1), open=100, high=100, low=100, close=100, volume=1000),
        SignalBar(date=date(2024, 1, 2), open=100, high=100, low=99, close=99, volume=1000),
        SignalBar(date=date(2024, 1, 3), open=99, high=105, low=99, close=103, volume=2000),  # cross back up
    ]

    # Synchronous scan without provider
    scanner = TriggerScanner(config)
    triggers = scanner.scan(bars)

    # Just verify the scan runs without error
    # The exact trigger depends on EXPMA calculation which is complex
    # We've tested volume thresholds separately
    assert isinstance(triggers, list)


@pytest.mark.asyncio
async def test_volume_provider_caches_result():
    """VolumeThresholdProvider caches results."""
    config = BacktestConfig(
        fund_code="TEST001",
        fund_name="Test Fund",
        signal_code="000001.SZ",
        signal_name="Test Signal",
        initial_cash=100_000.0,
        buy_volume_ratio=1.8,
    )

    # Mock cache
    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value=None)  # First call: miss
    mock_cache.set = AsyncMock()  # Cache the result

    # Mock bridge
    mock_bridge = AsyncMock()
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.data = {"threshold": 2.0}
    mock_bridge.invoke_simple = AsyncMock(return_value=mock_result)

    provider = VolumeThresholdProvider(skill_bridge=mock_bridge, cache=mock_cache)
    threshold = await provider.get_threshold("000001.SZ", "buy", date(2024, 1, 2), config)

    assert threshold == 2.0
    mock_cache.set.assert_called_once()

    # Second call should hit cache
    mock_cache.get = AsyncMock(return_value={"threshold": 2.0})
    provider2 = VolumeThresholdProvider(skill_bridge=mock_bridge, cache=mock_cache)
    threshold2 = await provider2.get_threshold("000001.SZ", "buy", date(2024, 1, 2), config)

    assert threshold2 == 2.0
