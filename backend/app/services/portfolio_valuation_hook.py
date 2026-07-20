"""After a successful Yangjibao sync, record an account-valuation snapshot.

Solves the `peak_equity is null` problem: with the manual funding-confirmation
flow removed from the conversation path, the snapshot table would otherwise
stay empty forever. Every real sync writes a HIGH-confidence row so drawdown
math has data to work with.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trading_room import AccountValuationSnapshotRecord
from app.services.yangjibao_service import YangjibaoService
from app.trading_room.account_valuation import AccountValuationService


async def record_synced_valuation(
    db: AsyncSession,
    *,
    session_id_prefix: str = "yangjibao-sync",
) -> AccountValuationSnapshotRecord | None:
    portfolio = await YangjibaoService(db).get_local_portfolio()
    holdings_value = float(portfolio.get("total_value") or 0)
    if holdings_value <= 0:
        return None

    now = datetime.now(timezone.utc)
    # Idempotency window: 60 s
    cutoff = now - timedelta(seconds=60)
    naive_cutoff = cutoff.replace(tzinfo=None)
    existing = (await db.execute(
        select(AccountValuationSnapshotRecord)
        .where(AccountValuationSnapshotRecord.captured_at >= naive_cutoff)
        .where(AccountValuationSnapshotRecord.session_id.like(f"{session_id_prefix}-%"))
    )).scalars().first()
    if existing is not None:
        return existing

    session_id = f"{session_id_prefix}-{int(now.timestamp())}"
    return await AccountValuationService(db).record_confirmed(
        session_id=session_id,
        holdings_value=holdings_value,
        cash=0.0,           # 讨论室按持仓市值衡量回撤，现金不计入
        captured_at=now,
        confidence="HIGH",
    )
