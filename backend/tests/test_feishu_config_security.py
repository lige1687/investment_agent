"""Security regression tests for Feishu webhook configuration."""

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.feishu import FeishuConfigUpdate, get_config, update_config
from app.database import Base
from app.feishu.bot import feishu_bot
from app.models.feishu import FeishuConfig


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
async def test_get_config_returns_only_masked_webhook_hint(db_session):
    secret = "https://open.feishu.cn/open-apis/bot/v2/hook/secret-token-abcd"
    db_session.add(FeishuConfig(webhook_url=secret))
    await db_session.flush()
    previous = feishu_bot._webhook
    feishu_bot._webhook = secret
    try:
        payload = await get_config(db_session)
    finally:
        feishu_bot._webhook = previous

    assert payload["configured"] is True
    assert "webhook_url" not in payload
    assert payload["webhook_hint"].startswith("https://")
    assert payload["webhook_hint"].endswith("abcd")
    assert secret not in str(payload)


@pytest.mark.asyncio
async def test_blank_update_preserves_existing_webhook(db_session):
    secret = "https://open.feishu.cn/open-apis/bot/v2/hook/keep-this-abcd"
    db_session.add(FeishuConfig(webhook_url=secret))
    await db_session.flush()
    previous = feishu_bot._webhook
    feishu_bot._webhook = secret
    try:
        payload = await update_config(FeishuConfigUpdate(webhook_url=""), db_session)
        result = await db_session.execute(
            select(FeishuConfig).order_by(FeishuConfig.id.desc()).limit(1)
        )
        latest = result.scalar_one()
    finally:
        feishu_bot._webhook = previous

    assert latest.webhook_url == secret
    assert payload == {"ok": True, "configured": True}
    assert secret not in str(payload)

