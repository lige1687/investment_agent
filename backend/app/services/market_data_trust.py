"""Shared trust helpers for data that may influence trading decisions."""

import math
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings
from app.schemas.market import MarketDataMeta


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def validate_index_rows(
    rows: list[dict[str, Any]],
    *,
    max_abs_change_pct: float = 20.0,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return decision-safe index rows and identifiers rejected by validation."""

    valid: list[dict[str, Any]] = []
    rejected: list[str] = []
    for row in rows:
        code = str(row.get("code") or row.get("symbol") or "unknown")
        price = _finite_number(row.get("price", row.get("close")))
        change_pct = _finite_number(row.get("change_pct", row.get("changePct")))
        if price is None or price <= 0 or change_pct is None or abs(change_pct) > max_abs_change_pct:
            rejected.append(code)
            continue
        valid.append(row)
    return valid, rejected


def validate_quote_rows(
    rows: list[dict[str, Any]],
    *,
    max_abs_change_pct: float = 30.0,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Reject quotes whose price or percentage cannot be trusted."""

    valid: list[dict[str, Any]] = []
    rejected: list[str] = []
    for row in rows:
        symbol = str(row.get("symbol") or row.get("code") or "unknown")
        price = _finite_number(row.get("price", row.get("close")))
        change_pct = _finite_number(row.get("change_pct", row.get("changePct")))
        if price is None or price <= 0 or change_pct is None or abs(change_pct) > max_abs_change_pct:
            rejected.append(symbol)
            continue
        valid.append(row)
    return valid, rejected


def validate_sector_rows(
    rows: list[dict[str, Any]],
    *,
    max_abs_change_pct: float = 30.0,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Reject sector rows with missing or unreasonable percentage changes."""

    valid: list[dict[str, Any]] = []
    rejected: list[str] = []
    for row in rows:
        code = str(row.get("code") or row.get("sector_code") or row.get("name") or "unknown")
        change_pct = _finite_number(row.get("change_pct", row.get("changePct")))
        if change_pct is None or abs(change_pct) > max_abs_change_pct:
            rejected.append(code)
            continue
        valid.append(row)
    return valid, rejected


def market_data_meta(
    *,
    source: str,
    status: str,
    message: str | None = None,
    is_mock: bool = False,
) -> MarketDataMeta:
    """Build consistent timezone-aware provenance without exposing raw errors."""

    mode = "demo" if is_mock else settings.market_data_mode
    return MarketDataMeta(
        source=source,
        fetched_at=datetime.now(ZoneInfo(settings.timezone)),
        mode=mode,
        status=status,
        is_mock=is_mock,
        message=message,
    )
