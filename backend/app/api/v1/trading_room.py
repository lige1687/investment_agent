"""Daily trading-room and immutable policy APIs (manual execution only)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.llm.registry import llm_credentials_configured
from app.trading_room.context import CriticalDataInput, TradingContextBuilder
from app.trading_room.announcement_provider import (
    AnnouncementProviderError,
    IwencaiAnnouncementProvider,
)
from app.trading_room.execution_preflight import ExecutionPreflight, TradeStatusSnapshot
from app.trading_room.orchestrator import (
    ROUND_ONE_ROUTE,
    BuyGuardInputs,
    DecisionEngine,
    GuardedDecision,
    TradingRoomOrchestrator,
)
from app.trading_room.policy import (
    MID_TERM_THEME_V1,
    TradingPolicy,
    import_policy_template,
)
from app.trading_room.schemas import ActionClass, DecisionRange, TargetAllocation
from app.trading_room.skill_registry import TradingSkillRegistry
from app.trading_room.specialists.roles import create_specialist
from app.trading_room.store import TradingRoomStore


router = APIRouter(prefix="/agent", tags=["Trading Room"])


class PolicyImportRequest(BaseModel):
    template_id: str = "mid-term-theme-v1"
    target_allocations: list[TargetAllocation] = Field(default_factory=list)


class SessionCreateRequest(BaseModel):
    policy_version_id: str
    as_of: datetime
    data_mode: Literal["live", "demo"] = "live"
    market_dates: dict[str, str]
    positions: list[dict[str, Any]]
    cash: float | None = Field(default=None, ge=0)
    equity: float | None = Field(default=None, gt=0)
    peak_equity: float | None = Field(default=None, gt=0)
    pending_orders: list[dict[str, Any]] = Field(default_factory=list)
    themes: dict[str, Any] = Field(default_factory=dict)
    funds: dict[str, Any] = Field(default_factory=dict)
    skill_versions: dict[str, str] = Field(default_factory=dict)
    critical_inputs: list[CriticalDataInput]
    exposure_snapshots: list[dict[str, Any]] = Field(default_factory=list)
    trade_status_snapshots: list[dict[str, Any]] = Field(default_factory=list)
    execution_channel: str = "支付宝"
    start_discussion: bool = True


class MessageRequest(BaseModel):
    content: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class ExecutionFundingConfirmation(BaseModel):
    available_cash: float = Field(ge=0)
    pending_buy_amount: float = Field(default=0, ge=0)
    consumed_purchase_today: float = Field(default=0, ge=0)


class FinalizeRequest(BaseModel):
    score: int = Field(ge=0, le=100)
    has_veto: bool = False
    suggested_range: DecisionRange
    preflight: TradeStatusSnapshot
    execution_funding: ExecutionFundingConfirmation | None = None
    selected_amount: float | None = Field(default=None, ge=0)


class FeedbackRequest(BaseModel):
    state: Literal["accepted", "partial", "ignored", "watch"]
    selected_amount: float | None = Field(default=None, ge=0)
    note: str | None = None


class PreflightRequest(BaseModel):
    fund_code: str = Field(min_length=1)
    fund_name: str = Field(min_length=1)
    share_class: str = "A"
    customer_scope: Literal["retail", "institutional"] = "retail"
    channel: str = "未确认渠道"
    channel_confirmed: bool = False


@router.get("/trading-policy/templates")
async def list_policy_templates():
    return [MID_TERM_THEME_V1.model_dump(mode="json")]


@router.post("/trading-policy/import")
async def import_policy(
    request: PolicyImportRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        policy = import_policy_template(
            request.template_id, target_allocations=request.target_allocations
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await TradingRoomStore(db).save_policy(policy)
    return policy.model_dump(mode="json")


@router.get("/trading-policy")
async def get_current_policy(db: AsyncSession = Depends(get_db)):
    row = await TradingRoomStore(db).get_current_policy()
    if row is None:
        raise HTTPException(status_code=404, detail="no trading policy imported")
    return json.loads(row.policy_json)


@router.post("/trading-policy")
async def update_current_policy(
    request: PolicyImportRequest,
    db: AsyncSession = Depends(get_db),
):
    return await import_policy(request, db)


@router.post("/trading-room/sessions")
async def create_session(
    request: SessionCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    store = TradingRoomStore(db)
    policy_row = await store.get_policy(request.policy_version_id)
    if policy_row is None:
        raise HTTPException(status_code=404, detail="unknown policy version")

    context = TradingContextBuilder.build(
        as_of=request.as_of,
        data_mode=request.data_mode,
        market_dates=request.market_dates,
        positions=request.positions,
        cash=request.cash,
        equity=request.equity,
        peak_equity=request.peak_equity,
        pending_orders=request.pending_orders,
        themes=request.themes,
        funds=request.funds,
        policy_version_id=request.policy_version_id,
        skill_versions=request.skill_versions,
        critical_inputs=request.critical_inputs,
    )
    session = await store.create_session(
        policy_version_id=request.policy_version_id,
        context_snapshot=context.model_dump(mode="json"),
    )
    for exposure in request.exposure_snapshots:
        fund_code = str(exposure.get("fund_code") or "")
        if fund_code:
            await store.save_exposure_snapshot(
                session.id, fund_code=fund_code, payload=exposure
            )
    trade_statuses = (
        await _collect_server_preflights(request)
        if request.start_discussion
        else request.trade_status_snapshots
    )
    for trade_status in trade_statuses:
        fund_code = str(trade_status.get("fund_code") or "")
        if fund_code:
            await store.save_trade_status_snapshot(
                session.id,
                fund_code=fund_code,
                share_class=str(trade_status.get("share_class") or "UNKNOWN"),
                channel=str(trade_status.get("channel") or "unconfirmed"),
                payload=trade_status,
            )

    if request.start_discussion:
        await _run_discussion(store, session.id, context)
    return await _session_response(store, session.id)


@router.post("/trading-room/preflight")
async def run_execution_preflight(request: PreflightRequest):
    return await _query_preflight(request)


async def _query_preflight(request: PreflightRequest) -> dict[str, Any]:
    now = datetime.now(ZoneInfo(settings.timezone))
    provider = IwencaiAnnouncementProvider(
        api_key=settings.iwencai_api_key,
        base_url=settings.iwencai_api_base_url,
    )
    provider_error: str | None = None
    try:
        records = await provider.search_fund(
            fund_code=request.fund_code,
            fund_name=request.fund_name,
            share_class=request.share_class,
        )
    except AnnouncementProviderError as exc:
        records = []
        provider_error = str(exc)
    snapshot = ExecutionPreflight.restore(
        records=records,
        fund_code=request.fund_code,
        share_class=request.share_class,
        customer_scope=request.customer_scope,
        as_of=now.date(),
        queried_at=now,
        channel_confirmed=request.channel_confirmed,
    )
    payload = snapshot.model_dump(mode="json")
    payload.update(
        {
            "channel": request.channel,
            "preflight_error": provider_error,
            "data_source": "同花顺问财",
        }
    )
    return payload


async def _collect_server_preflights(
    request: SessionCreateRequest,
) -> list[dict[str, Any]]:
    """Replace browser-supplied status with fresh server-side announcement reads."""
    fund_positions: list[tuple[str, str, str]] = []
    for position in request.positions:
        symbol = str(position.get("symbol") or position.get("fund_code") or "")
        position_type = str(position.get("type") or position.get("position_type") or "")
        if not symbol or (position_type and position_type != "fund"):
            continue
        fund_data = request.funds.get(symbol, {})
        name = str(
            position.get("name")
            or (fund_data.get("name") if isinstance(fund_data, dict) else "")
            or symbol
        )
        share_class = "C" if name.strip().endswith("C") else "A"
        fund_positions.append((symbol, name, share_class))

    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for symbol, name, share_class in fund_positions[:8]:
        key = (symbol, share_class)
        if key in seen:
            continue
        seen.add(key)
        results.append(
            await _query_preflight(
                PreflightRequest(
                    fund_code=symbol,
                    fund_name=name,
                    share_class=share_class,
                    customer_scope="retail",
                    channel=request.execution_channel,
                    channel_confirmed=False,
                )
            )
        )
    return results


@router.get("/trading-room/sessions/{session_id}")
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    store = TradingRoomStore(db)
    if await store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="trading-room session not found")
    return await _session_response(store, session_id)


@router.post("/trading-room/sessions/{session_id}/messages")
async def add_message(
    session_id: str,
    request: MessageRequest,
    db: AsyncSession = Depends(get_db),
):
    store = TradingRoomStore(db)
    if await store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="trading-room session not found")
    row = await store.add_message(
        session_id,
        sender_role="user",
        content=request.content,
        payload=request.payload,
    )
    return {
        "id": row.id,
        "session_id": session_id,
        "sender_role": row.sender_role,
        "content": row.content,
        "payload": json.loads(row.message_json),
        "created_at": row.created_at.isoformat(),
    }


@router.post("/trading-room/sessions/{session_id}/finalize")
async def finalize_session(
    session_id: str,
    request: FinalizeRequest,
    db: AsyncSession = Depends(get_db),
):
    store = TradingRoomStore(db)
    from zoneinfo import ZoneInfo

    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="trading-room session not found")
    policy_row = await store.get_policy(session.policy_version_id)
    if policy_row is None:
        raise HTTPException(status_code=409, detail="session policy is missing")
    policy = TradingPolicy.model_validate_json(policy_row.policy_json)
    if not policy.ready:
        missing = ", ".join(policy.missing_confirmations)
        raise HTTPException(status_code=409, detail=f"policy confirmations missing: {missing}")

    context = json.loads(session.context_json)
    classified = DecisionEngine.classify_buy(
        score=request.score,
        policy=policy,
        has_veto=request.has_veto,
    )
    effective_preflight = await _effective_saved_preflight(
        store=store,
        session=session,
        requested=request.preflight,
        context=context,
    )

    # Resolve funding: if execution_funding is provided, save a confirmation record
    # and use it for guard inputs.  Otherwise treat as unconfirmed.
    now = datetime.now(ZoneInfo(settings.timezone))
    if request.execution_funding is not None:
        funding = request.execution_funding
        await store.save_funding_confirmation(
            session_id=session_id,
            fund_code=effective_preflight.fund_code,
            channel=_saved_preflight_channel(session, effective_preflight),
            available_cash=funding.available_cash,
            pending_buy_amount=funding.pending_buy_amount,
            consumed_purchase_today=funding.consumed_purchase_today,
            confirmed_at=now,
        )
        effective_guard_inputs = _guard_inputs_from_context(
            context=context,
            policy=policy,
            fund_code=effective_preflight.fund_code,
            execution_funding=funding,
        )
        if effective_guard_inputs is None:
            decision = GuardedDecision(
                action_class=ActionClass.WATCH,
                suggested_range=request.suggested_range,
                guarded_range=None,
                immediately_executable=False,
                reasons=("target_allocation_not_measurable",),
            )
        else:
            decision = DecisionEngine.apply_buy_guard(
                classified_action=classified,
                suggested=request.suggested_range,
                preflight=effective_preflight,
                guard_inputs=effective_guard_inputs,
            )
    else:
        effective_guard_inputs = _guard_inputs_from_context(
            context=context,
            policy=policy,
            fund_code=effective_preflight.fund_code,
            execution_funding=None,
        )
        if effective_guard_inputs is not None and classified is not ActionClass.WATCH:
            raise HTTPException(
                status_code=409,
                detail="available_cash_confirmation_required",
            )
        decision = GuardedDecision(
            action_class=ActionClass.WATCH,
            suggested_range=request.suggested_range,
            guarded_range=None,
            immediately_executable=False,
            reasons=("available_cash_confirmation_required",),
        )

    if not context.get("formally_actionable", False):
        decision = decision.model_copy(
            update={
                "action_class": ActionClass.WATCH,
                "guarded_range": None,
                "immediately_executable": False,
                "reasons": tuple(context.get("blockers") or ("context_incomplete",)),
            }
        )

    if request.selected_amount is not None:
        _validate_selected_amount(request.selected_amount, decision.guarded_range)

    payload = decision.model_dump(mode="json")
    payload.update(
        {
            "score": request.score,
            "selected_amount": request.selected_amount,
            "policy_version_id": policy.version_id,
            "context_hash": context.get("context_hash"),
            "preflight": effective_preflight.model_dump(mode="json"),
            "manual_execution_only": True,
        }
    )
    await store.finalize_session(session_id, decision=payload)
    return {"session_id": session_id, "decision": payload}


@router.get("/trading-room/funding/latest")
async def get_latest_funding_confirmation(
    db: AsyncSession = Depends(get_db),
):
    """Return the most recent available_cash and confirmed_at for prefill."""
    record = await TradingRoomStore(db).get_latest_cash_confirmation()
    if record is None:
        return {"available_cash": None, "confirmed_at": None}
    return {
        "available_cash": record.available_cash,
        "confirmed_at": record.confirmed_at.isoformat(),
    }


@router.post("/trading-room/sessions/{session_id}/actions")
async def record_action(
    session_id: str,
    request: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
):
    store = TradingRoomStore(db)
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="trading-room session not found")
    if request.selected_amount is not None:
        decision = json.loads(session.final_decision_json or "{}")
        guarded_payload = decision.get("guarded_range")
        guarded = DecisionRange.model_validate(guarded_payload) if guarded_payload else None
        _validate_selected_amount(request.selected_amount, guarded)
    row = await store.record_feedback(
        session_id,
        state=request.state,
        selected_amount=request.selected_amount,
        note=request.note,
    )
    return {
        "session_id": session_id,
        "feedback_state": row.feedback_state,
        "selected_amount": row.selected_amount,
        "note": row.feedback_note,
        "feedback_at": row.feedback_at.isoformat() if row.feedback_at else None,
    }


async def _run_discussion(store, session_id, context) -> None:
    if not llm_credentials_configured("chair"):
        await store.add_message(
            session_id,
            sender_role="system",
            content="DeepSeek API 尚未配置；上下文已保存，专业席位暂不可用。",
            payload={"error": "llm_not_configured"},
        )
        return
    registry = TradingSkillRegistry(
        trading_root=settings.trading_skill_root,
        market_root=settings.market_skill_root,
    )
    roles = (*ROUND_ONE_ROUTE, "skeptic")
    runners = {
        role: create_specialist(role, skill_registry=registry) for role in roles
    }
    result = await TradingRoomOrchestrator(runners=runners).discuss(context)
    for round_name, memos in (("round_one", result.round_one), ("round_two", result.round_two)):
        for role, specialist_result in memos.items():
            payload = (
                specialist_result.memo.model_dump(mode="json")
                if specialist_result.memo is not None
                else {"error": specialist_result.error}
            )
            payload["round"] = round_name
            payload["context_hash"] = specialist_result.context_hash
            payload["model"] = specialist_result.model
            await store.add_memo(
                session_id,
                role=role,
                state=specialist_result.state.value,
                payload=payload,
                skill_versions=specialist_result.skill_versions,
            )


async def _session_response(store: TradingRoomStore, session_id: str) -> dict[str, Any]:
    row = await store.get_session(session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="trading-room session not found")
    return {
        "session_id": row.id,
        "status": row.status,
        "policy_version_id": row.policy_version_id,
        "context": json.loads(row.context_json),
        "specialist_memos": [
            {
                "role": item.role,
                "state": item.state,
                "memo": json.loads(item.memo_json),
                "skill_versions": json.loads(item.skill_versions_json),
                "created_at": item.created_at.isoformat(),
            }
            for item in row.specialist_memos
        ],
        "messages": [
            {
                "id": item.id,
                "sender_role": item.sender_role,
                "content": item.content,
                "payload": json.loads(item.message_json),
                "created_at": item.created_at.isoformat(),
            }
            for item in row.messages
        ],
        "exposure_snapshots": [json.loads(item.snapshot_json) for item in row.exposure_snapshots],
        "trade_status_snapshots": [
            json.loads(item.snapshot_json) for item in row.trade_status_snapshots
        ],
        "funding_confirmations": [
            {
                "fund_code": item.fund_code,
                "channel": item.channel,
                "available_cash": item.available_cash,
                "pending_buy_amount": item.pending_buy_amount,
                "consumed_purchase_today": item.consumed_purchase_today,
                "confirmed_at": item.confirmed_at.isoformat(),
            }
            for item in await store.list_funding_confirmations(session_id)
        ],
        "policy_proposals": [
            {
                "field": item.field,
                "proposed_value": json.loads(item.proposed_value_json),
                "reason": item.reason,
                "status": item.status,
            }
            for item in row.policy_proposals
        ],
        "final_decision": json.loads(row.final_decision_json) if row.final_decision_json else None,
        "feedback_state": row.feedback_state,
        "selected_amount": row.selected_amount,
        "feedback_note": row.feedback_note,
        "created_at": row.created_at.isoformat(),
        "manual_execution_only": True,
    }


def _validate_selected_amount(
    selected_amount: float,
    guarded_range: DecisionRange | None,
) -> None:
    if guarded_range is None:
        raise HTTPException(
            status_code=422,
            detail="no executable amount is available for this decision",
        )
    if not (guarded_range.minimum <= selected_amount <= guarded_range.maximum):
        raise HTTPException(
            status_code=422,
            detail=(
                f"selected amount must be between {guarded_range.minimum:g} "
                f"and {guarded_range.maximum:g}"
            ),
        )


async def _effective_saved_preflight(
    *,
    store: TradingRoomStore,
    session,
    requested: TradeStatusSnapshot,
    context: dict[str, Any],
) -> TradeStatusSnapshot:
    """Use the session audit snapshot, never a caller-supplied status claim."""
    stored_payload: dict[str, Any] | None = None
    for row in reversed(session.trade_status_snapshots):
        candidate = json.loads(row.snapshot_json)
        if (
            str(candidate.get("fund_code")) == requested.fund_code
            and str(candidate.get("share_class")) == requested.share_class
        ):
            stored_payload = candidate
            break

    now = datetime.now(requested.queried_at.tzinfo or ZoneInfo(settings.timezone))
    if stored_payload is None:
        return TradeStatusSnapshot(
            fund_code=requested.fund_code,
            share_class=requested.share_class,
            customer_scope=requested.customer_scope,
            manager_status="UNKNOWN",
            redemption_status="UNKNOWN",
            queried_at=now,
            channel_confirmed=False,
            maximum_action_class=ActionClass.CONDITIONAL,
            manager_source="announcement-search:session_snapshot_missing",
        )

    saved = TradeStatusSnapshot.model_validate(stored_payload)
    age_minutes = (now - saved.queried_at).total_seconds() / 60
    if age_minutes <= settings.execution_preflight_fresh_minutes:
        return saved

    fund_data = context.get("funds", {}).get(saved.fund_code, {})
    fund_name = (
        str(fund_data.get("name") or saved.fund_code)
        if isinstance(fund_data, dict)
        else saved.fund_code
    )
    provider = IwencaiAnnouncementProvider(
        api_key=settings.iwencai_api_key,
        base_url=settings.iwencai_api_base_url,
    )
    try:
        records = await provider.search_fund(
            fund_code=saved.fund_code,
            fund_name=fund_name,
            share_class=saved.share_class,
        )
    except AnnouncementProviderError:
        return TradeStatusSnapshot(
            fund_code=saved.fund_code,
            share_class=saved.share_class,
            customer_scope=saved.customer_scope,
            manager_status="UNKNOWN",
            redemption_status="UNKNOWN",
            queried_at=now,
            channel_confirmed=False,
            maximum_action_class=ActionClass.CONDITIONAL,
            manager_source="announcement-search:refresh_failed",
        )

    refreshed = ExecutionPreflight.restore(
        records=records,
        fund_code=saved.fund_code,
        share_class=saved.share_class,
        customer_scope=saved.customer_scope,
        as_of=now.date(),
        queried_at=now,
        channel_confirmed=saved.channel_confirmed,
    )
    await store.save_trade_status_snapshot(
        session.id,
        fund_code=refreshed.fund_code,
        share_class=refreshed.share_class,
        channel=str(stored_payload.get("channel") or "unconfirmed"),
        payload={
            **refreshed.model_dump(mode="json"),
            "channel": stored_payload.get("channel") or "unconfirmed",
            "data_source": "同花顺问财",
        },
    )
    return refreshed


def _saved_preflight_channel(
    session,
    preflight: TradeStatusSnapshot,
) -> str:
    """Return the channel saved in the session snapshot for `preflight`."""
    for row in reversed(session.trade_status_snapshots):
        candidate = json.loads(row.snapshot_json)
        if (
            str(candidate.get("fund_code")) == preflight.fund_code
            and str(candidate.get("share_class")) == preflight.share_class
        ):
            return str(candidate.get("channel") or "支付宝")
    return "支付宝"


def _guard_inputs_from_context(
    *,
    context: dict[str, Any],
    policy: TradingPolicy,
    fund_code: str,
    execution_funding: ExecutionFundingConfirmation | None = None,
) -> BuyGuardInputs | None:
    """Recompute every measurable cap from immutable server-side inputs.

    Uses execution_funding if available; otherwise uses context values
    (which may be None/missing for an unconfirmed state).
    """
    target = next(
        (
            item for item in policy.target_allocations
            if item.scope == "fund" and item.key == fund_code
        ),
        None,
    )
    # A theme target needs aggregate theme exposure, not one fund's allocation.
    # Until that aggregate is present in the snapshot, fail closed.
    if target is None:
        return None

    holdings_value = sum(
        max(0.0, float(p.get("market_value") or 0))
        for p in (context.get("positions") or [])
        if isinstance(p, dict)
    )

    if execution_funding is not None:
        account_equity = holdings_value + execution_funding.available_cash
        available_cash = execution_funding.available_cash
        pending_buy_amount = execution_funding.pending_buy_amount
        consumed_purchase_today = execution_funding.consumed_purchase_today
    else:
        equity = float(context.get("equity") or 0)
        if equity <= 0:
            return None
        account_equity = equity
        available_cash = max(0.0, float(context.get("cash") or 0))
        pending_buy_amount = sum(
            max(0.0, float(order.get("amount") or 0))
            for order in (context.get("pending_orders") or [])
            if isinstance(order, dict) and str(order.get("side") or "").lower() == "buy"
        )
        consumed_purchase_today = 0

    current_value = 0.0
    for position in context.get("positions") or []:
        if not isinstance(position, dict):
            continue
        symbol = str(position.get("symbol") or position.get("fund_code") or "")
        if symbol == fund_code:
            current_value += max(0.0, float(position.get("market_value") or 0))

    if account_equity <= 0:
        return None

    return BuyGuardInputs(
        consumed_purchase_today=consumed_purchase_today,
        account_equity=account_equity,
        current_allocation_pct=current_value / account_equity,
        target_allocation_pct=target.target_pct,
        available_cash=available_cash,
        pending_buy_amount=pending_buy_amount,
    )
