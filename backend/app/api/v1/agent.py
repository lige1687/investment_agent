"""AI Agent chat API + decision card / evidence lookup endpoints + Guardian."""
import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.guardian import BriefingSlot
from app.services.agent_service import InvestmentAgent
from app.services.decision_store import (
    VALID_USER_ACTIONS,
    DecisionCardStore,
)
from app.services.evidence_bus import EvidenceBus
from app.services.guardian import GuardianAgent
from app.services.outcome_tracker import OutcomeTracker

router = APIRouter(prefix="/agent", tags=["Agent"])


# ── /chat ─────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., description="用户问题")
    history: list[dict] = Field(default_factory=list, description="对话历史(role/content)")
    session_id: Optional[str] = Field(
        default=None,
        description="会话 id;传入即可跨请求共享 evidence bus / decision cards。"
                    "未传则由服务端生成并回传。",
    )


class ChatResponse(BaseModel):
    answer: str
    decision_card: Optional[dict] = None
    stored_card_id: Optional[int] = None
    evidence_refs: list[str] = []
    tool_calls: list[dict] = []
    session_id: str
    fallback: bool = False
    turns: Optional[int] = None
    stop_reason: Optional[str] = None
    usage: Optional[dict] = None
    error: Optional[str] = None


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    """AI 投资助手问答。

    - 决策类问题(买/卖/调仓/推荐)会返回结构化的 `decision_card`。
    - 每个工具结果都会记入证据总线,`evidence_refs` 列出决策卡引用的 ev_id。
    - 传同一个 `session_id` 可以在多轮对话之间共享证据 / 决策卡。
    """
    agent = InvestmentAgent(db, session_id=req.session_id)
    result = await agent.chat(req.message, req.history)
    return ChatResponse(**result)


# ── /evidence/{ev_id} ─────────────────────────────────────────────────────

class EvidenceResponse(BaseModel):
    ev_id: str
    session_id: str
    agent: str
    source: str
    query: dict[str, Any] = {}
    data: str
    summary: Optional[str] = None
    fetched_at: str
    ttl_seconds: int
    is_fresh: bool


@router.get("/evidence/{ev_id}", response_model=EvidenceResponse)
async def get_evidence(ev_id: str, db: AsyncSession = Depends(get_db)):
    """Fetch one evidence snapshot by id — for frontend click-through."""
    # `session_id` on the bus is only used for scoping *writes*; reads work
    # by primary key. Pass a placeholder here.
    bus = EvidenceBus(db, session_id="lookup")
    record = await bus.get(ev_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"evidence {ev_id} not found")
    return EvidenceResponse(**record.to_dict())


class SessionEvidenceListResponse(BaseModel):
    session_id: str
    count: int
    items: list[EvidenceResponse]


@router.get("/sessions/{session_id}/evidence", response_model=SessionEvidenceListResponse)
async def list_session_evidence(
    session_id: str,
    limit: int = 50,
    only_fresh: bool = False,
    db: AsyncSession = Depends(get_db),
):
    bus = EvidenceBus(db, session_id=session_id)
    records = await bus.list_session(limit=limit, only_fresh=only_fresh)
    return SessionEvidenceListResponse(
        session_id=session_id,
        count=len(records),
        items=[EvidenceResponse(**r.to_dict()) for r in records],
    )


# ── /decisions ────────────────────────────────────────────────────────────

class DecisionResponse(BaseModel):
    decision_id: str
    card: dict


@router.get("/decisions/{decision_id}", response_model=DecisionResponse)
async def get_decision(decision_id: str, db: AsyncSession = Depends(get_db)):
    store = DecisionCardStore(db)
    card = await store.get_by_id(decision_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"decision {decision_id} not found")
    return DecisionResponse(decision_id=decision_id, card=card.model_dump(mode="json"))


class DecisionListResponse(BaseModel):
    session_id: str
    count: int
    items: list[dict]


@router.get("/sessions/{session_id}/decisions", response_model=DecisionListResponse)
async def list_session_decisions(
    session_id: str, limit: int = 20, db: AsyncSession = Depends(get_db),
):
    store = DecisionCardStore(db)
    cards = await store.list_session(session_id, limit=limit)
    return DecisionListResponse(
        session_id=session_id,
        count=len(cards),
        items=[c.model_dump(mode="json") for c in cards],
    )


class MarkActionRequest(BaseModel):
    action: str = Field(..., description=f"one of {sorted(VALID_USER_ACTIONS)}")


class MarkActionResponse(BaseModel):
    decision_id: str
    user_action: str
    user_action_at: Optional[str] = None


@router.post("/decisions/{decision_id}/action", response_model=MarkActionResponse)
async def mark_decision_action(
    decision_id: str,
    req: MarkActionRequest,
    db: AsyncSession = Depends(get_db),
):
    """User accepted / ignored / partial'd a decision card. Used later by
    Guardian to compute hit-rate."""
    store = DecisionCardStore(db)
    try:
        row = await store.mark_user_action(decision_id, req.action)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if row is None:
        raise HTTPException(status_code=404, detail=f"decision {decision_id} not found")
    return MarkActionResponse(
        decision_id=decision_id,
        user_action=row.user_action,
        user_action_at=row.user_action_at.isoformat(timespec="seconds") if row.user_action_at else None,
    )


# ── /guardian ─────────────────────────────────────────────────────────────

class GuardianRunResponse(BaseModel):
    session_id: str
    slot: str
    started_at: str
    finished_at: Optional[str] = None
    alert_count: int
    decision_count: int
    llm_used: bool
    pushed_to_feishu: bool
    error: Optional[str] = None
    briefing_text: Optional[str] = None
    portfolio_snapshot: dict[str, Any] = {}
    market_snapshot: dict[str, Any] = {}
    alerts: list[dict] = []
    decision_ids: list[str] = []


class GuardianListResponse(BaseModel):
    count: int
    items: list[GuardianRunResponse]


def _row_to_response(row) -> GuardianRunResponse:
    """Turn a GuardianRun DB row into the API response DTO."""
    try:
        result = json.loads(row.result_json or "{}")
    except json.JSONDecodeError:
        result = {}
    return GuardianRunResponse(
        session_id=row.session_id,
        slot=row.slot,
        started_at=row.started_at.isoformat(timespec="seconds") if row.started_at else "",
        finished_at=row.finished_at.isoformat(timespec="seconds") if row.finished_at else None,
        alert_count=row.alert_count,
        decision_count=row.decision_count,
        llm_used=row.llm_used,
        pushed_to_feishu=row.pushed_to_feishu,
        error=row.error,
        briefing_text=result.get("briefing_text"),
        portfolio_snapshot=result.get("portfolio_snapshot") or {},
        market_snapshot=result.get("market_snapshot") or {},
        alerts=result.get("alerts") or [],
        decision_ids=result.get("decision_ids") or [],
    )


@router.post("/guardian/run", response_model=GuardianRunResponse)
async def run_guardian_now(
    slot: str = Query("manual", description="midday | close | manual"),
    db: AsyncSession = Depends(get_db),
):
    """立即执行一次 Guardian 体检。前端"立即体检"按钮走这条。"""
    try:
        slot_enum = BriefingSlot(slot)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"invalid slot {slot!r}; expected midday | close | manual",
        )
    agent = GuardianAgent(db, slot=slot_enum)
    result = await agent.run()
    # Read back the row we just saved so response reflects DB state
    from app.models.evidence import GuardianRun as GuardianRunRow
    from sqlalchemy import select as _select
    row = (await db.execute(
        _select(GuardianRunRow).where(GuardianRunRow.session_id == result.session_id)
    )).scalar_one_or_none()
    if row is None:
        # Fallback: return live result
        return GuardianRunResponse(
            session_id=result.session_id,
            slot=result.slot if isinstance(result.slot, str) else result.slot.value,
            started_at=result.started_at,
            finished_at=result.finished_at,
            alert_count=len(result.alerts),
            decision_count=len(result.decision_ids),
            llm_used=result.llm_used,
            pushed_to_feishu=result.pushed_to_feishu,
            error=result.error,
            briefing_text=result.briefing_text,
            portfolio_snapshot=result.portfolio_snapshot,
            market_snapshot=result.market_snapshot,
            alerts=[a.model_dump(mode="json") for a in result.alerts],
            decision_ids=result.decision_ids,
        )
    return _row_to_response(row)


@router.get("/guardian/runs", response_model=GuardianListResponse)
async def list_guardian_runs(
    limit: int = 10, db: AsyncSession = Depends(get_db),
):
    """最近 N 次 Guardian 扫描,新到旧。"""
    from app.models.evidence import GuardianRun as GuardianRunRow
    from sqlalchemy import desc as _desc, select as _select
    rows = (await db.execute(
        _select(GuardianRunRow)
        .order_by(_desc(GuardianRunRow.started_at), _desc(GuardianRunRow.id))
        .limit(limit)
    )).scalars().all()
    return GuardianListResponse(
        count=len(rows),
        items=[_row_to_response(r) for r in rows],
    )


@router.get("/guardian/{session_id}", response_model=GuardianRunResponse)
async def get_guardian_run(session_id: str, db: AsyncSession = Depends(get_db)):
    from app.models.evidence import GuardianRun as GuardianRunRow
    from sqlalchemy import select as _select
    row = (await db.execute(
        _select(GuardianRunRow).where(GuardianRunRow.session_id == session_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"guardian run {session_id} not found")
    return _row_to_response(row)


class OutcomeUpdateResponse(BaseModel):
    seven_day_updated: int
    thirty_day_updated: int
    skipped_no_snapshot: int
    skipped_no_price: int
    updated_ids: list[str]


@router.post("/guardian/outcome/update", response_model=OutcomeUpdateResponse)
async def trigger_outcome_update(db: AsyncSession = Depends(get_db)):
    """手动触发命中率追踪更新(cron 是每晚 21:00)。"""
    tracker = OutcomeTracker(db)
    stats = await tracker.update_outstanding()
    return OutcomeUpdateResponse(**stats.to_dict())


@router.get("/guardian/outcome/summary")
async def get_outcome_summary(
    days: int = Query(90, ge=1, le=730),
    db: AsyncSession = Depends(get_db),
):
    """过去 N 天的整体命中率与均值回报。"""
    tracker = OutcomeTracker(db)
    return await tracker.hit_rate_summary(days=days)


# ── /decisions/{id}/monitoring-alerts ─────────────────────────────────────

class MonitoringAlertItem(BaseModel):
    id: int
    symbol: str
    alert_type: str
    threshold: float
    direction: Optional[str]
    enabled: bool
    cooldown_min: int
    note: Optional[str]
    source: str
    source_ref: Optional[str]
    created_at: Optional[str] = None


class MonitoringAlertListResponse(BaseModel):
    decision_id: str
    count: int
    items: list[MonitoringAlertItem]


def _alert_to_item(row) -> MonitoringAlertItem:
    return MonitoringAlertItem(
        id=row.id,
        symbol=row.symbol,
        alert_type=row.alert_type,
        threshold=row.threshold,
        direction=row.direction,
        enabled=row.enabled,
        cooldown_min=row.cooldown_min,
        note=row.note,
        source=row.source,
        source_ref=row.source_ref,
        created_at=row.created_at.isoformat(timespec="seconds") if row.created_at else None,
    )


@router.get("/decisions/{decision_id}/monitoring-alerts", response_model=MonitoringAlertListResponse)
async def list_decision_monitoring_alerts(
    decision_id: str, db: AsyncSession = Depends(get_db),
):
    """List the PriceAlert rows spawned by this decision card's monitoring[]."""
    from app.services.monitoring_alert import MonitoringAlertSynthesizer
    synth = MonitoringAlertSynthesizer(db)
    rows = await synth.list_for_decision(decision_id)
    return MonitoringAlertListResponse(
        decision_id=decision_id,
        count=len(rows),
        items=[_alert_to_item(r) for r in rows],
    )


class DisableBatchResponse(BaseModel):
    decision_id: str
    disabled_count: int


@router.post("/decisions/{decision_id}/monitoring-alerts/disable", response_model=DisableBatchResponse)
async def disable_decision_monitoring_alerts(
    decision_id: str, db: AsyncSession = Depends(get_db),
):
    """One-click stop watching this card's conditions (e.g. after the user
    already acted on it or dismissed it)."""
    from app.services.monitoring_alert import MonitoringAlertSynthesizer
    synth = MonitoringAlertSynthesizer(db)
    n = await synth.disable_batch(decision_id)
    return DisableBatchResponse(decision_id=decision_id, disabled_count=n)
