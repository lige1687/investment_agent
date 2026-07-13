"""Two-round discussion orchestration with deterministic decision boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

from app.trading_room.context import TradingContextSnapshot
from app.trading_room.execution_preflight import TradeStatusSnapshot
from app.trading_room.guard import LightTradeGuard
from app.trading_room.policy import TradingPolicy
from app.trading_room.schemas import ActionClass, DecisionRange, SpecialistState
from app.trading_room.schemas import TradeAvailability
from app.trading_room.specialists.base import SpecialistRunResult, SpecialistRunner
from app.trading_room.specialists.roles import ChairMemo, RecorderMemo, SkepticMemo


# Account risk is deliberately first. Batch planning and batch-aware sell
# execution are outside this MVP because the user has no such policy.
ROUND_ONE_ROUTE = (
    "portfolio_risk",
    "market_regime",
    "theme_fund",
    "buy",
    "sell_protection",
)


class BuyGuardInputs(BaseModel):
    model_config = ConfigDict(frozen=True)

    consumed_purchase_today: float = Field(ge=0)
    account_equity: float = Field(gt=0)
    current_allocation_pct: float = Field(ge=0)
    target_allocation_pct: float = Field(gt=0, le=1)
    available_cash: float = Field(ge=0)
    pending_buy_amount: float = Field(ge=0)


class GuardedDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_class: ActionClass
    suggested_range: DecisionRange
    guarded_range: DecisionRange | None
    immediately_executable: bool
    reasons: tuple[str, ...] = ()
    applied_caps: tuple[str, ...] = ()


@dataclass(frozen=True)
class TradingDiscussionResult:
    context_hash: str
    round_one: dict[str, SpecialistRunResult]
    conflicts: tuple[dict[str, Any], ...]
    round_two: dict[str, SpecialistRunResult]


class TradingRoomOrchestrator:
    def __init__(self, *, runners: Mapping[str, SpecialistRunner]):
        self._runners = dict(runners)

    async def discuss(self, context: TradingContextSnapshot) -> TradingDiscussionResult:
        snapshot_payload = context.model_dump(mode="json")
        round_one: dict[str, SpecialistRunResult] = {}
        for role in ROUND_ONE_ROUTE:
            runner = self._runners.get(role)
            if runner is None:
                round_one[role] = _missing_role(role, context.context_hash)
                continue
            # Every role receives the identical snapshot and hash, never another
            # first-round memo. Sequential execution does not change independence.
            round_one[role] = await runner.run_round_one(
                context_snapshot=snapshot_payload,
                context_hash=context.context_hash,
            )

        conflicts = _extract_conflicts(round_one)
        claims = [
            {
                "role": role,
                "memo": result.memo.model_dump(mode="json") if result.memo else None,
                "state": result.state.value,
            }
            for role, result in round_one.items()
        ]
        round_two: dict[str, SpecialistRunResult] = {}
        skeptic = self._runners.get("skeptic")
        if skeptic is not None:
            skeptic_result = await skeptic.run_round_two(
                conflict_payload={"conflicts": conflicts, "claims_for_review": claims},
                context_hash=context.context_hash,
            )
            round_two["skeptic"] = skeptic_result
            if isinstance(skeptic_result.memo, SkepticMemo):
                for index, finding in enumerate(skeptic_result.memo.findings):
                    conflicts.append(
                        {
                            "id": f"skeptic-{index + 1}",
                            "type": finding.issue_type,
                            "roles": ["skeptic"],
                            "detail": finding.description,
                            "evidence_refs": [finding.evidence_ref] if finding.evidence_ref else [],
                            "missing_field": finding.missing_field,
                        }
                    )

        return TradingDiscussionResult(
            context_hash=context.context_hash,
            round_one=round_one,
            conflicts=tuple(conflicts),
            round_two=round_two,
        )


class DecisionEngine:
    @staticmethod
    def classify_buy(
        *, score: int, policy: TradingPolicy, has_veto: bool
    ) -> ActionClass:
        if score >= policy.buy_obvious_threshold:
            return ActionClass.CONDITIONAL if has_veto else ActionClass.IMMEDIATE
        if score >= policy.conditional_buy_min:
            return ActionClass.CONDITIONAL
        return ActionClass.WATCH

    @staticmethod
    def apply_buy_guard(
        *,
        classified_action: ActionClass,
        suggested: DecisionRange,
        preflight: TradeStatusSnapshot,
        guard_inputs: BuyGuardInputs,
    ) -> GuardedDecision:
        if preflight.manager_status is TradeAvailability.UNKNOWN:
            return GuardedDecision(
                action_class=_more_restrictive(
                    classified_action, ActionClass.CONDITIONAL
                ),
                suggested_range=suggested,
                guarded_range=None,
                immediately_executable=False,
                reasons=("preflight_unknown",),
            )
        guarded = LightTradeGuard.guard_buy(
            suggested=suggested,
            preflight=preflight,
            consumed_purchase_today=guard_inputs.consumed_purchase_today,
            account_equity=guard_inputs.account_equity,
            current_allocation_pct=guard_inputs.current_allocation_pct,
            target_allocation_pct=guard_inputs.target_allocation_pct,
            available_cash=guard_inputs.available_cash,
            pending_buy_amount=guard_inputs.pending_buy_amount,
        )
        if guarded.guarded is None:
            action = ActionClass.NO_ACTION
        else:
            action = _more_restrictive(classified_action, guarded.maximum_action_class)
        return GuardedDecision(
            action_class=action,
            suggested_range=suggested,
            guarded_range=guarded.guarded,
            immediately_executable=(
                action is ActionClass.IMMEDIATE and guarded.immediately_executable
            ),
            reasons=guarded.reasons,
            applied_caps=guarded.applied_caps,
        )


_ACTION_RANK = {
    ActionClass.NO_ACTION: 0,
    ActionClass.WATCH: 1,
    ActionClass.CONDITIONAL: 2,
    ActionClass.IMMEDIATE: 3,
}


def _more_restrictive(left: ActionClass, right: ActionClass) -> ActionClass:
    return left if _ACTION_RANK[left] <= _ACTION_RANK[right] else right


def validate_recorder_memo(
    memo: RecorderMemo, *, source_memos: Mapping[str, BaseModel]
) -> bool:
    action_sources = [
        source.action_class
        for source in source_memos.values()
        if hasattr(source, "action_class")
    ]
    if not action_sources:
        return memo.action_class in {ActionClass.WATCH, ActionClass.NO_ACTION}
    maximum_source_action = max(action_sources, key=lambda action: _ACTION_RANK[action])
    if _ACTION_RANK[memo.action_class] > _ACTION_RANK[maximum_source_action]:
        return False

    source_ranges = [
        value
        for source in source_memos.values()
        for value in [getattr(source, "suggested_range", None)]
        if value is not None
    ]
    if memo.proposed_range is not None:
        if not source_ranges:
            return False
        maximum = max(item.maximum for item in source_ranges)
        minimum = min(item.minimum for item in source_ranges)
        if memo.proposed_range.minimum < minimum or memo.proposed_range.maximum > maximum:
            return False
    return True


def validate_chair_memo(
    memo: ChairMemo,
    *,
    allowed_action: ActionClass,
    guarded_range: DecisionRange | None,
) -> bool:
    if _ACTION_RANK[memo.action_class] > _ACTION_RANK[allowed_action]:
        return False
    if memo.guarded_range is None:
        return True
    if guarded_range is None:
        return False
    return (
        memo.guarded_range.minimum >= guarded_range.minimum
        and memo.guarded_range.maximum <= guarded_range.maximum
    )


def _extract_conflicts(
    results: Mapping[str, SpecialistRunResult],
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for role, result in results.items():
        if result.state is SpecialistState.UNAVAILABLE:
            conflicts.append(
                {
                    "id": f"unavailable-{role}",
                    "type": "specialist_unavailable",
                    "roles": [role],
                    "detail": result.error or "unavailable",
                    "evidence_refs": [],
                }
            )

    action_roles = {
        role: result.memo.action_class
        for role, result in results.items()
        if result.memo is not None and hasattr(result.memo, "action_class")
    }
    if len(set(action_roles.values())) > 1:
        conflicts.append(
            {
                "id": "action-class-disagreement",
                "type": "action_class_disagreement",
                "roles": list(action_roles),
                "detail": ", ".join(
                    f"{role}={action.value}" for role, action in action_roles.items()
                ),
                "evidence_refs": [],
            }
        )

    risk = results.get("portfolio_risk")
    if risk and risk.memo is not None and getattr(risk.memo, "new_buy_allowed", True) is False:
        conflicts.append(
            {
                "id": "account-risk-veto",
                "type": "risk_veto",
                "roles": ["portfolio_risk", "buy"],
                "detail": "account risk blocks new buys",
                "evidence_refs": list(getattr(risk.memo, "evidence_refs", [])),
            }
        )
    return conflicts


def _missing_role(role: str, context_hash: str) -> SpecialistRunResult:
    return SpecialistRunResult(
        role=role,
        state=SpecialistState.UNAVAILABLE,
        memo=None,
        attempts=0,
        context_hash=context_hash,
        model="",
        skill_versions={},
        error="specialist_not_configured",
    )
