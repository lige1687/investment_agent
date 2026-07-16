"""Portfolio valuation service tests.

Covers the stale-fallback contract: live data when the Yangjibao token is
valid, DB-cached positions (stale=True) when it is not or the API errors.
Never hits the real Yangjibao API - get_all_holdings is always monkeypatched.
"""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.position import Position
from app.models.fund import FundProfile
from app.models.yangjibao import YangjibaoToken
from app.services.portfolio_valuation_service import PortfolioValuationService
from app.yangjibao.portfolio import PortfolioSync

SAMPLE_HOLDINGS = [
    {
        "code": "001055",
        "short_name": "科技创新基金",
        "hold_share": "1000",
        "hold_cost": "1.5000",
        "money": "1600",
        "nv_info": {
            "dwjz": "1.5000",
            "gsz": "1.6000",
            "gszzl": "2.55",
        },
    },
    {
        "code": "159913",
        "short_name": "纳指100ETF",
        "hold_share": "500",
        "hold_cost": "1.2000",
        "money": "0",
        "nv_info": {
            "dwjz": "1.2500",
            "gsz": "1.3000",
            "gszzl": "-1.20",
        },
    },
]


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


async def _seed_positions(db_session):
    """Seed DB-cached positions + fund profiles for fallback tests."""
    now = datetime.utcnow()
    db_session.add(
        Position(
            symbol="001055",
            position_type="fund",
            shares=1000,
            avg_cost=1.5,
            current_price=1.6,
            market_value=1600,
            cost_basis=1500,
            unrealized_pnl=100,
            unrealized_pnl_pct=6.67,
            estimated_change_pct=2.55,
            estimated_nav=1.6,
            estimated_at=now,
            source="yangjibao",
        )
    )
    db_session.add(
        Position(
            symbol="159913",
            position_type="etf",
            shares=500,
            avg_cost=1.2,
            current_price=1.3,
            market_value=650,
            cost_basis=600,
            unrealized_pnl=50,
            unrealized_pnl_pct=8.33,
            estimated_change_pct=-1.20,
            estimated_nav=1.3,
            estimated_at=now,
            source="yangjibao",
        )
    )
    db_session.add(FundProfile(code="001055", name="科技创新基金"))
    db_session.add(FundProfile(code="159913", name="纳指100ETF"))
    await db_session.flush()


# ── Test 1: no token -> DB fallback, stale=True ──


@pytest.mark.asyncio
async def test_no_token_falls_back_to_db(db_session):
    await _seed_positions(db_session)

    service = PortfolioValuationService(db_session)
    rows = await service.get_live_valuation()

    assert len(rows) == 2
    by_symbol = {r["symbol"]: r for r in rows}
    assert by_symbol["001055"]["stale"] is True
    assert by_symbol["001055"]["today_estimated_pct"] == 2.55
    assert by_symbol["001055"]["name"] == "科技创新基金"
    assert by_symbol["159913"]["stale"] is True
    assert by_symbol["159913"]["today_estimated_pct"] == -1.20
    assert by_symbol["159913"]["name"] == "纳指100ETF"
    # estimated_at should be an ISO string from DB
    assert by_symbol["001055"]["estimated_at"] is not None


# ── Test 2: token + mocked holdings -> live, stale=False ──


@pytest.mark.asyncio
async def test_live_valuation_with_token(db_session, monkeypatch):
    db_session.add(YangjibaoToken(access_token="valid-token"))
    await db_session.flush()

    monkeypatch.setattr(
        "app.yangjibao.client.YangjibaoClient.get_all_holdings",
        AsyncMock(return_value=SAMPLE_HOLDINGS),
    )

    service = PortfolioValuationService(db_session)
    rows = await service.get_live_valuation()

    assert len(rows) == 2
    by_symbol = {r["symbol"]: r for r in rows}
    assert by_symbol["001055"]["stale"] is False
    assert by_symbol["001055"]["today_estimated_pct"] == 2.55
    assert by_symbol["001055"]["name"] == "科技创新基金"
    assert by_symbol["001055"]["market_value"] == 1600  # money > 0
    assert by_symbol["159913"]["stale"] is False
    assert by_symbol["159913"]["today_estimated_pct"] == -1.20
    # money=0 so market_value = shares * gsz = 500 * 1.3 = 650
    assert by_symbol["159913"]["market_value"] == 650
    assert by_symbol["159913"]["estimated_at"] is not None


# ── Test 3: token but get_all_holdings raises -> DB fallback, no exception ──


@pytest.mark.asyncio
async def test_live_fetch_error_falls_back(db_session, monkeypatch):
    db_session.add(YangjibaoToken(access_token="expired-token"))
    await _seed_positions(db_session)

    monkeypatch.setattr(
        "app.yangjibao.client.YangjibaoClient.get_all_holdings",
        AsyncMock(side_effect=RuntimeError("token invalid")),
    )

    service = PortfolioValuationService(db_session)
    rows = await service.get_live_valuation()

    # No exception escaped; fell back to DB
    assert len(rows) == 2
    assert all(r["stale"] is True for r in rows)
    by_symbol = {r["symbol"]: r for r in rows}
    assert by_symbol["001055"]["today_estimated_pct"] == 2.55


# ── Test 4 (B2): sync writes estimated_* fields to upserted Position ──


@pytest.mark.asyncio
async def test_sync_writes_estimate_fields(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.yangjibao.client.YangjibaoClient.get_all_holdings",
        AsyncMock(return_value=SAMPLE_HOLDINGS),
    )

    sync = PortfolioSync(db_session)
    result = await sync.sync("test-token")

    assert result["success"] is True

    stmt = select(Position).where(Position.symbol == "001055")
    res = await db_session.execute(stmt)
    pos = res.scalar_one()
    assert pos.estimated_change_pct == 2.55
    assert pos.estimated_nav == 1.6
    assert pos.estimated_at is not None

    stmt2 = select(Position).where(Position.symbol == "159913")
    res2 = await db_session.execute(stmt2)
    etf = res2.scalar_one()
    assert etf.estimated_change_pct == -1.20
    assert etf.estimated_nav == 1.3
    assert etf.estimated_at is not None


# ── Test 5: sync update branch also writes estimate fields ──


@pytest.mark.asyncio
async def test_sync_update_branch_writes_estimate_fields(db_session, monkeypatch):
    # Pre-existing position (simulating a prior sync)
    db_session.add(
        Position(
            symbol="001055",
            position_type="fund",
            shares=800,
            avg_cost=1.4,
            source="yangjibao",
        )
    )
    await db_session.flush()

    monkeypatch.setattr(
        "app.yangjibao.client.YangjibaoClient.get_all_holdings",
        AsyncMock(return_value=SAMPLE_HOLDINGS),
    )

    sync = PortfolioSync(db_session)
    result = await sync.sync("test-token")
    assert result["success"] is True

    stmt = select(Position).where(Position.symbol == "001055")
    res = await db_session.execute(stmt)
    pos = res.scalar_one()
    # Updated fields from the new sync
    assert pos.estimated_change_pct == 2.55
    assert pos.estimated_nav == 1.6
    assert pos.estimated_at is not None
    # Shares should be updated to the new value
    assert pos.shares == 1000
