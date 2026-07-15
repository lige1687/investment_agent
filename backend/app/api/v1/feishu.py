"""Feishu bot configuration API."""
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.feishu.bot import feishu_bot
from app.models.feishu import FeishuConfig
from app.config import settings

router = APIRouter(prefix="/feishu", tags=["Feishu"])


class FeishuConfigUpdate(BaseModel):
    webhook_url: str
    notify_market_open: bool = True
    notify_market_close: bool = True
    notify_alerts: bool = True
    notify_signals: bool = True
    notify_pnl: bool = True


class DevAskRequest(BaseModel):
    message: str
    use_skill: bool = True


def mask_webhook_url(value: str) -> str:
    """Return a non-reversible hint suitable for API responses and UI copy."""

    value = value.strip()
    if not value:
        return ""
    parsed = urlsplit(value)
    host = parsed.netloc or "configured"
    scheme = parsed.scheme if parsed.scheme in {"http", "https"} else "https"
    return f"{scheme}://{host}/****"


def should_route_to_sector_detail(message: str) -> bool:
    text = message.lower()
    sector_words = ["半导体", "芯片", "通信", "光模块", "有色", "电池", "消费", "港股", "纳指", "美股"]
    detail_words = ["为什么", "为啥", "原因", "有机会", "机会", "回避", "风险", "观察"]
    return any(word in text for word in sector_words) and any(word in text for word in detail_words)


@router.get("/config")
async def get_config(db: AsyncSession = Depends(get_db)):
    """Get Feishu bot configuration."""
    from sqlalchemy import select
    stmt = select(FeishuConfig).order_by(FeishuConfig.created_at.desc()).limit(1)
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()

    return {
        "configured": feishu_bot.configured,
        "webhook_hint": mask_webhook_url(
            config.webhook_url if config else settings.feishu_webhook_url
        ),
        "notify_market_open": config.notify_market_open if config else True,
        "notify_market_close": config.notify_market_close if config else True,
        "notify_alerts": config.notify_alerts if config else True,
        "notify_signals": config.notify_signals if config else True,
        "notify_pnl": config.notify_pnl if config else True,
    }


@router.put("/config")
async def update_config(req: FeishuConfigUpdate, db: AsyncSession = Depends(get_db)):
    """Update Feishu bot configuration."""
    from sqlalchemy import select

    stmt = select(FeishuConfig).order_by(FeishuConfig.id.desc()).limit(1)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    requested_webhook = req.webhook_url.strip()
    effective_webhook = requested_webhook or (
        existing.webhook_url if existing else settings.feishu_webhook_url
    )

    config = FeishuConfig(
        webhook_url=effective_webhook,
        notify_market_open=req.notify_market_open,
        notify_market_close=req.notify_market_close,
        notify_alerts=req.notify_alerts,
        notify_signals=req.notify_signals,
        notify_pnl=req.notify_pnl,
    )
    db.add(config)
    await db.flush()

    # Update global bot instance
    global feishu_bot
    feishu_bot._webhook = effective_webhook

    return {"ok": True, "configured": feishu_bot.configured}


@router.post("/test")
async def test_push(db: AsyncSession = Depends(get_db)):
    """Send a test message to verify Feishu bot works."""
    if not feishu_bot.configured:
        return {"ok": False, "error": "飞书 Webhook 未配置，请先设置 Webhook URL"}

    success = await feishu_bot.send_text(
        "✅ 飞书机器人连接测试成功！\n\n"
        "如果你看到这条消息，说明配置正确。\n"
        "接下来你将收到：\n"
        "• 每日 9:20 前夜美股总结\n"
        "• 每日 12:05 早盘总结\n"
        "• 每日 14:35 尾盘总结\n"
        "• 持仓异动实时预警\n"
        "• 交易信号推送"
    )
    return {"ok": success}


@router.post("/test-sector-card")
async def test_sector_card_push(db: AsyncSession = Depends(get_db)):
    """Send a compact sector summary card using live sector flow + holdings."""
    if not feishu_bot.configured:
        return {"ok": False, "error": "飞书 Webhook 未配置，请先设置 Webhook URL"}

    from app.services.sector_card_service import build_live_sector_card

    from app.services.agent_context_service import AgentContextService

    card = await build_live_sector_card()
    context_payload = card.pop("_context_snapshot", None)
    context_snapshot_id = None
    if context_payload:
        context_snapshot_id = await AgentContextService(db).save_snapshot(
            source="feishu_card",
            intent="sector_monitor",
            question="板块监控测试卡",
            context=context_payload["context"],
            decision=context_payload["decision"],
            skill_calls=context_payload["skill_calls"],
        )
    success = await feishu_bot.send_card(card)
    return {
        "ok": success,
        "sent": success,
        "context_snapshot_id": context_snapshot_id,
        "title": card.get("header", {}).get("title", {}).get("content"),
        "preview": card,
    }


@router.post("/dev-ask")
async def dev_ask(req: DevAskRequest, db: AsyncSession = Depends(get_db)):
    """Local development endpoint that simulates a Feishu @bot question."""
    from app.agents.sector_detail_agent import SectorDetailAgent
    from app.services.agent_context_service import AgentContextService
    from app.services.portfolio_advice_service import build_portfolio_advice_answer

    context_service = AgentContextService(db)
    if should_route_to_sector_detail(req.message):
        snapshot = await context_service.find_recent_relevant_snapshot(req.message)
        result = await SectorDetailAgent().explain(question=req.message, snapshot=snapshot)
        return {
            "ok": True,
            "message": req.message,
            "has_recent_context": snapshot is not None,
            **result,
        }

    recent_context = await context_service.build_recent_context_block(req.message)
    result = await build_portfolio_advice_answer(
        req.message,
        use_skill=req.use_skill,
        recent_context=recent_context,
    )
    return {
        "ok": True,
        "message": req.message,
        "has_recent_context": bool(recent_context),
        **result,
    }


@router.post("/push/us-overnight")
async def push_us_overnight_now():
    """Manually trigger 09:20 US overnight skill summary."""
    from app.tasks.daily_summary import us_overnight_push
    return await us_overnight_push()


@router.post("/push/morning")
async def push_morning_now():
    """Manually trigger 12:05 morning session skill summary."""
    from app.tasks.daily_summary import morning_session_push
    return await morning_session_push()


@router.post("/push/tail")
async def push_tail_now():
    """Manually trigger 14:35 tail session skill summary."""
    from app.tasks.daily_summary import tail_session_push
    return await tail_session_push()
