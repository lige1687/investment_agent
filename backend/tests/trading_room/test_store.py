"""Persistence contracts for replayable daily trading-room sessions."""

import json

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.trading_room import ImmutableTradingRecordError
from app.trading_room.policy import import_policy_template
from app.trading_room.schemas import TargetAllocation
from app.trading_room.store import TradingRoomStore


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


def _policy():
    return import_policy_template(
        "mid-term-theme-v1",
        target_allocations=[
            TargetAllocation(scope="theme", key="通信", target_pct=0.25),
        ],
    )


@pytest.mark.asyncio
async def test_store_persists_a_replayable_session(db_session):
    store = TradingRoomStore(db_session)
    policy = _policy()
    await store.save_policy(policy)
    session = await store.create_session(
        policy_version_id=policy.version_id,
        context_snapshot={"as_of": "2026-07-13T14:30:00+08:00", "cash": 50_000},
    )

    await store.add_memo(
        session.id,
        role="risk_agent",
        state="completed",
        payload={"account_drawdown_pct": 2.1, "new_buy_allowed": True},
        skill_versions={"batch-trading-position-risk": "sha256:abc"},
    )
    await store.add_message(
        session.id,
        sender_role="chair",
        content="通信维持观察，等待确认。",
        payload={"action_class": "WATCH"},
    )
    await store.add_policy_proposal(
        session.id,
        field="target_allocations.通信",
        proposed_value=0.30,
        reason="用户希望提高通信中线目标仓位",
    )
    await store.save_exposure_snapshot(
        session.id,
        fund_code="001513",
        payload={"theme": "信息产业", "confidence": "MEDIUM"},
    )
    await store.save_trade_status_snapshot(
        session.id,
        fund_code="001513",
        share_class="A",
        channel="支付宝",
        payload={"availability": "LIMITED", "daily_limit": 10_000},
    )

    replay = await store.get_session(session.id)
    assert replay is not None
    assert json.loads(replay.context_json)["cash"] == 50_000
    assert len(replay.specialist_memos) == 1
    assert json.loads(replay.specialist_memos[0].skill_versions_json) == {
        "batch-trading-position-risk": "sha256:abc"
    }
    assert len(replay.messages) == 1
    assert len(replay.policy_proposals) == 1
    assert len(replay.exposure_snapshots) == 1
    assert len(replay.trade_status_snapshots) == 1


@pytest.mark.asyncio
async def test_policy_payload_is_immutable_after_creation(db_session):
    store = TradingRoomStore(db_session)
    policy = _policy()
    row = await store.save_policy(policy)
    row.policy_json = "{}"

    with pytest.raises(ImmutableTradingRecordError, match="policy snapshot"):
        await db_session.flush()


@pytest.mark.asyncio
async def test_session_context_is_immutable_while_feedback_can_change(db_session):
    store = TradingRoomStore(db_session)
    policy = _policy()
    await store.save_policy(policy)
    session = await store.create_session(
        policy_version_id=policy.version_id,
        context_snapshot={"cash": 50_000},
    )
    original_context = session.context_json

    updated = await store.record_feedback(
        session.id,
        state="partial",
        selected_amount=2_000,
        note="只执行建议区间的一部分",
    )

    assert updated.feedback_state == "partial"
    assert updated.selected_amount == 2_000
    assert updated.feedback_note == "只执行建议区间的一部分"
    assert updated.context_json == original_context

    updated.context_json = json.dumps({"cash": 0})
    with pytest.raises(ImmutableTradingRecordError, match="session context"):
        await db_session.flush()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["accepted", "partial", "ignored", "watch"])
async def test_feedback_states_are_supported(db_session, state):
    store = TradingRoomStore(db_session)
    policy = _policy()
    await store.save_policy(policy)
    session = await store.create_session(
        policy_version_id=policy.version_id,
        context_snapshot={"cash": 1_000},
    )

    row = await store.record_feedback(session.id, state=state)
    assert row.feedback_state == state
    assert row.feedback_at is not None


@pytest.mark.asyncio
async def test_invalid_feedback_is_rejected(db_session):
    store = TradingRoomStore(db_session)
    policy = _policy()
    await store.save_policy(policy)
    session = await store.create_session(
        policy_version_id=policy.version_id,
        context_snapshot={},
    )

    with pytest.raises(ValueError, match="invalid feedback state"):
        await store.record_feedback(session.id, state="maybe")
