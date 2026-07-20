"""Runs one conversation turn end-to-end, writing messages as it goes."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Iterable, Mapping, Protocol

from pydantic import BaseModel

from app.trading_room.conversation.chair import (
    ChairError, ChairSummary, ConversationChair,
)
from app.trading_room.conversation.router import ConversationRouter, RouterError
from app.trading_room.conversation.schemas import (
    AmountSuggestion, MessagePayload, RouterDecision, TurnRequest,
)
from app.trading_room.context import TradingContextSnapshot
from app.trading_room.schemas import (
    ActionClass, SpecialistState, TargetAllocation,
)
from app.trading_room.specialists.base import SpecialistRunResult
from app.trading_room.store import TradingRoomStore


logger = logging.getLogger(__name__)


class _SpecialistLike(Protocol):
    async def run_round_one(
        self, *, context_snapshot: dict[str, Any], context_hash: str,
        other_memos: list[dict[str, Any]] | None = None,
    ) -> SpecialistRunResult: ...


class _AmountStrategyLike(Protocol):
    def suggest(self, **kwargs: Any) -> AmountSuggestion | None: ...


class ConversationOrchestrator:
    def __init__(
        self,
        *,
        router: ConversationRouter | Any,
        specialists: Mapping[str, _SpecialistLike],
        chair: ConversationChair | Any,
        amount_strategy: _AmountStrategyLike,
    ) -> None:
        self._router = router
        self._specialists = dict(specialists)
        self._chair = chair
        self._amount_strategy = amount_strategy

    async def run_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        request: TurnRequest,
        positions: list[dict[str, str]],
        context_snapshot: TradingContextSnapshot,
        target_allocations: Iterable[TargetAllocation],
        store: TradingRoomStore,
    ) -> None:
        # 1) Route
        try:
            decision = await self._router.route(
                text=request.text, positions=positions, preset_id=request.preset_id,
            )
        except RouterError as exc:
            await _emit(store, session_id, "system", "error",
                       {"turn_id": turn_id, "stage": "router", "detail": str(exc)})
            return
        await _emit(store, session_id, "system", "routing",
                   {"turn_id": turn_id, **decision.model_dump(mode="json")})

        # 2) Clarification short-circuit
        if decision.ambiguities:
            await _emit(store, session_id, "system", "clarification",
                       {"turn_id": turn_id, "ambiguities": [
                           a.model_dump(mode="json") for a in decision.ambiguities
                       ]})
            return

        if not decision.participants:
            await _emit(store, session_id, "system", "error",
                       {"turn_id": turn_id, "detail": "no participants selected"})
            return

        # 3) Run specialists concurrently, emit as each finishes
        snapshot_payload = context_snapshot.model_dump(mode="json")

        async def _run(role: str) -> tuple[str, SpecialistRunResult]:
            runner = self._specialists.get(role)
            if runner is None:
                return role, SpecialistRunResult(
                    role=role, state=SpecialistState.UNAVAILABLE, memo=None,
                    attempts=0, context_hash=context_snapshot.context_hash,
                    model="", skill_versions={}, error="specialist_not_configured",
                )
            return role, await runner.run_round_one(
                context_snapshot=snapshot_payload,
                context_hash=context_snapshot.context_hash,
            )

        specialist_results: list[dict[str, Any]] = []
        tasks = [asyncio.create_task(_run(role)) for role in decision.participants]
        for task in asyncio.as_completed(tasks):
            role, result = await task
            memo_payload = (
                result.memo.model_dump(mode="json") if isinstance(result.memo, BaseModel)
                else None
            )
            entry = {"role": role, "state": result.state.value, "memo": memo_payload,
                     "error": result.error}
            specialist_results.append(entry)
            await _emit(store, session_id, role, "specialist_memo",
                       {"turn_id": turn_id, **entry})

        # 4) Amount suggestions (deterministic, no LLM)
        amounts = self._compute_amounts(
            specialist_results=specialist_results,
            fund_codes=[f.code for f in decision.resolved_funds],
            positions=context_snapshot.positions,
            target_allocations=list(target_allocations),
        )
        for amount in amounts:
            await _emit(store, session_id, "system", "amount_suggestion",
                       {"turn_id": turn_id, **amount.model_dump(mode="json")})

        # 5) Chair summary
        try:
            summary = await self._chair.synthesize(
                question=request.text or "",
                specialist_results=specialist_results,
                amounts=amounts,
                context_meta={
                    "data_mode": context_snapshot.data_mode,
                    "blockers": list(context_snapshot.blockers),
                },
            )
        except ChairError as exc:
            await _emit(store, session_id, "system", "error",
                       {"turn_id": turn_id, "stage": "chair", "detail": str(exc)})
            return

        await _emit(store, session_id, "chair", "chair_summary", {
            "turn_id": turn_id,
            "text": summary.text,
            "data_caveats": summary.data_caveats,
            "referenced_amount": (
                summary.referenced_amount.model_dump(mode="json")
                if summary.referenced_amount else None
            ),
        })

    def _compute_amounts(
        self,
        *,
        specialist_results: list[dict[str, Any]],
        fund_codes: list[str],
        positions: list[dict[str, Any]],
        target_allocations: list[TargetAllocation],
    ) -> list[AmountSuggestion]:
        results: list[AmountSuggestion] = []
        buy_score = 0
        sell_wanted = False
        for entry in specialist_results:
            memo = entry.get("memo") or {}
            if entry["role"] == "buy" and isinstance(memo, dict):
                buy_score = int(memo.get("score") or 0)
            if entry["role"] == "sell_protection" and isinstance(memo, dict):
                # 只要 sell_protection 输出了非 WATCH/NO_ACTION 就认为想减仓
                sell_wanted = memo.get("action_class") in {
                    ActionClass.CONDITIONAL.value, ActionClass.IMMEDIATE.value,
                }

        for code in fund_codes:
            if buy_score >= 65:
                s = self._amount_strategy.suggest(
                    action="buy", fund_code=code, positions=positions,
                    target_allocations=target_allocations, score=buy_score,
                )
                if s is not None:
                    results.append(s)
            if sell_wanted:
                s = self._amount_strategy.suggest(
                    action="sell", fund_code=code, positions=positions,
                    target_allocations=target_allocations, score=0,
                )
                if s is not None:
                    results.append(s)
        return results


async def _emit(
    store: TradingRoomStore, session_id: str,
    sender_role: str, kind: str, payload: dict[str, Any],
) -> None:
    envelope = MessagePayload(
        turn_id=str(payload.get("turn_id") or ""), kind=kind, payload=payload,
    )
    content = _human_readable(kind, payload)
    await store.add_message(
        session_id, sender_role=sender_role, content=content,
        payload=envelope.model_dump(mode="json"),
    )


def _human_readable(kind: str, payload: dict[str, Any]) -> str:
    if kind == "routing":
        parts = payload.get("participants") or []
        return f"本次参与: {', '.join(parts) or '（无）'}"
    if kind == "clarification":
        return "需要澄清基金指代"
    if kind == "chair_summary":
        return str(payload.get("text") or "")
    if kind == "specialist_memo":
        memo = payload.get("memo") or {}
        return str(memo.get("summary") or payload.get("role") or "")
    if kind == "amount_suggestion":
        return (
            f"{payload.get('action')} {payload.get('fund_code')} "
            f"{payload.get('minimum')}-{payload.get('maximum')} {payload.get('currency')}"
        )
    if kind == "error":
        return f"错误: {payload.get('detail') or ''}"
    return kind
