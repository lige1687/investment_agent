"""Yangjibao REST API endpoints."""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.portfolio_valuation_hook import record_synced_valuation
from app.services.yangjibao_service import YangjibaoService

router = APIRouter(prefix="/yangjibao", tags=["Yangjibao"])
logger = logging.getLogger(__name__)


@router.get("/status")
async def get_status(db: AsyncSession = Depends(get_db)):
    """Check Yangjibao connection status."""
    service = YangjibaoService(db)
    return await service.get_status()


@router.post("/login")
async def start_qr_login(db: AsyncSession = Depends(get_db)):
    """Start QR code login flow.

    Returns a QR code image (base64 PNG) that the user scans
    with their Yangjibao app to authorize.
    """
    service = YangjibaoService(db)
    return await service.start_qr_login()


@router.get("/login/check")
async def check_qr_login(db: AsyncSession = Depends(get_db)):
    """Poll QR code scan status.

    Call this repeatedly (every 2-3 seconds) until status is
    'confirmed' (success), 'expired', or 'failed'.
    """
    service = YangjibaoService(db)
    return await service.check_qr_login()


@router.post("/sync")
async def sync_portfolio(db: AsyncSession = Depends(get_db)):
    """Manually trigger portfolio sync from Yangjibao.

    Fetches latest positions and transactions, stores in local DB.
    On success, records an account-valuation snapshot so drawdown math
    has trusted data to work with.
    """
    service = YangjibaoService(db)
    result = await service.sync_portfolio()
    if result.get("success"):
        try:
            await record_synced_valuation(db)
        except Exception:  # 快照失败不阻塞主流程
            logger.exception("valuation snapshot failed")
    return result


@router.get("/portfolio")
async def get_local_portfolio(db: AsyncSession = Depends(get_db)):
    """Get locally cached portfolio from last Yangjibao sync."""
    service = YangjibaoService(db)
    return await service.get_local_portfolio()
