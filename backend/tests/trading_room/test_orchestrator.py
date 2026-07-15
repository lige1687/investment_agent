"""Two-round orchestration and fail-closed decision tests."""

import asyncio
from datetime import datetime, timezone

import pytest

from app.trading_room.context import CriticalDataInput, TradingContextBuilder
from app.trading_room.execution_preflight import TradeStatusSnapshot
from app.trading_room.orchestrator import (
    ROUND_ONE_ROUTE,
    BuyGuardInputs,
    DecisionEngine,
    TradingRoomOrchestrator,
    validate_chair_memo,
    validate_recorder_memo,
)
from app.trading_room.policy import import_policy_template
from app.trading_room.schemas import (
    ActionClass,
    DataConfidence,
    DecisionRange,
    RiskState,
    SpecialistState,
    TargetAllocation,
    TradeAvailability,
)
from app.trading_room.specialists.base import SpecialistRunResult
from app.trading_room.specialists.roles import (
    BuyMemo,
    ChairMemo,
    MarketRegimeMemo,
    PortfolioRiskMemo,
    RecorderMemo,
    SellProtectionMemo,
    SkepticFinding,
    SkepticMemo,
    ThemeFundMemo,
)


NOW = datetime(2026, 7, 13, 14, 30, tzinfo=timezone.utc)


def _critical(key="quotes", **overrides):
    values = {
        "key": key,
        "source": "live-provider",
        "as_of": NOW,
        "confidence": DataConfidence.HIGH,
        "is_mock": False,
        "stale": False,
    }
    values.update(overrides)
    return CriticalDataInput(**values)


def _context(*critical_inputs, data_mode="live"):
    return TradingContextBuilder.build(
        as_of=NOW,
        data_mode=data_mode,
        market_dates={"CN": "2026-07-13", "US": "2026-07-10"},
        positions=[{"fund_code": "001513", "market_value": 20_000}],
        cash=50_000,
        equity=100_000,
        peak_equity=102_000,
        pending_orders=[],
        themes={"通信": {"phase": "startup"}},
        funds={"001513": {"nav_as_of": "2026-07-10"}},
        policy_version_id="policy-1",
        skill_versions={"batch-trading-router": "hash-1"},
        critical_inputs=list(critical_inputs or (_critical(),)),
    )


@pytest.mark.parametrize(
    "critical,data_mode,expected_blocker",
    [
        (_critical(is_mock=True), "live", "critical_input_mock:quotes"),
        (_critical(stale=True), "live", "critical_input_stale:quotes"),
        (_critical(as_of=None), "live", "critical_input_missing_time:quotes"),
        (_critical(), "demo", "demo_data_mode"),
    ],
)
def test_context_becomes_explainable_but_not_actionable_for_untrusted_inputs(
    critical, data_mode, expected_blocker
):
    snapshot = _context(critical, data_mode=data_mode)
    assert snapshot.status == "incomplete"
    assert snapshot.formally_actionable is False
    assert expected_blocker in snapshot.blockers
    assert snapshot.context_hash


def test_router_prioritizes_account_risk_and_excludes_batch_semantics():
    assert ROUND_ONE_ROUTE[0] == "portfolio_risk"
    assert "batch_planner" not in ROUND_ONE_ROUTE
    assert "sell_execution" not in ROUND_ONE_ROUTE


def _memo(role):
    common = {"summary": role, "evidence_refs": ["ev_1"]}
    if role == "portfolio_risk":
        return PortfolioRiskMemo(
            **common, risk_state=RiskState.NORMAL, new_buy_allowed=True, findings=[]
        )
    if role == "market_regime":
        return MarketRegimeMemo(
            **common, phase="startup", regime_score=80,
            buy_permission="allowed", counter_evidence=[]
        )
    if role == "theme_fund":
        return ThemeFundMemo(
            **common, fund_code="001513", theme="通信", phase="startup",
            exposure_confidence="MEDIUM", report_period_end="2026-06-30",
        )
    if role == "buy":
        return BuyMemo(
            **common, score=82, action_class=ActionClass.IMMEDIATE,
            suggested_range=DecisionRange(minimum=1_000, maximum=3_000),
            triggers=["站稳"], invalidations=["破位"],
        )
    if role == "sell_protection":
        return SellProtectionMemo(
            **common, action_class=ActionClass.WATCH,
            reason_priority="none", triggers=[]
        )
    if role == "skeptic":
        return SkepticMemo(
            **common,
            findings=[
                SkepticFinding(
                    issue_type="logic_gap", description="买卖意见不一致",
                    impact="需要澄清", evidence_ref="ev_1",
                )
            ],
        )
    raise KeyError(role)


class StubRunner:
    def __init__(self, role):
        self.role = role
        self.round_one_calls = []
        self.round_two_calls = []

    async def run_round_one(self, **kwargs):
        self.round_one_calls.append(kwargs)
        return SpecialistRunResult(
            role=self.role, state=SpecialistState.COMPLETED, memo=_memo(self.role),
            attempts=1, context_hash=kwargs["context_hash"], model="test-model",
            skill_versions={self.role: "hash"},
        )

    async def run_round_two(self, **kwargs):
        self.round_two_calls.append(kwargs)
        return SpecialistRunResult(
            role=self.role, state=SpecialistState.COMPLETED, memo=_memo(self.role),
            attempts=1, context_hash=kwargs["context_hash"], model="test-model",
            skill_versions={self.role: "hash"},
        )


@pytest.mark.asyncio
async def test_orchestrator_runs_independent_round_then_conflicts_only_round_two():
    runners = {role: StubRunner(role) for role in (*ROUND_ONE_ROUTE, "skeptic")}
    orchestrator = TradingRoomOrchestrator(runners=runners)

    result = await orchestrator.discuss(_context())

    assert list(result.round_one) == list(ROUND_ONE_ROUTE)
    assert all(len(runners[role].round_one_calls) == 1 for role in ROUND_ONE_ROUTE)
    assert all(
        "other_memos" not in runners[role].round_one_calls[0]
        for role in ROUND_ONE_ROUTE
    )
    assert runners["skeptic"].round_one_calls == []
    assert runners["skeptic"].round_two_calls
    skeptic_payload = runners["skeptic"].round_two_calls[0]["conflict_payload"]
    assert set(skeptic_payload) == {"conflicts", "claims_for_review"}
    assert "immutable_context_snapshot" not in skeptic_payload
    assert result.context_hash == _context().context_hash


class _GatedRunner(StubRunner):
    """Round-one runner whose start/finish is gated on an asyncio.Event."""

    def __init__(self, role, *, waits_on=None, sets=None):
        super().__init__(role)
        self._waits_on = waits_on
        self._sets = sets

    async def run_round_one(self, **kwargs):
        if self._waits_on is not None:
            await self._waits_on.wait()
        if self._sets is not None:
            self._sets.set()
        return await super().run_round_one(**kwargs)


@pytest.mark.asyncio
async def test_round_one_runs_concurrently():
    # portfolio_risk (first in route) blocks until market_regime (second) runs.
    # Serial execution would deadlock — portfolio_risk awaits an event that only
    # gets set when market_regime executes, which serial ordering never reaches.
    gate = asyncio.Event()
    runners = {role: StubRunner(role) for role in (*ROUND_ONE_ROUTE, "skeptic")}
    runners["portfolio_risk"] = _GatedRunner("portfolio_risk", waits_on=gate)
    runners["market_regime"] = _GatedRunner("market_regime", sets=gate)
    orchestrator = TradingRoomOrchestrator(runners=runners)

    result = await asyncio.wait_for(orchestrator.discuss(_context()), timeout=5)

    assert list(result.round_one) == list(ROUND_ONE_ROUTE)
    assert result.round_one["portfolio_risk"].state is SpecialistState.COMPLETED
    assert result.round_one["market_regime"].state is SpecialistState.COMPLETED


def _policy():
    return import_policy_template(
        "mid-term-theme-v1",
        target_allocations=[TargetAllocation(scope="theme", key="通信", target_pct=0.30)],
    )


@pytest.mark.parametrize(
    "score,has_veto,expected",
    [
        (80, False, ActionClass.IMMEDIATE),
        (95, True, ActionClass.CONDITIONAL),
        (65, False, ActionClass.CONDITIONAL),
        (64, False, ActionClass.WATCH),
    ],
)
def test_buy_thresholds_require_score_and_no_veto(score, has_veto, expected):
    assert DecisionEngine.classify_buy(score=score, policy=_policy(), has_veto=has_veto) is expected


def _preflight(*, confirmed=True, status=TradeAvailability.OPEN):
    max_action = ActionClass.IMMEDIATE
    if status is TradeAvailability.SUSPENDED:
        max_action = ActionClass.NO_ACTION
    elif status is TradeAvailability.UNKNOWN or not confirmed:
        max_action = ActionClass.CONDITIONAL
    return TradeStatusSnapshot(
        fund_code="001513", share_class="A", customer_scope="retail",
        manager_status=status, redemption_status=TradeAvailability.OPEN,
        queried_at=NOW, channel_confirmed=confirmed, maximum_action_class=max_action,
    )


def test_guard_or_preflight_failure_downgrades_immediate_result():
    inputs = BuyGuardInputs(
        consumed_purchase_today=0, account_equity=100_000,
        current_allocation_pct=0.10, target_allocation_pct=0.30,
        available_cash=20_000, pending_buy_amount=0,
    )
    conditional = DecisionEngine.apply_buy_guard(
        classified_action=ActionClass.IMMEDIATE,
        suggested=DecisionRange(minimum=1_000, maximum=3_000),
        preflight=_preflight(confirmed=False),
        guard_inputs=inputs,
    )
    blocked = DecisionEngine.apply_buy_guard(
        classified_action=ActionClass.IMMEDIATE,
        suggested=DecisionRange(minimum=1_000, maximum=3_000),
        preflight=_preflight(status=TradeAvailability.SUSPENDED),
        guard_inputs=inputs,
    )
    assert conditional.action_class is ActionClass.CONDITIONAL
    assert conditional.guarded_range == DecisionRange(minimum=1_000, maximum=3_000)
    assert blocked.action_class is ActionClass.NO_ACTION
    assert blocked.guarded_range is None


def test_recorder_cannot_invent_action_and_chair_cannot_exceed_guarded_range():
    source = _memo("buy")
    invented = RecorderMemo(
        summary="改成更激进", evidence_refs=["ev_1"],
        action_class=ActionClass.IMMEDIATE,
        proposed_range=DecisionRange(minimum=1_000, maximum=10_000),
        source_roles=["buy"],
    )
    assert validate_recorder_memo(invented, source_memos={"buy": source}) is False


def test_unknown_cash_and_peak_allow_analysis_but_not_execution():
    snapshot = TradingContextBuilder.build(
        as_of=NOW,
        data_mode="live",
        market_dates={"CN": "2026-07-14"},
        positions=[{"symbol": "001513", "market_value": 20_000}],
        cash=None,
        equity=None,
        peak_equity=None,
        pending_orders=[],
        themes={},
        funds={},
        policy_version_id="policy-ready",
        skill_versions={},
        critical_inputs=[CriticalDataInput(
            key="portfolio", source="yangjibao", as_of=NOW,
            confidence=DataConfidence.HIGH, is_mock=False, stale=False,
        )],
    )

    assert snapshot.status == "complete"
    assert snapshot.formally_actionable is True
    assert snapshot.holdings_value == 20_000
    assert snapshot.equity is None
    assert snapshot.execution_ready is False
    assert snapshot.execution_blockers == (
        "available_cash_unconfirmed", "account_drawdown_unknown",
    )


    chair = ChairMemo(
        summary="主持", evidence_refs=["ev_1"], action_class=ActionClass.IMMEDIATE,
        guarded_range=DecisionRange(minimum=1_000, maximum=3_000),
        user_summary="可以买 1000 到 3000", conditions=[],
    )
    assert validate_chair_memo(
        chair,
        allowed_action=ActionClass.CONDITIONAL,
        guarded_range=DecisionRange(minimum=1_000, maximum=2_000),
    ) is False
