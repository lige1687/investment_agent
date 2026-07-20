import json
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.trading_room.conversation.orchestrator import ConversationOrchestrator
from app.trading_room.conversation.chair import ChairSummary
from app.trading_room.conversation.schemas import (
    AmountSuggestion, ResolvedFund, RouterDecision, TurnRequest,
)
from app.trading_room.context import TradingContextBuilder, CriticalDataInput
from app.trading_room.schemas import (
    ActionClass, DecisionRange, SpecialistState, TargetAllocation,
)
from app.trading_room.specialists.base import SpecialistRunResult
from app.trading_room.specialists.roles import BuyMemo, PortfolioRiskMemo
from app.trading_room.store import TradingRoomStore
from app.trading_room.policy import import_policy_template


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        from app import models as _  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


class FakeRouter:
    def __init__(self, decision: RouterDecision):
        self._decision = decision

    async def route(self, *, text, positions, preset_id=None):
        return self._decision


class FakeSpecialist:
    def __init__(self, result: SpecialistRunResult):
        self._result = result

    async def run_round_one(self, *, context_snapshot, context_hash, other_memos=None):
        return self._result


class FakeChair:
    def __init__(self, summary: ChairSummary):
        self._summary = summary

    async def synthesize(self, *, question, specialist_results, amounts, context_meta):
        return self._summary


class FakeStrategy:
    def __init__(self, suggestion: AmountSuggestion | None):
        self._s = suggestion

    def suggest(self, **kwargs):
        return self._s


NOW = datetime.now(timezone.utc)


def _build_context(positions, target_key="001513"):
    return TradingContextBuilder.build(
        as_of=NOW, data_mode="live",
        market_dates={"CN": NOW.date().isoformat()},
        positions=positions, cash=None, equity=None, peak_equity=None,
        pending_orders=[], themes={}, funds={},
        policy_version_id="v1", skill_versions={},
        critical_inputs=[CriticalDataInput(
            key="quotes", source="live", as_of=NOW,
            confidence="HIGH", is_mock=False, stale=False,
        )],
    )


async def _seed_policy_and_session(store):
    policy = import_policy_template(
        "mid-term-theme-v1",
        target_allocations=[
            TargetAllocation(scope="fund", key="001513", target_pct=0.30),
        ],
    )
    await store.save_policy(policy)
    context = _build_context([
        {"symbol": "001513", "name": "易方达信息产业混合A", "market_value": 20_000},
    ])
    session = await store.create_session(
        policy_version_id=policy.version_id,
        context_snapshot=context.model_dump(mode="json"),
    )
    return session, policy, context


@pytest.mark.asyncio
async def test_run_turn_writes_ordered_message_sequence(db_session):
    store = TradingRoomStore(db_session)
    session, policy, context = await _seed_policy_and_session(store)

    router = FakeRouter(RouterDecision(
        resolved_funds=[ResolvedFund(
            code="001513", name="易方达信息产业混合A", matched_from="test",
        )],
        ambiguities=[],
        participants=["portfolio_risk", "buy"],
        reason="test",
    ))
    orchestrator = ConversationOrchestrator(
        router=router,
        specialists={
            "portfolio_risk": FakeSpecialist(SpecialistRunResult(
                role="portfolio_risk", state=SpecialistState.COMPLETED,
                memo=PortfolioRiskMemo(
                    summary="风险 OK", risk_state="NORMAL",
                    new_buy_allowed=True, findings=[],
                ),
                attempts=1, context_hash=context.context_hash,
                model="fake", skill_versions={},
            )),
            "buy": FakeSpecialist(SpecialistRunResult(
                role="buy", state=SpecialistState.COMPLETED,
                memo=BuyMemo(
                    summary="分数 80", score=80,
                    action_class=ActionClass.CONDITIONAL,
                    suggested_range=DecisionRange(minimum=1000, maximum=3000, currency="CNY"),
                    triggers=["主升"], invalidations=["跌破 60 日"],
                ),
                attempts=1, context_hash=context.context_hash,
                model="fake", skill_versions={},
            )),
        },
        chair=FakeChair(ChairSummary(
            text="综合意见：可小幅加仓 1000-3000 元。",
            data_caveats=[], referenced_amount=None,
        )),
        amount_strategy=FakeStrategy(AmountSuggestion(
            action="buy", fund_code="001513",
            minimum=1000, maximum=3000, basis="缺口", caveats=[],
        )),
    )

    await orchestrator.run_turn(
        session_id=session.id,
        turn_id="t1",
        request=TurnRequest(text="能不能加点"),
        positions=[{"code": "001513", "name": "易方达信息产业混合A"}],
        context_snapshot=context,
        target_allocations=policy.target_allocations,
        store=store,
    )

    await db_session.commit()
    saved = await store.get_session(session.id)
    kinds = [json.loads(m.message_json).get("kind") for m in saved.messages]
    # 期望顺序：routing -> specialist_memo × 2 -> amount_suggestion -> chair_summary
    assert kinds[0] == "routing"
    assert kinds.count("specialist_memo") == 2
    assert "amount_suggestion" in kinds
    assert kinds[-1] == "chair_summary"


@pytest.mark.asyncio
async def test_run_turn_ambiguity_stops_after_clarification(db_session):
    store = TradingRoomStore(db_session)
    session, policy, context = await _seed_policy_and_session(store)

    router = FakeRouter(RouterDecision(
        resolved_funds=[],
        ambiguities=[{
            "hint": "A/C 份额需要澄清",
            "candidates": [
                {"code": "001513", "name": "易方达信息产业混合A", "matched_from": "信息产业"},
                {"code": "001514", "name": "易方达信息产业混合C", "matched_from": "信息产业"},
            ],
        }],
        participants=[], reason="需要澄清",
    ))
    orchestrator = ConversationOrchestrator(
        router=router, specialists={},
        chair=FakeChair(ChairSummary(text="X", data_caveats=[], referenced_amount=None)),
        amount_strategy=FakeStrategy(None),
    )

    await orchestrator.run_turn(
        session_id=session.id, turn_id="t2",
        request=TurnRequest(text="信息产业"),
        positions=[{"code": "001513", "name": "易方达信息产业混合A"}],
        context_snapshot=context,
        target_allocations=policy.target_allocations,
        store=store,
    )

    await db_session.commit()
    saved = await store.get_session(session.id)
    kinds = [json.loads(m.message_json).get("kind") for m in saved.messages]
    assert kinds == ["routing", "clarification"]  # chair 不应该出现
