"""Integration test: create conversation -> ask -> poll for messages."""

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app


NOW = datetime.now(timezone.utc)


async def _fake_portfolio(_self):
    return {
        "connected": True,
        "total_value": 20_000,
        "synced_at": NOW.isoformat(),
        "positions": [{"symbol": "001513", "name": "易方达信息产业混合A",
                       "type": "fund", "market_value": 20_000}],
    }


@pytest_asyncio.fixture
async def client(monkeypatch):
    from app import models as _  # noqa: F401
    monkeypatch.setattr(
        "app.services.yangjibao_service.YangjibaoService.get_local_portfolio",
        _fake_portfolio,
    )
    monkeypatch.setattr(
        "app.llm.registry.llm_credentials_configured", lambda role=None: True,
    )
    # 把整条对话链路替换为 fake，避免真调 LLM
    from app.trading_room.conversation import orchestrator as orch_mod

    async def _fake_run_turn(self, **kwargs):
        store = kwargs["store"]
        session_id = kwargs["session_id"]
        turn_id = kwargs["turn_id"]
        await store.add_message(
            session_id, sender_role="chair", content="ok",
            payload={"turn_id": turn_id, "kind": "chair_summary",
                     "payload": {"text": "ok"}},
        )

    monkeypatch.setattr(orch_mod.ConversationOrchestrator, "run_turn", _fake_run_turn)

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    # _work 后台任务用的是 conversation.py 里 import 进来的 async_session 名字，
    # 必须把它指向测试的内存 factory，否则后台会写真实库、轮询读内存库。
    monkeypatch.setattr("app.api.v1.conversation.async_session", factory)

    async def override_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def _import_policy(client):
    return (await client.post("/api/v1/agent/trading-policy/import", json={
        "template_id": "mid-term-theme-v1",
        "target_allocations": [{"scope": "fund", "key": "001513", "target_pct": 0.3}],
    })).json()


@pytest.mark.asyncio
async def test_ask_and_poll_messages_end_to_end(client):
    await _import_policy(client)
    conv = await client.post("/api/v1/agent/trading-room/conversations")
    assert conv.status_code == 200
    conv_id = conv.json()["conversation_id"]

    ask = await client.post(
        f"/api/v1/agent/trading-room/conversations/{conv_id}/ask",
        json={"text": "信息产业那只要不要减"},
    )
    assert ask.status_code == 200
    turn_id = ask.json()["turn_id"]
    assert turn_id

    # BackgroundTasks 在 request 结束后跑；再发一个 GET 确保它已 flush
    import asyncio
    for _ in range(20):
        r = await client.get(f"/api/v1/agent/trading-room/conversations/{conv_id}/messages")
        payload = r.json()
        if any(m["payload"].get("kind") == "chair_summary" for m in payload["messages"]):
            return
        await asyncio.sleep(0.1)
    pytest.fail("chair_summary never appeared")


@pytest.mark.asyncio
async def test_ask_rejects_when_llm_not_configured(client, monkeypatch):
    await _import_policy(client)
    monkeypatch.setattr(
        "app.llm.registry.llm_credentials_configured", lambda role=None: False,
    )
    conv = await client.post("/api/v1/agent/trading-room/conversations")
    conv_id = conv.json()["conversation_id"]
    r = await client.post(
        f"/api/v1/agent/trading-room/conversations/{conv_id}/ask",
        json={"preset_id": "market_read"},
    )
    assert r.status_code == 503
