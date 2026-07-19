"""Strategy decision policy for triggered backtest events."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.backtest.events import BacktestEvent
from app.backtest.models import BacktestConfig

StrategyAction = Literal["buy", "sell", "observe", "hold"]


@dataclass(frozen=True)
class StrategyDecision:
    action: StrategyAction
    reason: str
    target_position_delta_pct: float = 0.0
    ratio_of_position: float = 0.0
    observe_days: int = 0
    gate: str | None = None  # visible gate for hold/observe decisions


class RuleBasedStrategyAgent:
    """Deterministic MVP substitute for a future LLM strategy agent."""

    def __init__(self, config: BacktestConfig):
        self.config = config

    def decide(self, event: BacktestEvent) -> StrategyDecision:
        if event.event_type == "account_risk":
            return StrategyDecision(
                action="observe",
                reason="账户级风控触发，禁止买入/禁止加仓，先保账户风险",
            )
        if event.event_type == "buy_candidate":
            # buy_candidate 现在由 TriggerScanner 触发、引擎直接管理观察期，
            # strategy.decide() 不再在非 test 模式下被调用。
            # 保留 account_risk / dust 检查供 test 模式记录。
            trigger_signals = event.details.get("trigger_signals", [])
            if any(
                trigger.get("priority") == "P0" and trigger.get("trigger_family") == "account_risk"
                for trigger in trigger_signals
                if isinstance(trigger, dict)
            ):
                return StrategyDecision(
                    action="observe",
                    observe_days=self.config.observe_days,
                    reason="P0账户风控触发，禁止买入/禁止加仓，先重新评估账户风险",
                )

            # 检查 dust 买入（剩余仓位空间太小）
            snapshot = event.snapshot
            current_position_pct = snapshot.position_pct if snapshot else 0.0
            effective_target = min(
                self.config.target_position_pct,
                self.config.max_single_position_pct,
                self.config.max_account_position_pct,
            )
            remaining_target = max(effective_target - current_position_pct, 0.0)
            if remaining_target < self.config.min_trade_position_pct:
                return StrategyDecision(
                    action="hold",
                    reason="剩余可买空间低于最小交易仓位，忽略零头补仓",
                )

            # 统一观察期：不再按 5 维 signal_level 分级（已删除死规则）
            return StrategyDecision(
                action="observe",
                reason="放量突破站上EXPMA，进入观察期确认站稳",
                observe_days=2,
            )
        if event.event_type == "buy_confirmation":
            return self._decide_buy(event)
        if event.event_type == "risk_block":
            return StrategyDecision(
                action="observe",
                reason="账户级风控禁止新增风险，禁止买入/禁止加仓",
            )
        if event.event_type == "profit_drawdown":
            snapshot = event.snapshot
            if snapshot and snapshot.position_pct < self.config.min_trade_position_pct:
                return StrategyDecision(
                    action="hold",
                    reason="剩余仓位低于最小交易仓位，小仓位不做碎片化止盈",
                )
            return StrategyDecision(
                action="sell",
                ratio_of_position=0.5,
                observe_days=self.config.observe_days,
                reason="收益高点回撤达到阈值，按批次交易系统检查基金批次自身浮盈与回撤，命中批次按卖出优先级处理",
            )
        if event.event_type == "technical_breakdown":
            return StrategyDecision(
                action="sell",
                ratio_of_position=0.5,
                observe_days=self.config.observe_days,
                reason="参考标的放量跌破关键EXPMA，按批次交易系统优先卖出高位/灵活仓和确认仓，核心仓继续观察",
            )
        if event.event_type == "post_sell_observation":
            snapshot = event.snapshot
            if snapshot and snapshot.position_pct < self.config.min_trade_position_pct:
                return StrategyDecision(
                    action="hold",
                    reason="卖后观察期内剩余仓位低于最小交易仓位，不做碎片化处理",
                )
            if event.details.get("recommended_action") == "sell":
                return StrategyDecision(
                    action="sell",
                    ratio_of_position=0.5,
                    observe_days=3,
                    reason="卖后观察期复核仍未修复，按批次交易系统继续处理剩余风险仓位",
                )
            return StrategyDecision(
                action="observe",
                observe_days=1,
                reason="卖后观察期复核未命中继续卖出条件，剩余仓位暂不处理且禁止情绪化接回",
            )
        if event.event_type == "stop_loss":
            return StrategyDecision(
                action="sell",
                ratio_of_position=1.0,
                reason="持仓亏损达到止损阈值，执行清仓止损",
            )
        return StrategyDecision(action="hold", reason="事件类型未匹配动作，保持不动")

    def _decide_buy(self, event: BacktestEvent) -> StrategyDecision:
        trigger_signals = event.details.get("trigger_signals", [])
        if any(
            trigger.get("priority") == "P0" and trigger.get("trigger_family") == "account_risk"
            for trigger in trigger_signals
            if isinstance(trigger, dict)
        ):
            return StrategyDecision(
                action="observe",
                observe_days=self.config.observe_days,
                reason="P0账户风控触发，禁止买入/禁止加仓，先重新评估账户风险",
                gate="account_risk",
            )

        # Task 8: Check prosperity rejection
        market_regime = event.details.get("market_regime", "neutral")
        if market_regime == "rejected":
            return StrategyDecision(
                action="hold",
                reason="经济景气度低于50，拒绝买入",
                gate="prosperity_rejected",
            )

        snapshot = event.snapshot
        current_position_pct = snapshot.position_pct if snapshot else 0.0
        effective_target = min(
            self.config.target_position_pct,
            self.config.max_single_position_pct,
            self.config.max_account_position_pct,
        )
        remaining_target = max(effective_target - current_position_pct, 0.0)
        if remaining_target <= 0:
            return StrategyDecision(
                action="hold", reason="当前仓位已达到目标仓位，不再加仓", gate="target_reached"
            )
        if remaining_target < self.config.min_trade_position_pct:
            return StrategyDecision(
                action="hold",
                reason="剩余可买空间低于最小交易仓位，忽略零头补仓",
                gate="min_trade_floor",
            )

        # 对于 buy_confirmation 事件，使用原始的买入信号
        buy_signal = event.details.get("original_buy_signal", {})
        signal_level = buy_signal.get("signal_level")

        # Task 8: Regime-based tier downgrading
        # In bear/neutral regime, downgrade to confirmation batch only (6%)
        # In bull regime, use full tier allocation
        if market_regime in ("bear", "neutral"):
            # Downgrade: target 20% → confirmation batch 6% only
            buy_scale = 0.3  # 6% / 20% = 0.3 of effective_target
            scale_reason = f"市场制度={market_regime}，降档至确认仓(6%)，不买核心仓(10%)"
        else:
            # Bull regime: use normal sizing
            if signal_level == "strong_buy":
                buy_scale = 1.0
                scale_reason = f"强买信号且market_regime={market_regime}，建满100%目标仓位"
            elif signal_level == "middle_buy":
                buy_scale = 0.7
                scale_reason = f"中等买信号，market_regime={market_regime}，建仓70%目标仓位"
            else:  # weak_buy
                buy_scale = 0.5
                scale_reason = f"弱买信号，market_regime={market_regime}，建仓50%目标仓位"

        buy_size = min(effective_target * buy_scale, remaining_target)
        if buy_size < self.config.min_trade_position_pct:
            return StrategyDecision(
                action="hold",
                reason="本次买入低于最小交易仓位，忽略零头补仓",
                gate="min_trade_floor",
            )

        reason = f"{scale_reason}，保留后续确认仓位"

        return StrategyDecision(
            action="buy",
            target_position_delta_pct=round(buy_size, 4),
            observe_days=5,
            reason=reason,
        )
