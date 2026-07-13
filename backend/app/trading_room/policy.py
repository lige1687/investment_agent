"""Versioned user-confirmed policy templates for the daily trading room."""

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.trading_room.schemas import TargetAllocation, TrendBreakPolicy


class TradingPolicyTemplate(BaseModel):
    model_config = ConfigDict(frozen=True)

    template_id: Literal["mid-term-theme-v1"]
    display_name: str
    buy_obvious_threshold: int = Field(ge=0, le=100)
    conditional_buy_min: int = Field(ge=0, le=100)
    account_drawdown_warning_pct: float
    account_drawdown_derisk_pct: float
    account_drawdown_protection_pct: float
    percentage_stop_enabled: bool
    percentage_stop_pct: float | None
    stop_priority: tuple[str, ...]
    trend_break: TrendBreakPolicy


class TradingPolicy(TradingPolicyTemplate):
    version_id: str
    created_at: datetime
    target_allocations: tuple[TargetAllocation, ...]
    ready: bool
    missing_confirmations: tuple[str, ...]


MID_TERM_THEME_V1 = TradingPolicyTemplate(
    template_id="mid-term-theme-v1",
    display_name="中线题材波段",
    buy_obvious_threshold=80,
    conditional_buy_min=65,
    account_drawdown_warning_pct=5.0,
    account_drawdown_derisk_pct=7.5,
    account_drawdown_protection_pct=10.0,
    percentage_stop_enabled=False,
    percentage_stop_pct=None,
    stop_priority=("logic_failure", "effective_trend_break", "percentage_stop"),
    trend_break=TrendBreakPolicy(
        consecutive_closes_min=2,
        consecutive_closes_max=3,
        breakdown_magnitude_min_pct=2.0,
        breakdown_magnitude_max_pct=3.0,
        reclaim_required=True,
        volume_break_confirms=True,
    ),
)


def get_policy_template(template_id: str) -> TradingPolicyTemplate:
    if template_id != MID_TERM_THEME_V1.template_id:
        raise KeyError(f"unknown policy template: {template_id}")
    return MID_TERM_THEME_V1


def import_policy_template(
    template_id: str,
    *,
    target_allocations: list[TargetAllocation],
) -> TradingPolicy:
    template = get_policy_template(template_id)
    targets = tuple(target_allocations)
    missing = () if targets else ("target_allocations",)
    return TradingPolicy(
        **template.model_dump(),
        version_id=str(uuid4()),
        created_at=datetime.now(timezone.utc),
        target_allocations=targets,
        ready=not missing,
        missing_confirmations=missing,
    )

