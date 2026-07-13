"""Batch-trading skill routing metadata for event-driven backtests."""
from __future__ import annotations

from typing import Any

from app.backtest.events import BacktestEvent
from app.backtest.models import BacktestConfig
from app.backtest.strategy import StrategyDecision

BATCH_TRADING_SKILLS = {
    "router": "batch-trading-router",
    "market_regime": "batch-trading-market-regime",
    "position_risk": "batch-trading-position-risk",
    "buy_signal": "batch-trading-buy-signal",
    "batch_planner": "batch-trading-batch-planner",
    "take_profit": "batch-trading-take-profit",
    "stop_loss": "batch-trading-stop-loss",
    "sell_execution": "batch-trading-sell-execution",
}


class BatchTradingSkillRouter:
    """Maps mechanical events to the user's batch-trading specialist skills."""

    def __init__(self, config: BacktestConfig):
        self.config = config

    def route(self, event: BacktestEvent, decision: StrategyDecision) -> dict[str, Any]:
        trigger_signals = _trigger_signals(event)
        highest_priority = self._effective_priority(event, trigger_signals)
        classified_intent = self._classified_intent(event, decision, trigger_signals)
        required_skill_order = self._required_skill_order(event, decision, classified_intent, highest_priority)
        immediate_vetoes = self._immediate_vetoes(event, trigger_signals, highest_priority)
        return {
            "system": "batch-trading",
            "system_name": "批次交易系统",
            "classified_intent": classified_intent,
            "highest_priority": highest_priority,
            "immediate_vetoes": immediate_vetoes,
            "required_skill_order": required_skill_order,
            "direct_answer_allowed": not any(veto["blocking"] for veto in immediate_vetoes),
            "missing_information": self._missing_information(classified_intent),
            "priority_note": self._priority_note(classified_intent, highest_priority),
            "next_step": self._next_step(required_skill_order),
        }

    def _effective_priority(self, event: BacktestEvent, trigger_signals: list[dict[str, Any]]) -> str:
        priority = _highest_priority(trigger_signals)
        if event.event_type in {"stop_loss", "technical_breakdown"} and priority not in {"P0", "P1"}:
            return "P1"
        if event.event_type == "post_sell_observation" and priority not in {"P0", "P1", "P2"}:
            return "P2"
        return priority

    def _classified_intent(
        self,
        event: BacktestEvent,
        decision: StrategyDecision,
        trigger_signals: list[dict[str, Any]],
    ) -> str:
        families = {trigger.get("trigger_family") for trigger in trigger_signals}
        if event.event_type == "account_risk" or "account_risk" in families:
            return "account_risk_control"
        if event.event_type in {"stop_loss", "technical_breakdown"} or "stop_loss" in families:
            return "stop_loss_or_breakdown"
        if event.event_type == "post_sell_observation" and decision.action == "sell":
            return "sell_execution"
        if event.event_type == "profit_drawdown" or "take_profit" in families:
            return "take_profit"
        if "buy_observation" in families or "add_position" in families:
            return "buy_or_add"
        if event.event_type in {"buy_candidate", "risk_block"} or decision.action == "buy":
            return "buy_or_add"
        if event.event_type == "technical_breakdown" and decision.action == "sell":
            return "sell_execution"
        return "observe_or_hold"

    def _required_skill_order(
        self,
        event: BacktestEvent,
        decision: StrategyDecision,
        classified_intent: str,
        highest_priority: str,
    ) -> list[str]:
        router = BATCH_TRADING_SKILLS["router"]
        if highest_priority == "P0" or classified_intent == "account_risk_control":
            return [
                router,
                BATCH_TRADING_SKILLS["position_risk"],
                BATCH_TRADING_SKILLS["stop_loss"],
                BATCH_TRADING_SKILLS["sell_execution"],
            ]
        if classified_intent == "stop_loss_or_breakdown":
            return [
                router,
                BATCH_TRADING_SKILLS["position_risk"],
                BATCH_TRADING_SKILLS["stop_loss"],
                BATCH_TRADING_SKILLS["sell_execution"],
            ]
        if classified_intent == "take_profit":
            return [
                router,
                BATCH_TRADING_SKILLS["market_regime"],
                BATCH_TRADING_SKILLS["take_profit"],
                BATCH_TRADING_SKILLS["sell_execution"],
            ]
        if classified_intent == "buy_or_add":
            return [
                router,
                BATCH_TRADING_SKILLS["market_regime"],
                BATCH_TRADING_SKILLS["position_risk"],
                BATCH_TRADING_SKILLS["buy_signal"],
                BATCH_TRADING_SKILLS["batch_planner"],
            ]
        if decision.action == "sell":
            return [router, BATCH_TRADING_SKILLS["sell_execution"]]
        return [router]

    def _immediate_vetoes(
        self,
        event: BacktestEvent,
        trigger_signals: list[dict[str, Any]],
        highest_priority: str,
    ) -> list[dict[str, Any]]:
        vetoes: list[dict[str, Any]] = []
        if highest_priority == "P0":
            vetoes.append({
                "rule": "账户级风控优先",
                "blocking": True,
                "reason": "P0 账户风控触发，禁止买入/禁止加仓，必须先处理账户风险",
            })
        if event.event_type == "risk_block":
            vetoes.append({
                "rule": "账户不允许新增风险",
                "blocking": True,
                "reason": event.reason,
            })
        if any(trigger.get("trigger_family") == "stop_loss" for trigger in trigger_signals):
            vetoes.append({
                "rule": "止损优先于持有和止盈",
                "blocking": event.event_type in {"buy_candidate", "risk_block"},
                "reason": "存在止损/破位触发，先交给 stop-loss 模块判断",
            })
        return vetoes

    def _missing_information(self, classified_intent: str) -> list[str]:
        missing: list[str] = []
        if classified_intent in {"buy_or_add", "take_profit"}:
            missing.append("market_regime_score")
        if classified_intent in {"buy_or_add", "stop_loss_or_breakdown", "account_risk_control"}:
            missing.append("single_symbol_stop_loss_width")
        if classified_intent in {"buy_or_add", "take_profit", "stop_loss_or_breakdown"}:
            missing.append("batch_records")
        return missing

    def _priority_note(self, classified_intent: str, highest_priority: str) -> str:
        if highest_priority == "P0":
            return "账户风控优先：买入、补仓、止盈偏好都必须后置。"
        if classified_intent == "stop_loss_or_breakdown":
            return "止损/趋势破坏优先于普通持有和利润保护。"
        if classified_intent == "take_profit":
            return "止盈属于利润保护，低于账户风控和止损，高于普通再平衡。"
        if classified_intent == "buy_or_add":
            return "买入热情最低优先级，必须先通过市场环境和账户风控。"
        return "当前仅需观察或保持，不触发下游 specialist。"

    def _next_step(self, required_skill_order: list[str]) -> dict[str, str]:
        next_skill = required_skill_order[1] if len(required_skill_order) > 1 else required_skill_order[0]
        return {
            "invoke": next_skill,
            "reason": "按批次交易系统优先级继续评估",
        }


def _trigger_signals(event: BacktestEvent) -> list[dict[str, Any]]:
    raw = event.details.get("trigger_signals", [])
    return [item for item in raw if isinstance(item, dict)]


def _highest_priority(trigger_signals: list[dict[str, Any]]) -> str:
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}
    priorities = [
        item.get("priority")
        for item in trigger_signals
        if item.get("priority") in order
    ]
    if not priorities:
        return "P4"
    return min(priorities, key=lambda item: order[item])
