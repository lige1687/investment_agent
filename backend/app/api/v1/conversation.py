"""REST API for the conversational trading room."""

from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo

from app.config import settings
from app.database import async_session, get_db
from app.llm import registry
from app.services.yangjibao_service import YangjibaoService
from app.trading_room.account_valuation import AccountValuationService
from app.trading_room.context import CriticalDataInput, TradingContextBuilder
from app.trading_room.conversation.chair import ConversationChair
from app.trading_room.conversation.orchestrator import ConversationOrchestrator
from app.trading_room.conversation.router import ConversationRouter
from app.trading_room.conversation.schemas import PresetId, TurnRequest
from app.trading_room.amount_strategy import TargetGapStrategy
from app.trading_room.policy import TradingPolicy
from app.trading_room.skill_registry import TradingSkillRegistry
from app.trading_room.specialists.roles import create_specialist_for_preset
from app.trading_room.store import TradingRoomStore

router = APIRouter(prefix="/agent/trading-room", tags=["Trading Room Conversation"])


class ConversationResponse(BaseModel):
    conversation_id: str


class AskResponse(BaseModel):
    turn_id: str


class MessageItem(BaseModel):
    id: int
    sender_role: str
    content: str
    payload: dict
    created_at: str


class MessageListResponse(BaseModel):
    messages: list[MessageItem]
    next_cursor: int


@router.post("/conversations", response_model=ConversationResponse)
async def create_or_get_conversation(db: AsyncSession = Depends(get_db)):
    store = TradingRoomStore(db)
    policy_row = await store.get_current_policy()
    if policy_row is None:
        raise HTTPException(404, "no trading policy imported")
    policy = TradingPolicy.model_validate_json(policy_row.policy_json)

    portfolio = await YangjibaoService(db).get_local_portfolio()
    positions = portfolio.get("positions") or []
    funds = {p["symbol"]: {"name": p.get("name") or p["symbol"]} for p in positions}
    now = datetime.now(ZoneInfo(settings.timezone))
    peak_equity = await AccountValuationService(db).recent_peak(as_of=now)

    context = TradingContextBuilder.build(
        as_of=now, data_mode=settings.market_data_mode,
        market_dates={"CN": now.date().isoformat()},
        positions=positions, cash=None, equity=None, peak_equity=peak_equity,
        pending_orders=[], themes={}, funds=funds,
        policy_version_id=policy.version_id, skill_versions={},
        critical_inputs=[CriticalDataInput(
            key="portfolio", source="yangjibao",
            as_of=datetime.fromisoformat(portfolio["synced_at"])
              if portfolio.get("synced_at") else None,
            confidence="HIGH" if portfolio.get("connected") else "UNKNOWN",
            is_mock=False,
            stale=False,
        )],
    )
    session = await store.create_session(
        policy_version_id=policy.version_id,
        context_snapshot=context.model_dump(mode="json"),
    )
    return ConversationResponse(conversation_id=session.id)


@router.post("/conversations/{conversation_id}/ask", response_model=AskResponse)
async def ask(
    conversation_id: str,
    request: TurnRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    if not registry.llm_credentials_configured("chair"):
        raise HTTPException(503, "LLM not configured")

    store = TradingRoomStore(db)
    session_row = await store.get_session(conversation_id)
    if session_row is None:
        raise HTTPException(404, "conversation not found")

    # 并发保护：查找是否已有进行中的 turn（chair_summary 或 error 未出现）
    turn_ids: dict[str, dict] = {}
    for m in session_row.messages:
        payload = json.loads(m.message_json or "{}")
        tid = payload.get("turn_id")
        if not tid:
            continue
        state = turn_ids.setdefault(tid, {"started": False, "ended": False})
        if payload.get("kind") == "routing":
            state["started"] = True
        if payload.get("kind") in {"chair_summary", "clarification", "error"}:
            state["ended"] = True
    if any(v["started"] and not v["ended"] for v in turn_ids.values()):
        raise HTTPException(409, "another turn is in progress")

    turn_id = str(uuid4())
    policy_row = await store.get_policy(session_row.policy_version_id)
    policy = TradingPolicy.model_validate_json(policy_row.policy_json)
    context_dict = json.loads(session_row.context_json)
    positions = context_dict.get("positions") or []
    named_positions = [
        {"code": str(p.get("symbol") or ""), "name": str(p.get("name") or "")}
        for p in positions
    ]

    # 立即写一条 user 消息（前端能立刻回显）
    await store.add_message(
        conversation_id, sender_role="user",
        content=(request.text or (f"[快捷] {request.preset_id.value}" if request.preset_id else "?")),
        payload={"turn_id": turn_id, "kind": "text",
                 "payload": {"text": request.text, "preset_id":
                             request.preset_id.value if request.preset_id else None}},
    )

    async def _work():
        # BackgroundTasks 拿不到 request-scoped db，用独立 session
        async with async_session() as bg_db:
            bg_store = TradingRoomStore(bg_db)
            skill_registry = TradingSkillRegistry(
                trading_root=settings.trading_skill_root,
                market_root=settings.market_skill_root,
            )
            router_llm = registry.get_llm_client("intent_router")
            chair_llm = registry.get_llm_client("chair")
            router_impl = ConversationRouter(client=router_llm, skill_registry=skill_registry)
            chair_impl = ConversationChair(client=chair_llm, skill_registry=skill_registry)
            specialists = {
                role: create_specialist_for_preset(
                    role, preset_id=request.preset_id, skill_registry=skill_registry,
                )
                for role in {"market_regime", "theme_fund", "portfolio_risk",
                             "buy", "sell_protection", "skeptic"}
            }
            orch = ConversationOrchestrator(
                router=router_impl, specialists=specialists, chair=chair_impl,
                amount_strategy=TargetGapStrategy(),
            )
            from app.trading_room.context import TradingContextSnapshot
            context = TradingContextSnapshot.model_validate(context_dict)
            try:
                await orch.run_turn(
                    session_id=conversation_id, turn_id=turn_id,
                    request=request, positions=named_positions,
                    context_snapshot=context,
                    target_allocations=policy.target_allocations,
                    store=bg_store,
                )
                await bg_db.commit()
            except Exception as exc:  # 兜底
                await bg_store.add_message(
                    conversation_id, sender_role="system",
                    content=f"错误: {exc}",
                    payload={"turn_id": turn_id, "kind": "error",
                             "payload": {"detail": str(exc)}},
                )
                await bg_db.commit()

    background_tasks.add_task(_work)
    return AskResponse(turn_id=turn_id)


@router.get("/conversations/{conversation_id}/messages",
            response_model=MessageListResponse)
async def list_messages(
    conversation_id: str, after: int = 0,
    db: AsyncSession = Depends(get_db),
):
    store = TradingRoomStore(db)
    session_row = await store.get_session(conversation_id)
    if session_row is None:
        raise HTTPException(404, "conversation not found")
    items: list[MessageItem] = []
    max_id = after
    for m in session_row.messages:
        if m.id <= after:
            continue
        items.append(MessageItem(
            id=m.id, sender_role=m.sender_role, content=m.content,
            payload=json.loads(m.message_json or "{}"),
            created_at=m.created_at.isoformat(),
        ))
        max_id = max(max_id, m.id)
    return MessageListResponse(messages=items, next_cursor=max_id)
