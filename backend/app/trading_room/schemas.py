"""Validated contracts shared by deterministic and LLM trading-room modules."""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DataConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class TradeAvailability(str, Enum):
    OPEN = "OPEN"
    LIMITED = "LIMITED"
    SUSPENDED = "SUSPENDED"
    UNKNOWN = "UNKNOWN"


class ThemePhase(str, Enum):
    BOTTOMING = "bottoming"
    STARTUP = "startup"
    MAIN_RISE = "main_rise"
    OVERHEATED = "overheated"
    RANGE = "range"
    RETREAT = "retreat"
    TREND_BROKEN = "trend_broken"


class SpecialistState(str, Enum):
    READY = "ready"
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"


class ActionClass(str, Enum):
    IMMEDIATE = "IMMEDIATE"
    CONDITIONAL = "CONDITIONAL"
    WATCH = "WATCH"
    NO_ACTION = "NO_ACTION"


class RiskState(str, Enum):
    NORMAL = "NORMAL"
    RISK_REVIEW = "RISK_REVIEW"
    REDUCE_OR_EXIT_CANDIDATE = "REDUCE_OR_EXIT_CANDIDATE"


class TargetAllocation(BaseModel):
    model_config = ConfigDict(frozen=True)

    scope: Literal["theme", "fund"]
    key: str = Field(min_length=1)
    target_pct: float = Field(gt=0, le=1)


class EvidenceRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    evidence_id: str
    source: str
    title: str
    as_of: datetime | None = None
    url: str | None = None


class DecisionRange(BaseModel):
    model_config = ConfigDict(frozen=True)

    minimum: float = Field(ge=0)
    maximum: float = Field(ge=0)
    currency: Literal["CNY"] = "CNY"

    @model_validator(mode="after")
    def validate_order(self) -> "DecisionRange":
        if self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")
        return self


class TrendBreakPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    consecutive_closes_min: int = Field(ge=1)
    consecutive_closes_max: int = Field(ge=1)
    breakdown_magnitude_min_pct: float = Field(gt=0)
    breakdown_magnitude_max_pct: float = Field(gt=0)
    reclaim_required: bool = True
    volume_break_confirms: bool = True

    @model_validator(mode="after")
    def validate_ranges(self) -> "TrendBreakPolicy":
        if self.consecutive_closes_min > self.consecutive_closes_max:
            raise ValueError("invalid consecutive close range")
        if self.breakdown_magnitude_min_pct > self.breakdown_magnitude_max_pct:
            raise ValueError("invalid breakdown magnitude range")
        return self

