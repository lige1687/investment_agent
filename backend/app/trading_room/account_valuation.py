"""Account valuation snapshots and recent peak calculation."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trading_room import AccountValuationSnapshotRecord


class AccountValuationService:
    """Stores account-valuation snapshots and queries recent peaks."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def record_confirmed(
        self,
        *,
        session_id: str,
        holdings_value: float,
        cash: float,
        captured_at: datetime,
        confidence: str = "HIGH",
    ) -> AccountValuationSnapshotRecord:
        row = AccountValuationSnapshotRecord(
            session_id=session_id,
            holdings_value=holdings_value,
            cash=cash,
            equity=holdings_value + cash,
            confidence=confidence,
            captured_at=captured_at.replace(tzinfo=None),
        )
        self._db.add(row)
        await self._db.flush()
        return row

    async def record_unconfirmed(
        self,
        *,
        session_id: str,
        holdings_value: float,
        captured_at: datetime,
    ) -> AccountValuationSnapshotRecord:
        row = AccountValuationSnapshotRecord(
            session_id=session_id,
            holdings_value=holdings_value,
            cash=None,
            equity=None,
            confidence="UNKNOWN",
            captured_at=captured_at.replace(tzinfo=None),
        )
        self._db.add(row)
        await self._db.flush()
        return row

    async def recent_peak(
        self,
        *,
        as_of: datetime,
        lookback_days: int = 180,
    ) -> float | None:
        cutoff = as_of.replace(tzinfo=None) - timedelta(days=lookback_days)
        result = await self._db.execute(
            select(func.max(AccountValuationSnapshotRecord.equity))
            .where(
                AccountValuationSnapshotRecord.captured_at >= cutoff,
                AccountValuationSnapshotRecord.captured_at <= as_of.replace(tzinfo=None),
                AccountValuationSnapshotRecord.confidence.in_(["HIGH", "MEDIUM"]),
                AccountValuationSnapshotRecord.equity.isnot(None),
            )
        )
        return result.scalar_one_or_none()
