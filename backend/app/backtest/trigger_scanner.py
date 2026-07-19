"""L1 mechanical trigger scanner for the two-layer observation model.

Scans OHLCV bars for volume-confirmed EXPMA crossovers:
- buy trigger: previous close <= EXPMA, current close > EXPMA, volume_ratio >= buy_volume_ratio
- sell trigger: previous close >= EXPMA, current close < EXPMA, volume_ratio >= breakdown_volume_ratio

This is a pure deterministic module -- no LLM, no side effects.
Phase 1 allows volume thresholds to be provided by VolumeThresholdProvider; the
crossover logic stays the same.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from app.backtest.indicators import expma, volume_ratio
from app.backtest.models import BacktestConfig, SignalBar

TriggerKind = Literal["buy", "sell"]


@dataclass(frozen=True)
class TriggerPoint:
    """A single L1 mechanical trigger detected by TriggerScanner."""

    kind: TriggerKind
    index: int
    date: date


class TriggerScanner:
    """Scans bars for volume-confirmed EXPMA crossover triggers (L1).

    Optionally uses VolumeThresholdProvider for dynamic volume thresholds.
    If no provider given, uses config defaults.
    """

    def __init__(
        self,
        config: BacktestConfig,
        volume_provider: Any | None = None,
    ):
        """
        Parameters
        ----------
        config : BacktestConfig
            Backtest configuration with default volume ratios.
        volume_provider : optional
            VolumeThresholdProvider instance for dynamic volume thresholds.
            If None, uses config.buy_volume_ratio and config.breakdown_volume_ratio.
        """
        self.config = config
        self.volume_provider = volume_provider

    async def scan_async(
        self,
        bars: list[SignalBar],
        symbol: str = "",
        config: BacktestConfig | None = None,
    ) -> list[TriggerPoint]:
        """Async scan with volume provider support.

        For use when VolumeThresholdProvider is available. Computes thresholds
        once at the start, then scans deterministically.
        """
        config = config or self.config

        # Determine volume thresholds (once per scan)
        if self.volume_provider is not None and bars:
            try:
                buy_threshold = await self.volume_provider.get_threshold(
                    symbol, "buy", bars[0].date, config
                )
                sell_threshold = await self.volume_provider.get_threshold(
                    symbol, "sell", bars[0].date, config
                )
            except Exception as exc:
                import logging

                logger = logging.getLogger(__name__)
                logger.warning("Failed to get volume thresholds, using config defaults: %s", exc)
                buy_threshold = config.buy_volume_ratio
                sell_threshold = config.breakdown_volume_ratio
        else:
            buy_threshold = config.buy_volume_ratio
            sell_threshold = config.breakdown_volume_ratio

        return self._scan_deterministic(bars, buy_threshold, sell_threshold)

    def scan(self, bars: list[SignalBar]) -> list[TriggerPoint]:
        """Synchronous scan with config defaults (backward compat)."""
        return self._scan_deterministic(
            bars,
            self.config.buy_volume_ratio,
            self.config.breakdown_volume_ratio,
        )

    def _scan_deterministic(
        self,
        bars: list[SignalBar],
        buy_threshold: float,
        sell_threshold: float,
    ) -> list[TriggerPoint]:
        """Deterministic scan given fixed thresholds."""
        if len(bars) < 2:
            return []

        closes = [bar.close for bar in bars]
        volumes = [bar.volume for bar in bars]

        expma_values = expma(closes, self.config.expma_window)
        volume_ratios = volume_ratio(volumes, self.config.buy_volume_window)

        triggers: list[TriggerPoint] = []
        for i in range(1, len(bars)):
            vr = volume_ratios[i]
            if vr is None:
                continue

            prev_close = closes[i - 1]
            curr_close = closes[i]
            prev_expma = expma_values[i - 1]
            curr_expma = expma_values[i]

            # buy: cross above EXPMA with volume
            if (
                prev_close <= prev_expma
                and curr_close > curr_expma
                and vr >= buy_threshold
            ):
                triggers.append(TriggerPoint(kind="buy", index=i, date=bars[i].date))

            # sell: cross below EXPMA with volume
            if (
                prev_close >= prev_expma
                and curr_close < curr_expma
                and vr >= sell_threshold
            ):
                triggers.append(TriggerPoint(kind="sell", index=i, date=bars[i].date))

        return triggers
