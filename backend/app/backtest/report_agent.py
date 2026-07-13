"""Deterministic trade report agent for user-facing operation explanations."""
from __future__ import annotations

from typing import Any

from app.backtest.events import BacktestEvent
from app.backtest.models import BacktestConfig
from app.backtest.strategy import StrategyDecision


SIGNAL_LEVEL_LABELS = {
    "observe": "观察",
    "weak_buy": "弱买点",
    "middle_buy": "中买点",
    "strong_buy": "强买点",
    "risk_blocked": "观察",
}

ACTION_LABELS = {
    "buy": "按计划建仓",
    "sell": "减仓",
    "observe": "观察",
    "hold": "持有",
}


class ReportAgent:
    """Formats each triggered operation in the user's trading-system structure."""

    def __init__(self, config: BacktestConfig):
        self.config = config

    def build(self, event: BacktestEvent, decision: StrategyDecision) -> dict[str, Any]:
        buy_signal = event.details.get("buy_signal") if isinstance(event.details, dict) else None
        return {
            "current_conclusion": self._current_conclusion(buy_signal, decision),
            "account_check": self._account_check(event, buy_signal),
            "buy_signal_checks": self._buy_signal_checks(buy_signal),
            "trigger_conditions": self._trigger_conditions(event, decision, buy_signal),
            "risk_warnings": self._risk_warnings(event, decision, buy_signal),
            "one_sentence": self._one_sentence(event, decision, buy_signal),
        }

    def _current_conclusion(
        self,
        buy_signal: dict[str, Any] | None,
        decision: StrategyDecision,
    ) -> dict[str, Any]:
        raw_level = buy_signal.get("signal_level") if buy_signal else "observe"
        return {
            "signal_level": SIGNAL_LEVEL_LABELS.get(raw_level, "观察"),
            "suggested_action": ACTION_LABELS.get(decision.action, "观察"),
            "risk_control_passed": bool(buy_signal.get("account_allowed", True)) if buy_signal else True,
            "decision_reason": decision.reason,
        }

    def _account_check(
        self,
        event: BacktestEvent,
        buy_signal: dict[str, Any] | None,
    ) -> dict[str, Any]:
        snapshot = event.snapshot
        position_pct = snapshot.position_pct if snapshot else 0.0
        correlated_after = self.config.current_correlated_growth_exposure_pct
        if buy_signal:
            portfolio_dimension = next(
                (
                    item for item in buy_signal.get("dimensions", [])
                    if item.get("name") == "组合允许"
                ),
                {},
            )
            correlated_after = (
                portfolio_dimension.get("details", {}).get("correlated_after_buy")
                or correlated_after
            )
        total_safe = position_pct <= self.config.max_account_position_pct
        sector_safe = correlated_after <= self.config.max_correlated_growth_exposure_pct
        account_allowed = bool(buy_signal.get("account_allowed", True)) if buy_signal else True
        return {
            "current_total_position_pct": round(position_pct * 100, 2),
            "current_total_position_safe": total_safe,
            "current_sector_exposure_too_high": not sector_safe,
            "would_break_single_or_sector_limit": not sector_safe,
            "risk_control_passed": total_safe and sector_safe and account_allowed,
            "reasons": buy_signal.get("account_reasons", ["账户风控允许"]) if buy_signal else ["当前为卖出/持有事件，不新增风险"],
        }

    def _buy_signal_checks(self, buy_signal: dict[str, Any] | None) -> dict[str, Any]:
        names = ["趋势修复", "量能健康", "资金回流", "逻辑/催化验证", "组合允许"]
        checks = {
            name: {"passed": False, "reason": "本次不是买入信号，不评估该维度"}
            for name in names
        }
        if not buy_signal:
            return checks
        for item in buy_signal.get("dimensions", []):
            name = item.get("name")
            if name in checks:
                checks[name] = {
                    "passed": bool(item.get("passed")),
                    "reason": item.get("reason", ""),
                    "details": item.get("details", {}),
                }
        return checks

    def _trigger_conditions(
        self,
        event: BacktestEvent,
        decision: StrategyDecision,
        buy_signal: dict[str, Any] | None,
    ) -> dict[str, Any]:
        missing = self._missing_buy_conditions(buy_signal)
        upgrade_conditions = [
            "突破后第一次回踩不破",
            "资金连续2-3天回流且龙头强于板块",
            "新增催化与价格、量能形成共振",
        ]
        return {
            "event": event.reason,
            "decision": decision.reason,
            "missing_conditions": missing,
            "upgrade_conditions": upgrade_conditions if decision.action in {"buy", "observe", "hold"} else [],
            "raw_details": event.details,
        }

    def _risk_warnings(
        self,
        event: BacktestEvent,
        decision: StrategyDecision,
        buy_signal: dict[str, Any] | None,
    ) -> list[str]:
        if decision.action == "buy":
            warnings = [
                "买入后若同类成长赛道暴露升高，后续加仓信号必须更严格。",
                "当前买点来自确认信号，不代表后续趋势一定延续。",
                "若参考 ETF 放量跌破关键均线，必须按系统进入减仓或止损流程。",
            ]
        elif decision.action == "sell":
            warnings = [
                "卖出后不要因为单日反抽立刻接回，必须等待重新站稳。",
                "若剩余仓位继续破位，下一步按止损或二次减仓处理。",
                "若板块快速修复，也只按新的买入闭环重新评估，不追情绪。",
            ]
        else:
            warnings = [
                "信号闭环不足时不要提前埋伏。",
                "账户仓位或高相关暴露不允许时禁止加仓。",
                "单日异动不算买点，必须看连续性。",
            ]
        if event.event_type == "risk_block":
            warnings[0] = "账户级风控已经优先于板块机会，禁止新增风险。"
        if buy_signal and not buy_signal.get("account_allowed", True):
            warnings[1] = "账户风控未通过，即使技术信号出现也不能买入。"
        return warnings[:3]

    def _one_sentence(
        self,
        event: BacktestEvent,
        decision: StrategyDecision,
        buy_signal: dict[str, Any] | None,
    ) -> str:
        if decision.action == "buy":
            return "信号闭环已形成，但只允许按计划首次建仓，不允许一把梭哈。"
        if decision.action == "sell" and event.event_type == "technical_breakdown":
            return "系统已触发破位减仓条件，先卖高位/灵活仓和确认仓，核心仓只观察是否重新站回关键均线。"
        if decision.action == "sell" and event.event_type == "profit_drawdown":
            return "收益从高点回撤达到阈值，只卖命中基金批次自身止盈条件的批次，剩余批次继续按趋势纪律观察。"
        if decision.action == "sell" and event.event_type == "post_sell_observation":
            return "卖后观察期复核仍未修复，系统继续处理剩余风险仓位，并重新开启下一轮观察窗口。"
        if decision.action == "observe" and event.event_type == "post_sell_observation":
            return "卖后观察期未命中继续卖出条件，剩余仓位暂不处理，也不允许情绪化接回。"
        if decision.action == "sell" and event.event_type == "stop_loss":
            return "单标的已到止损线，不管主观判断如何，系统要求退出。"
        if decision.action == "observe" and buy_signal:
            return "当前只观察，没有信号闭环或账户许可，不买。"
        return "当前不新增动作，继续等待风险可控、信号闭环、仓位允许的机会。"

    def _missing_buy_conditions(self, buy_signal: dict[str, Any] | None) -> list[str]:
        if not buy_signal:
            return ["本次不是买入信号，等待新的五维买入闭环"]
        missing = [
            item.get("name", "未知维度")
            for item in buy_signal.get("dimensions", [])
            if not item.get("passed")
        ]
        return missing or ["已满足当前等级所需条件，后续关注回踩确认与账户暴露"]
