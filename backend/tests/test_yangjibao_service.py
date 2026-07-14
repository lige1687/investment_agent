"""Yangjibao service sync-time and portfolio tests."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base


NOW = datetime(2026, 7, 14, 14, 30, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def db_session():
    import app.models  # noqa: F401

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_local_portfolio_returns_synced_at(db_session, monkeypatch):
    from app.services.yangjibao_service import YangjibaoService

    # Mock PortfolioSync so it doesn't try an actual sync.
    monkeypatch.setattr(
        "app.services.yangjibao_service.PortfolioSync",
        lambda db: AsyncMock(),
    )

    service = YangjibaoService(db_session)
    portfolio = await service.get_local_portfolio()
    assert portfolio["connected"] is False
    assert portfolio["total_value"] == 0
    assert "synced_at" in portfolio
