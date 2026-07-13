"""Event detection for event-triggered strategy decisions."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from app.backtest.indicators import expma, moving_average, volume_ratio
from app.backtest.models import BacktestConfig, PortfolioSnapshot, SignalBar
from app.backtest.policy import TradingSystemPolicy
from app.backtest.trigger_engine import TriggerEngine, TriggerSignal

EventType = Literal[
    "account_risk",
    "system_check",
    "buy_candidate",
    "risk_block",
    "profit_drawdown",
    "technical_breakdown",
    "post_sell_observation",
    "stop_loss",
]


@dataclass(frozen=True)
class BacktestEvent:
    event_type: EventType
    date: date
    reason: str
    details: dict[str, Any] = field(default_factory=dict)
    snapshot: PortfolioSnapshot | None = None


class EventDetector:
    """Detects sparse strategy events from daily replay context."""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.policy = TradingSystemPolicy(config)
        self.trigger_engine = TriggerEngine(config)
        self._emitted_account_trigger_types: set[str] = set()

    def detect(
        self,
        index: int,
        bars: list[SignalBar],
        snapshot: PortfolioSnapshot,
    ) -> list[BacktestEvent]:
        if index < 0 or index >= len(bars):
            raise IndexError("index out of range")

        events: list[BacktestEvent] = []
        triggers = self.trigger_engine.evaluate(index=index, bars=bars, snapshot=snapshot)

        account_event = self._detect_account_risk(bars[index], snapshot, triggers)
        if account_event:
            events.append(account_event)

        buy_event = self._detect_buy_candidate(index, bars, snapshot, triggers)
        if buy_event:
            events.append(buy_event)

        profit_event = self._detect_profit_drawdown(bars[index], snapshot, triggers)
        if profit_event:
            events.append(profit_event)

        breakdown_event = self._detect_technical_breakdown(index, bars, snapshot, triggers)
        if breakdown_event:
            events.append(breakdown_event)

        stop_loss_event = self._detect_stop_loss(bars[index], snapshot, triggers)
        if stop_loss_event:
            events.append(stop_loss_event)

        return events

    def _detect_account_risk(
        self,
        bar: SignalBar,
        snapshot: PortfolioSnapshot,
        triggers: list[TriggerSignal],
    ) -> BacktestEvent | None:
        account_triggers = [
            trigger for trigger in triggers
            if trigger.trigger_family == "account_risk"
            and trigger.trigger_type not in self._emitted_account_trigger_types
        ]
        if not account_triggers:
            return None
        self._emitted_account_trigger_types.update(trigger.trigger_type for trigger in account_triggers)
        return BacktestEvent(
            event_type="account_risk",
            date=bar.date,
            reason="账户级风控触发，必须优先重新评估风险",
            details={"trigger_signals": _triggers_to_dicts(account_triggers)},
            snapshot=snapshot,
        )

    def _detect_buy_candidate(
        self,
        index: int,
        bars: list[SignalBar],
        snapshot: PortfolioSnapshot,
        triggers: list[TriggerSignal],
    ) -> BacktestEvent | None:
        if snapshot.position_pct >= min(self.config.target_position_pct, self.config.max_single_position_pct):
            return None
        checklist = self.policy.evaluate_buy(index=index, bars=bars, snapshot=snapshot)
        if checklist.passed_count <= 2:
            return None
        if not checklist.account_allowed:
            return BacktestEvent(
                event_type="risk_block",
                date=bars[index].date,
                reason="买入信号出现，但账户级风控禁止新增风险",
                details={
                    "buy_signal": checklist.to_dict(),
                    "trigger_signals": _triggers_to_dicts(triggers),
                },
                snapshot=snapshot,
            )

        return BacktestEvent(
            event_type="buy_candidate",
            date=bars[index].date,
            reason="五维买入信号闭环达到至少3项，触发分批买入判断",
            details={
                "buy_signal": checklist.to_dict(),
                "trigger_signals": _triggers_to_dicts(triggers),
            },
            snapshot=snapshot,
        )

    def _detect_profit_drawdown(
        self,
        bar: SignalBar,
        snapshot: PortfolioSnapshot,
        triggers: list[TriggerSignal],
    ) -> BacktestEvent | None:
        if snapshot.position_pct <= 0:
            return None
        drawdown_from_peak = snapshot.peak_return_pct - snapshot.cumulative_return_pct
        if drawdown_from_peak < self.config.profit_drawdown_trigger_pct:
            return None
        return BacktestEvent(
            event_type="profit_drawdown",
            date=bar.date,
            reason="收益从阶段高点回撤达到阈值，触发止盈保护判断",
            details={
                "peak_return_pct": snapshot.peak_return_pct,
                "current_return_pct": snapshot.cumulative_return_pct,
                "drawdown_from_peak_pct": drawdown_from_peak,
                "trigger_signals": _triggers_to_dicts([
                    trigger for trigger in triggers
                    if trigger.trigger_family == "take_profit"
                ]),
            },
            snapshot=snapshot,
        )

    def _detect_technical_breakdown(
        self,
        index: int,
        bars: list[SignalBar],
        snapshot: PortfolioSnapshot,
        triggers: list[TriggerSignal],
    ) -> BacktestEvent | None:
        if snapshot.position_pct <= 0:
            return None
        closes = [bar.close for bar in bars[: index + 1]]
        volumes = [bar.volume for bar in bars[: index + 1]]
        expma_values = expma(closes, self.config.expma_window)
        volume_ratios = volume_ratio(volumes, self.config.buy_volume_window)
        current_volume_ratio = volume_ratios[index]
        if current_volume_ratio is None:
            return None
        previous_close = closes[index - 1] if index > 0 else closes[index]
        previous_expma = expma_values[index - 1] if index > 0 else expma_values[index]
        broke_down = previous_close >= previous_expma and closes[index] < expma_values[index]
        if not broke_down or current_volume_ratio < self.config.breakdown_volume_ratio:
            return None
        return BacktestEvent(
            event_type="technical_breakdown",
            date=bars[index].date,
            reason="参考标的放量跌破EXPMA，触发止盈/止损判断",
            details={
                "close": closes[index],
                "expma": expma_values[index],
                "volume_ratio": current_volume_ratio,
                "trigger_signals": _triggers_to_dicts([
                    trigger for trigger in triggers
                    if trigger.trigger_family in {"stop_loss", "take_profit"}
                ]),
            },
            snapshot=snapshot,
        )

    def _detect_stop_loss(
        self,
        bar: SignalBar,
        snapshot: PortfolioSnapshot,
        triggers: list[TriggerSignal],
    ) -> BacktestEvent | None:
        if snapshot.position_pct <= 0:
            return None
        if snapshot.cumulative_return_pct > -self.config.stop_loss_trigger_pct:
            return None
        return BacktestEvent(
            event_type="stop_loss",
            date=bar.date,
            reason="持仓亏损达到止损阈值，触发止损判断",
            details={
                "current_return_pct": snapshot.cumulative_return_pct,
                "trigger_signals": _triggers_to_dicts([
                    trigger for trigger in triggers
                    if trigger.trigger_family == "stop_loss"
                ]),
            },
            snapshot=snapshot,
        )


def _triggers_to_dicts(triggers: list[TriggerSignal]) -> list[dict[str, Any]]:
    return [trigger.to_dict() for trigger in triggers]
