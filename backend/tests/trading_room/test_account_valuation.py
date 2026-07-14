"""Account valuation snapshot and recent peak tests."""

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.trading_room.account_valuation import AccountValuationService


NOW = datetime(2026, 7, 14, 14, 30, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def service():
    import app.models  # noqa: F401

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield AccountValuationService(session)
    await engine.dispose()


@pytest.mark.asyncio
async def test_confirmed_snapshot_in_peak(service):
    await service.record_confirmed(
        session_id="s1", holdings_value=80_000, cash=20_000,
        captured_at=NOW, confidence="HIGH",
    )
    await service.record_unconfirmed(
        session_id="s2", holdings_value=120_000, captured_at=NOW,
    )

    assert await service.recent_peak(as_of=NOW) == 100_000


@pytest.mark.asyncio
async def test_no_history_returns_none(service):
    assert await service.recent_peak(as_of=NOW) is None
