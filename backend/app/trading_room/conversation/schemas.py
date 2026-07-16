"""Pydantic contracts for the conversational trading-room layer."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

KNOWN_PARTICIPANTS = frozenset({
    "market_regime", "theme_fund", "portfolio_risk", "buy",
    "sell_protection", "skeptic",
})

MessageKind = Literal[
    "text", "routing", "specialist_memo",
    "amount_suggestion", "chair_summary", "clarification", "error",
]


class PresetId(str, Enum):
    DAILY_ACTION = "daily_action"
    DISCOVERY = "discovery"
    RISK_SCAN = "risk_scan"
    MARKET_READ = "market_read"


class TurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = None
    preset_id: PresetId | None = None

    @model_validator(mode="after")
    def _requires_input(self) -> "TurnRequest":
        if not self.text and self.preset_id is None:
            raise ValueError("either text or preset_id is required")
        if self.text is not None and not self.text.strip():
            raise ValueError("text must be non-empty")
        return self


class ResolvedFund(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    matched_from: str = Field(min_length=1)


class Ambiguity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hint: str = Field(min_length=1)
    candidates: list[ResolvedFund] = Field(default_factory=list)


class RouterDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolved_funds: list[ResolvedFund] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    participants: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def _known_participants(self) -> "RouterDecision":
        unknown = [p for p in self.participants if p not in KNOWN_PARTICIPANTS]
        if unknown:
            raise ValueError(f"unknown participants: {unknown}")
        return self


class AmountSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["buy", "sell"]
    fund_code: str = Field(min_length=1)
    minimum: float = Field(ge=0)
    maximum: float = Field(ge=0)
    currency: str = "CNY"
    basis: str = Field(min_length=1)
    caveats: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _range_ordered(self) -> "AmountSuggestion":
        if self.maximum < self.minimum:
            raise ValueError("maximum must be >= minimum")
        return self


class MessagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: str = Field(min_length=1)
    kind: MessageKind
    payload: dict[str, Any] = Field(default_factory=dict)
