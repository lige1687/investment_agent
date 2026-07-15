"""Account valuation snapshot and recent peak tests."""

from datetime import datetime, timedelta, timezone

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


@pytest.mark.asyncio
async def test_timezone_normalized_before_compare(service):
    # Recorded with a +08:00 wall clock that is the SAME instant as NOW (14:30 UTC).
    # Without UTC normalization the stored 22:30 wall clock would exceed the
    # 14:30 query upper bound and be wrongly excluded (the 8-hour skew bug).
    shanghai = timezone(timedelta(hours=8))
    captured_at = datetime(2026, 7, 14, 22, 30, tzinfo=shanghai)
    await service.record_confirmed(
        session_id="s1", holdings_value=80_000, cash=20_000,
        captured_at=captured_at, confidence="HIGH",
    )

    assert await service.recent_peak(as_of=NOW) == 100_000
