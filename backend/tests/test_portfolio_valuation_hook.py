from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.trading_room import AccountValuationSnapshotRecord
from app.services.portfolio_valuation_hook import record_synced_valuation


@pytest_asyncio.fixture
async def db_session(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        from app import models as _  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _fake_portfolio(_self):
    return {
        "connected": True,
        "total_value": 42_000.0,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "positions": [{"symbol": "001513", "name": "x", "market_value": 42_000.0}],
    }


@pytest.mark.asyncio
async def test_record_synced_valuation_writes_high_confidence_snapshot(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.services.yangjibao_service.YangjibaoService.get_local_portfolio",
        _fake_portfolio,
    )
    row = await record_synced_valuation(db_session)
    await db_session.commit()
    assert row is not None
    assert row.holdings_value == 42_000.0
    assert row.confidence == "HIGH"
    rows = (await db_session.execute(
        select(AccountValuationSnapshotRecord)
    )).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_record_synced_valuation_is_idempotent_within_a_minute(
    db_session, monkeypatch,
):
    monkeypatch.setattr(
        "app.services.yangjibao_service.YangjibaoService.get_local_portfolio",
        _fake_portfolio,
    )
    await record_synced_valuation(db_session)
    await record_synced_valuation(db_session)
    await db_session.commit()
    rows = (await db_session.execute(
        select(AccountValuationSnapshotRecord)
    )).scalars().all()
    assert len(rows) == 1
