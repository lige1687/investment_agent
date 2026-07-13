"""Role schemas and verified-skill bindings for the daily trading room."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import settings
from app.llm.base import LLMClient
from app.llm.registry import get_llm_client
from app.trading_room.schemas import ActionClass, DecisionRange, RiskState, ThemePhase
from app.trading_room.skill_registry import TradingSkillRegistry
from app.trading_room.specialists.base import SpecialistRunner


class StrictMemo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)


class MarketRegimeMemo(StrictMemo):
    phase: ThemePhase
    regime_score: int = Field(ge=0, le=100)
    buy_permission: Literal["allowed", "conditional", "blocked"]
    counter_evidence: list[str] = Field(default_factory=list)


class ThemeFundMemo(StrictMemo):
    fund_code: str
    theme: str
    phase: ThemePhase
    exposure_confidence: Literal["HIGH", "MEDIUM", "LOW", "UNKNOWN"]
    report_period_end: str | None = None
    supporting_evidence: list[str] = Field(default_factory=list)
    counter_evidence: list[str] = Field(default_factory=list)


class PortfolioRiskMemo(StrictMemo):
    risk_state: RiskState
    new_buy_allowed: bool
    findings: list[str] = Field(default_factory=list)


class BuyMemo(StrictMemo):
    score: int = Field(ge=0, le=100)
    action_class: ActionClass
    suggested_range: DecisionRange | None = None
    triggers: list[str] = Field(min_length=1)
    invalidations: list[str] = Field(min_length=1)


class SellProtectionMemo(StrictMemo):
    action_class: ActionClass
    suggested_range: DecisionRange | None = None
    reason_priority: Literal["logic_failure", "effective_trend_break", "percentage_stop", "none"]
    triggers: list[str] = Field(default_factory=list)


class SkepticFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_type: Literal[
        "stale_or_mock", "duplicate_evidence", "unsupported_claim", "logic_gap",
        "announcement_misread", "holding_period_misread", "missing_input",
    ]
    description: str = Field(min_length=1)
    impact: str = Field(min_length=1)
    evidence_ref: str | None = None
    missing_field: str | None = None

    @model_validator(mode="after")
    def require_grounding(self) -> "SkepticFinding":
        if not self.evidence_ref and not self.missing_field:
            raise ValueError("evidence_ref or missing_field is required")
        return self


class SkepticMemo(StrictMemo):
    findings: list[SkepticFinding]


class RecorderMemo(StrictMemo):
    action_class: ActionClass
    proposed_range: DecisionRange | None = None
    source_roles: list[str] = Field(min_length=1)
    disagreements: list[str] = Field(default_factory=list)


class ChairMemo(StrictMemo):
    action_class: ActionClass
    guarded_range: DecisionRange | None = None
    user_summary: str = Field(min_length=1)
    conditions: list[str] = Field(default_factory=list)


ROLE_DEFINITIONS = {
    "market_regime": (
        MarketRegimeMemo,
        ("batch-trading-router", "batch-trading-market-regime"),
        "先判断市场环境；没有环境结论时不得推进买入。",
    ),
    "theme_fund": (
        ThemeFundMemo,
        ("hithink-fund-query", "fund-analysis"),
        "主动基金公开持仓不是实时持仓，必须注明报告期与推断置信度。",
    ),
    "portfolio_risk": (
        PortfolioRiskMemo,
        ("batch-trading-position-risk",),
        "只解释确定性风险指标，未确认阈值只能标为参考。",
    ),
    "buy": (
        BuyMemo,
        ("batch-trading-buy-signal",),
        "分数评价机会质量，不得把分数直接换算成金额。",
    ),
    "sell_protection": (
        SellProtectionMemo,
        ("batch-trading-stop-loss", "batch-trading-take-profit"),
        "优先级是逻辑失效、有效趋势破坏、用户明确启用的百分比止损。",
    ),
    "skeptic": (
        SkepticMemo,
        ("batch-trading-router",),
        "只能审查证据真实性和逻辑漏洞；不得输出分数、金额、仓位建议或新市场观点。"
        "每条质疑必须有 evidence_ref 或 missing_field。",
    ),
    "recorder": (
        RecorderMemo,
        ("batch-trading-router",),
        "只能整理已有 memo，不能创造未被任何专业席位提出的动作。",
    ),
    "chair": (
        ChairMemo,
        ("batch-trading-router",),
        "只能解释护栏后的结构化结果，不得放大可执行金额。",
    ),
}


def create_specialist(
    role: str,
    *,
    client: LLMClient | None = None,
    skill_registry: TradingSkillRegistry | None = None,
) -> SpecialistRunner:
    try:
        schema, skill_names, constraints = ROLE_DEFINITIONS[role]
    except KeyError as exc:
        raise KeyError(f"unknown trading-room specialist: {role}") from exc

    registry = skill_registry or TradingSkillRegistry(
        trading_root=settings.trading_skill_root,
        market_root=settings.market_skill_root,
    )
    temperature = (
        settings.trading_room_chair_temperature
        if role in {"recorder", "chair"}
        else settings.trading_room_analysis_temperature
    )
    return SpecialistRunner(
        role=role,
        output_schema=schema,
        client=client or get_llm_client(role),
        skill_registry=registry,
        skill_names=skill_names,
        temperature=temperature,
        role_constraints=constraints,
    )
