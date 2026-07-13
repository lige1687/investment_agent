"""Deterministic shadow session covering the user's three core themes."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.llm.schemas import LLMResponse
from app.trading_room.context import CriticalDataInput, TradingContextBuilder
from app.trading_room.execution_preflight import TradeStatusSnapshot
from app.trading_room.orchestrator import BuyGuardInputs, DecisionEngine, ROUND_ONE_ROUTE, TradingRoomOrchestrator
from app.trading_room.policy import import_policy_template
from app.trading_room.schemas import ActionClass, DataConfidence, TargetAllocation, TradeAvailability
from app.trading_room.skill_registry import SkillBundle
from app.trading_room.specialists.roles import create_specialist
from app.trading_room.store import TradingRoomStore


FIXTURE = Path(__file__).parents[1] / "fixtures" / "trading_room" / "shadow_session.json"


class FixtureClient:
    def __init__(self, payload):
        self.payload = payload
        self.model = "deepseek-v4-flash-fixture"

    async def chat(self, messages, **kwargs):
        return LLMResponse(text=json.dumps(self.payload, ensure_ascii=False), model=self.model)


class FixtureSkills:
    def load(self, name):
        return SkillBundle(
            name=name, files=("SKILL.md",), content=f"fixture constraints: {name}",
            sha256=f"fixture-hash-{name}",
        )


@pytest_asyncio.fixture
async def db_session():
    import app.models  # noqa: F401

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_three_theme_shadow_session_saves_auditable_conditional_result(db_session):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    now = datetime(2026, 7, 13, 14, 30, tzinfo=timezone.utc)
    policy = import_policy_template(
        "mid-term-theme-v1",
        target_allocations=[
            TargetAllocation(scope="theme", key="通信", target_pct=0.30),
            TargetAllocation(scope="theme", key="纳斯达克", target_pct=0.25),
            TargetAllocation(scope="theme", key="全球基金", target_pct=0.20),
        ],
    )
    context = TradingContextBuilder.build(
        as_of=now, data_mode="live", market_dates={"CN": "2026-07-13", "US": "2026-07-10"},
        positions=[{"fund_code": "001513", "market_value": 20_000}],
        cash=50_000, equity=100_000, peak_equity=102_000, pending_orders=[],
        themes=fixture["themes"], funds={"001513": {"name": "易方达信息产业混合A"}},
        policy_version_id=policy.version_id,
        skill_versions={"batch-trading-router": "fixture-hash"},
        critical_inputs=[CriticalDataInput(
            key="market_and_portfolio", source="fixture-live", as_of=now,
            confidence=DataConfidence.HIGH,
        )],
    )
    skills = FixtureSkills()
    runners = {
        role: create_specialist(
            role, client=FixtureClient(fixture["responses"][role]), skill_registry=skills
        )
        for role in (*ROUND_ONE_ROUTE, "skeptic")
    }
    discussion = await TradingRoomOrchestrator(runners=runners).discuss(context)

    store = TradingRoomStore(db_session)
    await store.save_policy(policy)
    session = await store.create_session(
        policy_version_id=policy.version_id,
        context_snapshot=context.model_dump(mode="json"),
    )
    for result in (*discussion.round_one.values(), *discussion.round_two.values()):
        await store.add_memo(
            session.id, role=result.role, state=result.state.value,
            payload=result.memo.model_dump(mode="json") if result.memo else {"error": result.error},
            skill_versions=result.skill_versions,
        )

    buy = discussion.round_one["buy"].memo
    classified = DecisionEngine.classify_buy(score=buy.score, policy=policy, has_veto=False)
    guarded = DecisionEngine.apply_buy_guard(
        classified_action=classified,
        suggested=buy.suggested_range,
        preflight=TradeStatusSnapshot(
            fund_code="001513", share_class="A", customer_scope="retail",
            manager_status=TradeAvailability.LIMITED,
            redemption_status=TradeAvailability.OPEN,
            daily_purchase_limit=10_000, queried_at=now, channel_confirmed=False,
            maximum_action_class=ActionClass.CONDITIONAL,
        ),
        guard_inputs=BuyGuardInputs(
            consumed_purchase_today=0, account_equity=100_000,
            current_allocation_pct=0.20, target_allocation_pct=0.30,
            available_cash=50_000, pending_buy_amount=0,
        ),
    )
    await store.finalize_session(session.id, decision=guarded.model_dump(mode="json"))

    replay = await store.get_session(session.id)
    assert set(fixture["themes"]) == {"通信", "纳斯达克", "全球基金"}
    assert len(replay.specialist_memos) == 6
    assert all(json.loads(item.skill_versions_json) for item in replay.specialist_memos)
    assert guarded.action_class is ActionClass.CONDITIONAL
    assert guarded.immediately_executable is False
    assert json.loads(replay.final_decision_json)["guarded_range"]["maximum"] == 5000
