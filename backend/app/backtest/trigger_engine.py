"""Deterministic AI-trigger signal engine for sparse strategy evaluation."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.backtest.indicators import moving_average, volume_ratio
from app.backtest.models import BacktestConfig, PortfolioSnapshot, SignalBar

TriggerPriority = Literal["P0", "P1", "P2", "P3", "P4"]
TriggerFamily = Literal[
    "account_risk",
    "stop_loss",
    "take_profit",
    "buy_observation",
    "add_position",
    "market_regime",
    "active_fund_strength",
]

PRIORITY_ORDER: dict[TriggerPriority, int] = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}


@dataclass(frozen=True)
class TriggerSignal:
    priority: TriggerPriority
    trigger_family: TriggerFamily
    trigger_type: str
    reason: str
    metrics: dict[str, Any] = field(default_factory=dict)
    should_call_ai: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TriggerEngine:
    """Finds mechanical events that deserve AI/strategy re-evaluation.

    Triggering is intentionally separate from trading. These rules only say
    "重新评估", not "买入/卖出".
    """

    def __init__(self, config: BacktestConfig):
        self.config = config

    def evaluate(
        self,
        index: int,
        bars: list[SignalBar],
        snapshot: PortfolioSnapshot,
    ) -> list[TriggerSignal]:
        if index < 0 or index >= len(bars):
            raise IndexError("index out of range")
        triggers: list[TriggerSignal] = []
        triggers.extend(self._account_risk_triggers(snapshot))
        triggers.extend(self._stop_loss_triggers(index, bars, snapshot))
        triggers.extend(self._take_profit_triggers(index, bars, snapshot))
        triggers.extend(self._add_position_triggers(index, bars, snapshot))
        triggers.extend(self._buy_observation_triggers(index, bars, snapshot))
        return sorted(triggers, key=lambda item: PRIORITY_ORDER[item.priority])

    def _account_risk_triggers(self, snapshot: PortfolioSnapshot) -> list[TriggerSignal]:
        triggers: list[TriggerSignal] = []
        account_drawdown = snapshot.peak_return_pct - snapshot.cumulative_return_pct
        cash_pct = 1 - snapshot.position_pct
        drawdown_steps = [
            (10.0, "账户回撤达到10%"),
            (7.0, "账户回撤达到7%~8%"),
            (5.0, "账户回撤达到5%"),
        ]
        for threshold, reason in drawdown_steps:
            if account_drawdown >= threshold:
                triggers.append(self._signal(
                    "P0",
                    "account_risk",
                    f"account_drawdown_{int(threshold)}",
                    reason,
                    {
                        "account_drawdown_pct": round(account_drawdown, 4),
                        "threshold_pct": threshold,
                        "current_return_pct": snapshot.cumulative_return_pct,
                        "peak_return_pct": snapshot.peak_return_pct,
                    },
                ))
                break
        if cash_pct < self.config.min_cash_pct:
            triggers.append(self._signal(
                "P0",
                "account_risk",
                "cash_below_required",
                "现金比例低于系统要求",
                {"cash_pct": round(cash_pct * 100, 4), "min_cash_pct": self.config.min_cash_pct * 100},
            ))
        if snapshot.position_pct > self.config.max_account_position_pct:
            triggers.append(self._signal(
                "P0",
                "account_risk",
                "total_position_above_limit",
                "总仓位超过系统上限",
                {
                    "position_pct": round(snapshot.position_pct * 100, 4),
                    "max_account_position_pct": self.config.max_account_position_pct * 100,
                },
            ))
        if self.config.current_correlated_growth_exposure_pct > self.config.max_correlated_growth_exposure_pct:
            triggers.append(self._signal(
                "P0",
                "account_risk",
                "correlated_growth_exposure_high",
                "单赛道暴露过高",
                {
                    "current_correlated_growth_exposure_pct": self.config.current_correlated_growth_exposure_pct * 100,
                    "max_correlated_growth_exposure_pct": self.config.max_correlated_growth_exposure_pct * 100,
                },
            ))
        return triggers

    def _buy_observation_triggers(
        self,
        index: int,
        bars: list[SignalBar],
        snapshot: PortfolioSnapshot,
    ) -> list[TriggerSignal]:
        triggers: list[TriggerSignal] = []
        closes = [bar.close for bar in bars[: index + 1]]
        lows = [bar.low for bar in bars[: index + 1]]
        volumes = [bar.volume for bar in bars[: index + 1]]
        current = bars[index]
        previous_close = closes[index - 1] if index > 0 else closes[index]
        for window in (20, 30, 60):
            ma_values = moving_average(closes, window)
            ma = ma_values[index]
            previous_ma = ma_values[index - 1] if index > 0 else None
            if ma is None:
                continue
            if self._pullback_holds(current, ma):
                triggers.append(self._signal(
                    "P3",
                    "buy_observation",
                    f"pullback_ma{window}_holds",
                    f"回踩{window}日均线不破",
                    {"close": current.close, "low": current.low, f"ma{window}": ma},
                ))
            if previous_ma is not None and previous_close < previous_ma <= current.close:
                triggers.append(self._signal(
                    "P3",
                    "buy_observation",
                    f"reclaim_ma{window}",
                    f"重新站回{window}日均线",
                    {"previous_close": previous_close, "close": current.close, f"ma{window}": ma},
                ))
        if self._three_days_not_new_low(index, lows):
            triggers.append(self._signal(
                "P3",
                "buy_observation",
                "three_days_not_new_low",
                "连续3天不创新低",
                {"recent_lows": lows[max(0, index - 2): index + 1]},
            ))
        volume_ratios = volume_ratio(volumes, min(self.config.buy_volume_window, max(1, index)))
        current_volume_ratio = volume_ratios[index]
        if self._volume_contracts(index, bars):
            triggers.append(self._signal(
                "P3",
                "buy_observation",
                "volume_contracts_stabilizing",
                "缩量企稳",
                {"recent_volumes": volumes[max(0, index - 2): index + 1]},
            ))
        if current_volume_ratio is not None and current_volume_ratio >= self.config.buy_volume_ratio:
            prior_high = max(closes[max(0, index - 10): index], default=current.close)
            if current.close > prior_high:
                triggers.append(self._signal(
                    "P3",
                    "buy_observation",
                    "volume_breakout",
                    "放量突破",
                    {"close": current.close, "prior_high": prior_high, "volume_ratio": current_volume_ratio},
                ))
        if self._range_breakout_after_consolidation(index, bars):
            triggers.append(self._signal(
                "P3",
                "buy_observation",
                "range_breakout_after_consolidation",
                "横盘后向上突破",
                {"close": current.close},
            ))
        return self._dedupe(triggers)

    def _add_position_triggers(
        self,
        index: int,
        bars: list[SignalBar],
        snapshot: PortfolioSnapshot,
    ) -> list[TriggerSignal]:
        if snapshot.position_pct <= 0:
            return []
        drawdown_from_peak = snapshot.peak_return_pct - snapshot.cumulative_return_pct
        if drawdown_from_peak < 5:
            return []
        triggers = [self._signal(
            "P3",
            "add_position",
            "drawdown_to_add_zone",
            "从阶段高点回撤到预设区间",
            {
                "drawdown_from_peak_pct": round(drawdown_from_peak, 4),
                "peak_return_pct": snapshot.peak_return_pct,
                "current_return_pct": snapshot.cumulative_return_pct,
            },
        )]
        closes = [bar.close for bar in bars[: index + 1]]
        ma20 = moving_average(closes, 20)[index]
        if ma20 is not None and self._pullback_holds(bars[index], ma20):
            triggers.append(self._signal(
                "P3",
                "add_position",
                "pullback_support_holds",
                "回踩均线不破",
                {"close": bars[index].close, "low": bars[index].low, "ma20": ma20},
            ))
        return triggers

    def _take_profit_triggers(
        self,
        index: int,
        bars: list[SignalBar],
        snapshot: PortfolioSnapshot,
    ) -> list[TriggerSignal]:
        if snapshot.position_pct <= 0:
            return []
        triggers: list[TriggerSignal] = []
        monitor_pct = 10.0 if self.config.fund_category == "high_elastic" else 8.0
        if snapshot.cumulative_return_pct >= monitor_pct:
            triggers.append(self._signal(
                "P2",
                "take_profit",
                "profit_monitor_reached",
                "高波动基金盈利10%~15%",
                {"current_return_pct": snapshot.cumulative_return_pct, "monitor_pct": monitor_pct},
            ))
        drawdown_from_peak = snapshot.peak_return_pct - snapshot.cumulative_return_pct
        if drawdown_from_peak >= 3 and snapshot.peak_return_pct > 0:
            triggers.append(self._signal(
                "P2",
                "take_profit",
                "floating_profit_drawdown",
                "单批次最高浮盈开始回撤",
                {"drawdown_from_peak_pct": round(drawdown_from_peak, 4)},
            ))
        if self._high_volume_stalling(index, bars):
            triggers.append(self._signal(
                "P2",
                "take_profit",
                "high_volume_stalling",
                "高位出现放量滞涨",
                self._bar_metrics(index, bars),
            ))
        if self._intraday_reversal(index, bars):
            triggers.append(self._signal(
                "P2",
                "take_profit",
                "intraday_reversal",
                "冲高回落",
                self._bar_metrics(index, bars),
            ))
        return triggers

    def _stop_loss_triggers(
        self,
        index: int,
        bars: list[SignalBar],
        snapshot: PortfolioSnapshot,
    ) -> list[TriggerSignal]:
        if snapshot.position_pct <= 0:
            return []
        triggers: list[TriggerSignal] = []
        if snapshot.cumulative_return_pct <= -5:
            triggers.append(self._signal(
                "P1",
                "stop_loss",
                "trial_position_loss_zone",
                "试错仓亏5%~8%",
                {"current_return_pct": snapshot.cumulative_return_pct},
            ))
        closes = [bar.close for bar in bars[: index + 1]]
        for window in (20, 60):
            ma_values = moving_average(closes, window)
            ma = ma_values[index]
            if ma is not None and bars[index].close < ma:
                triggers.append(self._signal(
                    "P1",
                    "stop_loss",
                    f"break_ma{window}",
                    f"跌破{window}日均线",
                    {"close": bars[index].close, f"ma{window}": ma},
                ))
        volume_ratios = volume_ratio([bar.volume for bar in bars[: index + 1]], min(self.config.buy_volume_window, max(1, index)))
        current_volume_ratio = volume_ratios[index]
        recent_low = min((bar.low for bar in bars[max(0, index - 10): index]), default=bars[index].low)
        if bars[index].close < recent_low and current_volume_ratio is not None and current_volume_ratio >= self.config.breakdown_volume_ratio:
            triggers.append(self._signal(
                "P1",
                "stop_loss",
                "break_support_high_volume",
                "跌破关键位并放量下跌",
                {"close": bars[index].close, "recent_low": recent_low, "volume_ratio": current_volume_ratio},
            ))
        return triggers

    def _signal(
        self,
        priority: TriggerPriority,
        trigger_family: TriggerFamily,
        trigger_type: str,
        reason: str,
        metrics: dict[str, Any],
        should_call_ai: bool = True,
    ) -> TriggerSignal:
        return TriggerSignal(
            priority=priority,
            trigger_family=trigger_family,
            trigger_type=trigger_type,
            reason=reason,
            metrics=metrics,
            should_call_ai=should_call_ai,
        )

    def _pullback_holds(self, bar: SignalBar, support: float) -> bool:
        tolerance = support * 0.01
        return bar.low <= support + tolerance and bar.close >= support

    def _three_days_not_new_low(self, index: int, lows: list[float]) -> bool:
        if index < 5:
            return False
        recent = lows[index - 2: index + 1]
        prior = lows[index - 5: index - 2]
        return bool(recent and prior) and min(recent) >= min(prior)

    def _volume_contracts(self, index: int, bars: list[SignalBar]) -> bool:
        if index < 5:
            return False
        recent = bars[index - 2: index + 1]
        prior_volumes = [bar.volume for bar in bars[index - 5: index - 2]]
        if not prior_volumes:
            return False
        avg_prior = sum(prior_volumes) / len(prior_volumes)
        avg_recent = sum(bar.volume for bar in recent) / len(recent)
        price_range = max(bar.high for bar in recent) - min(bar.low for bar in recent)
        avg_price = sum(bar.close for bar in recent) / len(recent)
        return avg_recent < avg_prior * 0.85 and price_range / avg_price < 0.06

    def _range_breakout_after_consolidation(self, index: int, bars: list[SignalBar]) -> bool:
        if index < 8:
            return False
        range_bars = bars[index - 6: index]
        upper = max(bar.high for bar in range_bars)
        lower = min(bar.low for bar in range_bars)
        avg_close = sum(bar.close for bar in range_bars) / len(range_bars)
        consolidated = (upper - lower) / avg_close <= 0.06
        return consolidated and bars[index].close > upper

    def _high_volume_stalling(self, index: int, bars: list[SignalBar]) -> bool:
        if index < 2:
            return False
        ratios = volume_ratio([bar.volume for bar in bars[: index + 1]], min(self.config.buy_volume_window, max(1, index)))
        ratio = ratios[index]
        if ratio is None or ratio < 1.5:
            return False
        current = bars[index]
        body_pct = abs(current.close - current.open) / current.open if current.open else 0
        upper_shadow = current.high - max(current.open, current.close)
        return body_pct < 0.01 or upper_shadow > abs(current.close - current.open) * 1.5

    def _intraday_reversal(self, index: int, bars: list[SignalBar]) -> bool:
        current = bars[index]
        if current.high <= current.open:
            return False
        intraday_gain = current.high / current.open - 1
        close_giveback = (current.high - current.close) / (current.high - current.open)
        return intraday_gain >= 0.03 and close_giveback >= 0.5

    def _bar_metrics(self, index: int, bars: list[SignalBar]) -> dict[str, Any]:
        current = bars[index]
        return {
            "open": current.open,
            "high": current.high,
            "low": current.low,
            "close": current.close,
            "volume": current.volume,
        }

    def _dedupe(self, triggers: list[TriggerSignal]) -> list[TriggerSignal]:
        seen: set[tuple[str, str]] = set()
        result: list[TriggerSignal] = []
        for trigger in triggers:
            key = (trigger.trigger_family, trigger.trigger_type)
            if key in seen:
                continue
            seen.add(key)
            result.append(trigger)
        return result
