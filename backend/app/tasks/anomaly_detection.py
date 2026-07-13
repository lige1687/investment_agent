"""Anomaly detection task — scans positions for significant changes."""
import logging
from sqlalchemy import select
from app.database import async_session
from app.models.position import Position
from app.models.fund import FundProfile
from app.tasks.scheduler import is_trading_day, is_market_hours
from app.feishu.bot import feishu_bot

logger = logging.getLogger(__name__)

# Thresholds
PRICE_CHANGE_THRESHOLD = 3.0    # ±3%
CONSECUTIVE_THRESHOLD = 3        # 3 days same direction


async def scan_and_alert():
    """Fund intraday P&L alerts are intentionally disabled.

    Yangjibao fund positions expose cumulative unrealized P&L, not reliable
    intraday fund price changes. Pushing these during A-share hours creates
    noisy and misleading alerts.
    """
    return {"ok": True, "skipped": True, "reason": "fund_intraday_pnl_alerts_disabled"}
