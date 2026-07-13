import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base


@pytest_asyncio.fixture
async def context_session():
    import app.models  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_context_snapshot_round_trips_and_finds_related_sector(context_session):
    from app.services.agent_context_service import AgentContextService

    service = AgentContextService(context_session)
    snapshot_id = await service.save_snapshot(
        source="feishu_card",
        intent="sector_monitor",
        question="板块监控测试卡",
        context={
            "market_mood": {"state": "缩量修复"},
            "sector_evidence": [
                {
                    "name": "半导体/芯片",
                    "matched_sector": "半导体",
                    "tracking_code": "931743",
                    "data_code": "H30184.CSI",
                    "change_pct": 3.29,
                }
            ],
        },
        decision={"summary": "半导体观察，不追涨"},
        skill_calls=[{"skill": "hithink-zhishu-query", "query": "半导体 今日涨跌幅"}],
    )

    assert snapshot_id > 0

    latest = await service.find_recent_relevant_snapshot("为什么半导体有机会？")

    assert latest is not None
    assert latest.id == snapshot_id
    assert latest.context["sector_evidence"][0]["tracking_code"] == "931743"
    assert latest.decision["summary"] == "半导体观察，不追涨"
    assert latest.skill_calls[0]["skill"] == "hithink-zhishu-query"


@pytest.mark.asyncio
async def test_recent_context_prompt_is_compact_and_auditable(context_session):
    from app.services.agent_context_service import AgentContextService

    service = AgentContextService(context_session)
    await service.save_snapshot(
        source="feishu_card",
        intent="sector_monitor",
        question="板块监控测试卡",
        context={
            "market_mood": {"summary": "缩量修复：全A成交额32938亿，较昨日缩量6.94%。"},
            "sector_evidence": [
                {
                    "name": "半导体/芯片",
                    "matched_sector": "半导体",
                    "tracking_code": "931743",
                    "data_code": "H30184.CSI",
                    "change_pct": 3.29,
                    "turnover": 497_120_000_000,
                    "main_flow": None,
                    "opportunity_level": "观察",
                }
            ],
        },
        decision={"summary": "半导体进入观察榜，但主力数据缺失。"},
        skill_calls=[{"skill": "hithink-market-query"}],
    )

    block = await service.build_recent_context_block("继续说说半导体")

    assert "最近证据快照" in block
    assert "半导体/芯片" in block
    assert "跟踪代码 931743" in block
    assert "数据代码 H30184.CSI" in block
    assert "主力数据缺失" in block
    assert "hithink-market-query" in block
