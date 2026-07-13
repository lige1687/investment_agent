"""Detailed execution logger for backtest trading decisions."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
from typing import Any
from app.backtest.events import BacktestEvent
from app.backtest.strategy import StrategyDecision


@dataclass
class ExecutionLog:
    """Record of a single trading decision execution."""

    date: date
    event_type: str
    trigger_reason: str
    signal_info: dict[str, Any]
    decision_action: str
    decision_reason: str
    position_before: float
    position_after: float
    equity_before: float
    equity_after: float
    nav: float
    trade_executed: bool
    additional_details: dict[str, Any]

    def to_markdown_row(self) -> str:
        """Convert to markdown table row."""
        signal_str = ", ".join(
            f"{k}={v}" for k, v in self.signal_info.items() if v
        ) or "N/A"
        return f"| {self.date} | {self.event_type} | {self.trigger_reason[:30]} | {signal_str[:40]} | {self.decision_action} | {self.decision_reason[:40]} | {self.position_before:.1%} | {self.position_after:.1%} | {'✓' if self.trade_executed else '✗'} |"


class ExecutionLogger:
    """Manages backtest execution logging."""

    def __init__(self):
        self.logs: list[ExecutionLog] = []

    def record(
        self,
        date: date,
        event: BacktestEvent,
        decision: StrategyDecision,
        snapshot_before: dict[str, float],
        snapshot_after: dict[str, float],
        nav: float,
        trade_executed: bool,
    ) -> None:
        """Record a trading decision execution."""
        signal_info = event.details.get("buy_signal", {}) or event.details.get(
            "original_buy_signal", {}
        )
        signal_info_dict = {
            "signal_level": signal_info.get("signal_level"),
            "passed_count": signal_info.get("passed_count"),
        }

        log = ExecutionLog(
            date=date,
            event_type=event.event_type,
            trigger_reason=event.reason,
            signal_info=signal_info_dict,
            decision_action=decision.action,
            decision_reason=decision.reason,
            position_before=snapshot_before.get("position_pct", 0.0),
            position_after=snapshot_after.get("position_pct", 0.0),
            equity_before=snapshot_before.get("equity", 0.0),
            equity_after=snapshot_after.get("equity", 0.0),
            nav=nav,
            trade_executed=trade_executed,
            additional_details={
                "observe_days": decision.observe_days,
                "target_position_delta": decision.target_position_delta_pct,
                "ratio_of_position": decision.ratio_of_position,
            },
        )
        self.logs.append(log)

    def to_markdown(self) -> str:
        """Generate markdown report of all executions."""
        if not self.logs:
            return "# 交易执行日志\n\n暂无交易记录\n"

        md = "# 交易执行日志\n\n"
        md += f"**总记录数**: {len(self.logs)}\n\n"

        # Summary statistics
        buy_count = sum(1 for log in self.logs if log.decision_action == "buy")
        sell_count = sum(
            1 for log in self.logs if log.decision_action == "sell"
        )
        executed_count = sum(1 for log in self.logs if log.trade_executed)

        md += "## 执行统计\n\n"
        md += f"- 买入决策: {buy_count}\n"
        md += f"- 卖出决策: {sell_count}\n"
        md += f"- 实际执行: {executed_count}\n"
        md += f"- 观察等待: {len(self.logs) - executed_count}\n\n"

        # Grouped by event type
        event_types = {}
        for log in self.logs:
            if log.event_type not in event_types:
                event_types[log.event_type] = []
            event_types[log.event_type].append(log)

        for event_type, logs in sorted(event_types.items()):
            md += f"## {self._event_type_label(event_type)}\n\n"
            md += "| 日期 | 事件 | 触发原因 | 信号 | 决策 | 决策原因 | 仓位前 | 仓位后 | 执行 |\n"
            md += "|------|------|---------|------|------|---------|--------|--------|------|\n"
            for log in logs:
                md += log.to_markdown_row() + "\n"
            md += "\n"

        # Detailed logs
        md += "## 详细决策日志\n\n"
        for i, log in enumerate(self.logs, 1):
            md += f"### #{i} {log.date} - {log.event_type}\n\n"
            md += f"**触发事件**: {log.trigger_reason}\n\n"

            if log.signal_info.get("signal_level"):
                md += f"**信号强度**: {log.signal_info['signal_level']} ({log.signal_info.get('passed_count', '?')}/5)\n\n"

            md += f"**策略决策**: {log.decision_action.upper()}\n\n"
            md += f"**决策原因**: {log.decision_reason}\n\n"

            md += "**仓位变化**:\n"
            md += f"- 执行前: {log.position_before:.1%} (净值: ¥{log.equity_before:,.0f})\n"
            md += f"- 执行后: {log.position_after:.1%} (净值: ¥{log.equity_after:,.0f})\n"
            md += f"- NAV: {log.nav:.4f}\n\n"

            md += f"**执行状态**: {'✓ 已执行' if log.trade_executed else '✗ 未执行(观察中)'}\n\n"

            if log.additional_details.get("observe_days"):
                md += f"**观察期**: {log.additional_details['observe_days']} 天\n\n"

            if log.additional_details.get("target_position_delta"):
                md += f"**目标仓位变化**: {log.additional_details['target_position_delta']:.1%}\n\n"

            md += "---\n\n"

        return md

    @staticmethod
    def _event_type_label(event_type: str) -> str:
        """Get human-readable label for event type."""
        labels = {
            "buy_candidate": "📈 买入候选信号",
            "buy_confirmation": "✓ 买入确认执行",
            "profit_drawdown": "📊 止盈保护触发",
            "technical_breakdown": "📉 技术面破位",
            "post_sell_observation": "🔍 卖后观察期",
            "stop_loss": "❌ 止损触发",
            "account_risk": "⚠️ 账户风控",
            "risk_block": "🛑 风险阻挡",
        }
        return labels.get(event_type, f"其他: {event_type}")
