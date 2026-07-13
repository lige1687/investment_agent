"""Decision card schema — the structured output that agents emit instead of
free-form prose.

Design principles (see architecture doc):
1. 6 dimensions are kept SEPARATE — no forced score aggregation.
2. Conflicts between dimensions are declared EXPLICITLY.
3. Every signal points at an evidence_ref so the UI can show the raw source.
4. Portfolio context is a first-class field, not a footnote.
5. execution_plan / monitoring are optional — WATCH cards may omit them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Enums ─────────────────────────────────────────────────────────────────

class DecisionType(str, Enum):
    BUY_CANDIDATE = "BUY_CANDIDATE"
    SELL_ALERT = "SELL_ALERT"
    REBALANCE = "REBALANCE"
    WATCH = "WATCH"
    NONE = "NONE"                    # Question wasn't a decision-shaped Q


class ActionVerb(str, Enum):
    BUY = "BUY"
    ADD = "ADD"                      # 加仓
    HOLD = "HOLD"
    REDUCE = "REDUCE"                # 减仓
    SELL = "SELL"
    WATCH = "WATCH"
    AVOID = "AVOID"


class Urgency(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class DimensionKey(str, Enum):
    """The 6 dimensions the sector/holding is judged across.

    NOTE: Keep these stable — the frontend renders a radar chart keyed by
    exactly these values.
    """
    TECHNICAL = "technical"          # 技术面 — K 线、均线、形态
    CAPITAL = "capital"              # 资金面 — 主力流向、成交量
    MACRO = "macro"                  # 宏观面 — 流动性、利率、大盘
    NEWS = "news"                    # 消息面 — 政策、事件、舆情
    FINANCIAL = "financial"          # 财务面 — ROE、增长率、估值
    CONSENSUS = "consensus"          # 机构面 — 评级、目标价、报告


class TargetKind(str, Enum):
    FUND = "fund"
    STOCK = "stock"
    ETF = "etf"
    SECTOR = "sector"
    INDEX = "index"
    PORTFOLIO = "portfolio"          # For REBALANCE-type cards


class PortfolioRole(str, Enum):
    """Relationship of a candidate to the user's current holdings."""
    COMPLEMENT = "COMPLEMENT"        # Lowers concentration
    STRENGTHEN = "STRENGTHEN"        # Adds to an existing exposure
    DUPLICATE = "DUPLICATE"          # Highly correlated with a holding
    NEW = "NEW"                      # Fresh direction, no overlap


# ── Nested value objects ──────────────────────────────────────────────────

class Target(BaseModel):
    kind: TargetKind
    code: Optional[str] = Field(
        default=None,
        description="Fund/stock/ETF code. May be None for a whole-sector card.",
    )
    name: str


class Action(BaseModel):
    verb: ActionVerb
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="How sure the agent is. NOT a rating of the target.",
    )
    urgency: Urgency = Urgency.MEDIUM


class Dimension(BaseModel):
    """One of the 6 evaluation axes."""
    key: DimensionKey
    score: float = Field(ge=0.0, le=10.0)
    signal: str = Field(
        min_length=1,
        description="One-sentence human summary of what this axis says.",
    )
    evidence_ref: Optional[str] = Field(
        default=None,
        description="ev_xxx id in the evidence bus — click-through raw data.",
    )


class Conflict(BaseModel):
    """Explicit disagreement between two dimensions.

    Emit whenever two axes point opposite directions (e.g. technical strong,
    financial weak). Never silently average them.
    """
    between: list[DimensionKey] = Field(min_length=2, max_length=6)
    note: str


class PortfolioContext(BaseModel):
    overlap_with_holdings: list[str] = Field(
        default_factory=list,
        description="Human-readable notes on overlaps, e.g. '001513 已重仓半导体 12%'",
    )
    role: PortfolioRole = PortfolioRole.NEW
    warning: Optional[str] = Field(
        default=None,
        description="Concentration/duplication risk callout.",
    )


class EntryPlan(BaseModel):
    style: str = Field(
        description="'batched' | 'single' | 'dca' | free-form",
    )
    batches: Optional[int] = Field(default=None, ge=1, le=20)
    trigger: Optional[str] = Field(
        default=None,
        description="Human-readable entry condition, e.g. '回踩5日线'",
    )


class StopLoss(BaseModel):
    type: str = Field(description="'trailing' | 'fixed' | 'none' | free-form")
    value: str = Field(description="e.g. '-8%'")


class TakeProfitLevel(BaseModel):
    at: str = Field(description="Trigger, e.g. '+15%' or '突破200日线'")
    action: str = Field(description="What to do, e.g. '减半'")


class TakeProfit(BaseModel):
    levels: list[TakeProfitLevel] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    position_size_pct: Optional[str] = Field(
        default=None,
        description="Position sizing, e.g. '3-5%' of portfolio",
    )
    entry: Optional[EntryPlan] = None
    stop_loss: Optional[StopLoss] = None
    take_profit: Optional[TakeProfit] = None


# ── The card itself ───────────────────────────────────────────────────────

def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DecisionCard(BaseModel):
    """Structured output every agent emits when it has a real recommendation.

    Follow-up chat can attach to the same session and reference this by id.
    """

    model_config = ConfigDict(use_enum_values=True)

    decision_id: str = Field(min_length=1)
    created_at: str = Field(default_factory=_utcnow_iso)
    agent: str = Field(
        description="'advisor' | 'scout' | 'guardian'",
    )
    session_id: Optional[str] = None

    type: DecisionType
    target: Target
    action: Action

    headline: Optional[str] = Field(
        default=None,
        description="One-line title, e.g. '半导体 - 中芯国际 强势突破,可小仓试探'",
    )
    summary: Optional[str] = Field(
        default=None,
        description="2-4 sentence rationale, human readable.",
    )

    dimensions: list[Dimension] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)

    portfolio_context: Optional[PortfolioContext] = None
    execution_plan: Optional[ExecutionPlan] = None
    monitoring: list[str] = Field(
        default_factory=list,
        description="Conditions Guardian should watch for after entry.",
    )

    evidence_refs: list[str] = Field(
        default_factory=list,
        description="All ev_xxx ids referenced by this card (union of dimensions).",
    )
    disclaimer: str = "仅供参考,不构成投资建议"

    @field_validator("dimensions")
    @classmethod
    def _unique_dimension_keys(cls, dims: list[Dimension]) -> list[Dimension]:
        """Each of the 6 axes may appear at most once — duplicates are a bug."""
        seen: set[str] = set()
        for d in dims:
            key = d.key.value if isinstance(d.key, DimensionKey) else str(d.key)
            if key in seen:
                raise ValueError(f"duplicate dimension key: {key}")
            seen.add(key)
        return dims

    @field_validator("evidence_refs")
    @classmethod
    def _dedup_evidence_refs(cls, refs: list[str]) -> list[str]:
        # Preserve order but drop duplicates
        seen: set[str] = set()
        out: list[str] = []
        for r in refs:
            if r and r not in seen:
                seen.add(r)
                out.append(r)
        return out

    def collect_evidence_refs(self) -> list[str]:
        """Union of evidence_refs field + per-dimension evidence_ref values."""
        refs: list[str] = list(self.evidence_refs)
        for d in self.dimensions:
            if d.evidence_ref and d.evidence_ref not in refs:
                refs.append(d.evidence_ref)
        return refs


class DecisionCardEnvelope(BaseModel):
    """What the /chat endpoint returns for a card, plus a store id."""
    stored_id: int
    card: DecisionCard


# ── JSON Schema for tool input ────────────────────────────────────────────

def build_emit_decision_card_schema() -> dict:
    """Return the JSON Schema used as the input_schema of the
    `emit_decision_card` tool. We take Pydantic's output and strip the pieces
    that some LLMs choke on (e.g. `$defs` with anyOf around enums)."""
    schema = DecisionCard.model_json_schema()
    # Ensure required fields are always exactly what we want the model to fill
    schema.setdefault("required", ["decision_id", "agent", "type", "target", "action"])
    return schema
