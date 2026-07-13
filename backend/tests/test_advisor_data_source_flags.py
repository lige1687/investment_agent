"""Regression tests for the data-source honesty pass:
   - market/sector fallbacks flag themselves as simulated
   - lookup_fund_names resolves + marks unknowns
   - system prompt mentions the new hard rules
"""
import json

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.fund import FundProfile
from app.models.position import Position
from app.services.agent_service import (
    AGENT_TOOLS, SYSTEM_PROMPT, InvestmentAgent,
)


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


# ── SYSTEM_PROMPT hard rules ─────────────────────────────────────────────

def test_system_prompt_requires_chinese_name_with_code():
    """The prompt must instruct the model to write 「中文名(代码)」 format."""
    assert "中文名" in SYSTEM_PROMPT
    assert "001513" in SYSTEM_PROMPT  # example
    assert "lookup_fund_names" in SYSTEM_PROMPT


def test_system_prompt_defines_data_source_reliability_contract():
    """simulated data must not be cited for directional calls."""
    assert "data_source" in SYSTEM_PROMPT
    assert "simulated" in SYSTEM_PROMPT
    assert "0.5" in SYSTEM_PROMPT  # confidence cap
    assert "首句" in SYSTEM_PROMPT  # forces the summary opening line


def test_system_prompt_forbids_padding_missing_dimensions():
    """The prompt must tell the model to drop dimensions it has no data for."""
    assert "只写你真的有证据支持" in SYSTEM_PROMPT
    assert "省略" in SYSTEM_PROMPT


# ── lookup_fund_names tool ───────────────────────────────────────────────

def test_lookup_fund_names_is_registered():
    names = [t["name"] for t in AGENT_TOOLS]
    assert "lookup_fund_names" in names


@pytest.mark.asyncio
async def test_lookup_fund_names_from_profile(db_session):
    db_session.add(FundProfile(code="001513", name="易方达信息产业混合A"))
    db_session.add(FundProfile(code="022184", name="富国全球科技互联网(QDII)C"))
    await db_session.flush()

    agent = InvestmentAgent(db_session, session_id="sess_x")
    raw = await agent._tool_lookup_fund_names(["001513", "022184"])
    data = json.loads(raw)
    assert data["data_source"] == "live"
    assert data["names"]["001513"] == "易方达信息产业混合A"
    assert data["names"]["022184"] == "富国全球科技互联网(QDII)C"


@pytest.mark.asyncio
async def test_lookup_fund_names_falls_back_to_position_notes(db_session):
    """When FundProfile lacks the code but Position.notes has the name."""
    db_session.add(Position(
        symbol="999999", source="yangjibao", position_type="fund",
        shares=1, avg_cost=1, current_price=1, market_value=1,
        notes="某冷门基金C",
    ))
    await db_session.flush()

    agent = InvestmentAgent(db_session, session_id="sess_y")
    data = json.loads(await agent._tool_lookup_fund_names(["999999"]))
    assert data["names"]["999999"] == "某冷门基金C"


@pytest.mark.asyncio
async def test_lookup_fund_names_marks_unknown_codes_as_null(db_session):
    """Unresolved codes come back as null so the model knows to say
    '名称未知' rather than pretending it knows."""
    agent = InvestmentAgent(db_session, session_id="sess_z")
    data = json.loads(await agent._tool_lookup_fund_names(["000000"]))
    assert data["names"]["000000"] is None
    assert "名称未知" in data["note"]


@pytest.mark.asyncio
async def test_lookup_fund_names_empty_input(db_session):
    agent = InvestmentAgent(db_session, session_id="sess_e")
    data = json.loads(await agent._tool_lookup_fund_names([]))
    assert data["names"] == {}


# ── data_source flag on market/sector fallback ───────────────────────────

@pytest.mark.asyncio
async def test_market_overview_falls_back_flagged_simulated(db_session):
    """MarketDataProvider fallback must flag the output as simulated."""
    agent = InvestmentAgent(db_session, session_id="sess_m")
    raw = await agent._tool_market_overview()
    data = json.loads(raw)
    assert data["data_source"] == "simulated"
    assert "reliability_note" in data
    # And the useful fields are still present
    assert "indices" in data
    assert "sentiment" in data


@pytest.mark.asyncio
async def test_search_sectors_fallback_flagged_simulated(db_session):
    """search_sectors falling through to MarketDataProvider must be flagged."""
    agent = InvestmentAgent(db_session, session_id="sess_s")
    raw = await agent._tool_search_sectors({"sector_name": "半导体"})
    data = json.loads(raw)
    assert data["data_source"] == "simulated"
    assert "items" in data
