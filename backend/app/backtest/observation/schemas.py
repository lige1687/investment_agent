"""Pydantic-style data models for observation judgments."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ObservationDecision = Literal["buy", "sell", "hold"]


@dataclass(frozen=True)
class ObservationJudgment:
    """Result of judging an observation window.

    - decision: the action to take (buy/sell/hold)
    - confirmed: whether the window condition held (stood above / stayed below MA)
    - reason: human-readable explanation
    - gate: only set when decision == "hold", explains why (e.g. observation_not_confirmed)
    """

    decision: ObservationDecision
    confirmed: bool
    reason: str
    gate: str | None = None
