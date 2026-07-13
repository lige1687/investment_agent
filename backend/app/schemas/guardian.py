"""Guardian schemas — the types the daily-scan agent produces.

Guardian runs twice a day (midday 11:30, close 14:30) and produces:
  - Zero or more `HoldingAlert` (rule-based triggers per holding)
  - Exactly one `BriefingResult` per run (aggregate summary + all cards)

The alerts feed straight into DecisionCard rows so the frontend renders
them the same way as advisor-emitted cards.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class BriefingSlot(str, Enum):
    MIDDAY = "midday"      # 11:30 午盘 — 上半场收盘后
    CLOSE = "close"        # 14:30 尾盘 — 尾盘决策窗口
    MANUAL = "manual"      # 用户按钮触发的立即体检


class AlertSeverity(str, Enum):
    LOW = "LOW"            # 观察,不必立即行动
    MEDIUM = "MEDIUM"      # 建议关注 / 调整
    HIGH = "HIGH"          # 立即处理


class AlertTrigger(str, Enum):
    """Why the alert fired. Every trigger has its own rule in HoldingHealthChecker."""
    LOSS_DEEP = "LOSS_DEEP"                 # 单只浮亏过深
    LOSS_EXPANDING = "LOSS_EXPANDING"       # 亏损加速扩大(需近期比较)
    CONCENTRATION_HIGH = "CONCENTRATION_HIGH"  # 单持仓占比过高
    TOP3_CONCENTRATION = "TOP3_CONCENTRATION"  # 前三持仓占比过高
    OVERLAP_DUPLICATE = "OVERLAP_DUPLICATE"    # 同一基金 A/C 双份或高度重叠
    PROFIT_TAKE = "PROFIT_TAKE"             # 单只浮盈过高,考虑分批止盈


class HoldingAlert(BaseModel):
    """One rule-triggered alert for one holding.

    Consumed by GuardianAgent to (a) decide which cards to emit and
    (b) prompt the LLM with an explicit reason.
    """
    model_config = ConfigDict(use_enum_values=True)

    code: str
    name: str
    trigger: AlertTrigger
    severity: AlertSeverity
    note: str = Field(..., min_length=1)  # human-readable, e.g. "浮亏 -25%,仓位 5.4%"
    metric_value: Optional[float] = None  # the numeric that triggered it
    threshold: Optional[float] = None     # the rule's threshold

    def one_line(self) -> str:
        return f"[{self.severity}] {self.name}({self.code}) — {self.trigger}: {self.note}"


class BriefingResult(BaseModel):
    """What one Guardian run outputs — persisted and returned by the API."""
    model_config = ConfigDict(use_enum_values=True)

    session_id: str
    slot: BriefingSlot
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    finished_at: Optional[str] = None

    portfolio_snapshot: dict = Field(
        default_factory=dict,
        description="Total value / pnl / position count / risk level at scan time",
    )
    market_snapshot: dict = Field(
        default_factory=dict,
        description="Market overview at scan time (indices, sentiment, etc.)",
    )
    alerts: list[HoldingAlert] = Field(default_factory=list)
    decision_ids: list[str] = Field(
        default_factory=list,
        description="All DecisionCard ids emitted by this run (briefing + per-alert).",
    )
    briefing_text: Optional[str] = Field(
        default=None,
        description="Human-facing summary — what got pushed to Feishu.",
    )
    llm_used: bool = False
    error: Optional[str] = None
    pushed_to_feishu: bool = False
