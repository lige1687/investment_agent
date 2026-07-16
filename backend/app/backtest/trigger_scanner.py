"""L1 mechanical trigger scanner for the two-layer observation model.

Scans OHLCV bars for volume-confirmed EXPMA crossovers:
- buy trigger: previous close <= EXPMA, current close > EXPMA, volume_ratio >= buy_volume_ratio
- sell trigger: previous close >= EXPMA, current close < EXPMA, volume_ratio >= breakdown_volume_ratio

This is a pure deterministic module -- no LLM, no side effects.
Phase 1 will swap the volume thresholds for a skill-provided provider; the
crossover logic stays the same.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

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
    """Scans bars for volume-confirmed EXPMA crossover triggers (L1)."""

    def __init__(self, config: BacktestConfig):
        self.config = config

    def scan(self, bars: list[SignalBar]) -> list[TriggerPoint]:
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
                and vr >= self.config.buy_volume_ratio
            ):
                triggers.append(TriggerPoint(kind="buy", index=i, date=bars[i].date))

            # sell: cross below EXPMA with volume
            if (
                prev_close >= prev_expma
                and curr_close < curr_expma
                and vr >= self.config.breakdown_volume_ratio
            ):
                triggers.append(TriggerPoint(kind="sell", index=i, date=bars[i].date))

        return triggers
