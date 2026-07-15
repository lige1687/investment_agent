"""Immutable, hash-addressed input snapshot for one daily discussion."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.trading_room.schemas import DataConfidence


def compute_holdings_value(positions: list[dict[str, Any]]) -> float:
    return sum(
        max(0.0, float(p.get("market_value") or 0))
        for p in positions
        if isinstance(p, dict)
    )


class CriticalDataInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str = Field(min_length=1)
    source: str = Field(min_length=1)
    as_of: datetime | None
    confidence: DataConfidence
    is_mock: bool = False
    stale: bool = False


class TradingContextSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    as_of: datetime
    data_mode: Literal["live", "demo"]
    market_dates: dict[str, str]
    positions: list[dict[str, Any]]
    cash: float | None = Field(default=None, ge=0)
    holdings_value: float = Field(ge=0)
    equity: float | None = Field(default=None, gt=0)
    peak_equity: float | None = Field(default=None, gt=0)
    pending_orders: list[dict[str, Any]]
    themes: dict[str, Any]
    funds: dict[str, Any]
    policy_version_id: str
    skill_versions: dict[str, str]
    critical_inputs: tuple[CriticalDataInput, ...]
    status: Literal["complete", "incomplete"]
    formally_actionable: bool
    blockers: tuple[str, ...]
    execution_ready: bool
    execution_blockers: tuple[str, ...]
    context_hash: str


class TradingContextBuilder:
    @staticmethod
    def build(
        *,
        as_of: datetime,
        data_mode: Literal["live", "demo"],
        market_dates: dict[str, str],
        positions: list[dict[str, Any]],
        cash: float | None = None,
        equity: float | None = None,
        peak_equity: float | None = None,
        pending_orders: list[dict[str, Any]],
        themes: dict[str, Any],
        funds: dict[str, Any],
        policy_version_id: str,
        skill_versions: dict[str, str],
        critical_inputs: list[CriticalDataInput],
    ) -> TradingContextSnapshot:
        blockers: list[str] = []
        if data_mode == "demo":
            blockers.append("demo_data_mode")
        if not critical_inputs:
            blockers.append("critical_inputs_missing")
        for item in critical_inputs:
            if item.is_mock:
                blockers.append(f"critical_input_mock:{item.key}")
            if item.stale:
                blockers.append(f"critical_input_stale:{item.key}")
            if item.as_of is None:
                blockers.append(f"critical_input_missing_time:{item.key}")
            if item.confidence in {DataConfidence.LOW, DataConfidence.UNKNOWN}:
                blockers.append(f"critical_input_low_confidence:{item.key}")

        holdings_value = compute_holdings_value(positions)

        execution_blockers: list[str] = []
        if cash is None:
            execution_blockers.append("available_cash_unconfirmed")
        if peak_equity is None:
            execution_blockers.append("account_drawdown_unknown")

        base = {
            "as_of": as_of,
            "data_mode": data_mode,
            "market_dates": market_dates,
            "positions": positions,
            "cash": cash,
            "holdings_value": holdings_value,
            "equity": equity,
            "peak_equity": peak_equity,
            "pending_orders": pending_orders,
            "themes": themes,
            "funds": funds,
            "policy_version_id": policy_version_id,
            "skill_versions": skill_versions,
            "critical_inputs": tuple(critical_inputs),
            "status": "incomplete" if blockers else "complete",
            "formally_actionable": not blockers,
            "blockers": tuple(dict.fromkeys(blockers)),
            "execution_ready": not execution_blockers,
            "execution_blockers": tuple(dict.fromkeys(execution_blockers)),
        }
        canonical = json.dumps(
            _jsonable(base), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        context_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return TradingContextSnapshot(**base, context_hash=context_hash)


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value
