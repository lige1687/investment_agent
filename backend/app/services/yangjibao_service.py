"""Yangjibao business service."""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.yangjibao import YangjibaoToken
from app.yangjibao.client import YangjibaoClient
from app.yangjibao.auth import qr_manager, QRStatus
from app.yangjibao.portfolio import PortfolioSync

logger = logging.getLogger(__name__)


class YangjibaoService:
    """Service for Yangjibao QR login + portfolio sync."""

    def __init__(self, db: AsyncSession):
        self._db = db

    # ── Status ──

    async def get_status(self) -> dict:
        """Check connection status."""
        # Check if we have a stored token
        stmt = select(YangjibaoToken).order_by(YangjibaoToken.created_at.desc()).limit(1)
        result = await self._db.execute(stmt)
        token_record = result.scalar_one_or_none()

        return {
            "connected": token_record is not None,
            "has_active_session": qr_manager.active_session is not None,
            "qr_status": qr_manager.active_session.status.value if qr_manager.active_session else None,
        }

    async def _get_stored_token(self) -> str | None:
        stmt = select(YangjibaoToken).order_by(YangjibaoToken.created_at.desc()).limit(1)
        result = await self._db.execute(stmt)
        record = result.scalar_one_or_none()
        return record.access_token if record else None

    # ── QR Login ──

    async def start_qr_login(self) -> dict:
        """Start QR login. Returns QR image base64."""
        session = await qr_manager.start_login()
        return {
            "qr_id": session.qr_id,
            "qr_image": session.qr_image_base64,
            "expires_in": session.expires_in,
            "status": session.status.value,
        }

    async def check_qr_login(self) -> dict:
        """Poll QR status. On confirmed, saves token to DB."""
        session = await qr_manager.poll_status()

        result = {"status": session.status.value}

        if session.status == QRStatus.CONFIRMED and session.access_token:
            # Save token to DB
            self._db.add(YangjibaoToken(
                access_token=session.access_token,
                token_type="bearer",
                raw_response=str({"source": "qr_login"}),
            ))
            await self._db.flush()
            result["connected"] = True
            qr_manager.reset()

        return result

    # ── Portfolio Sync ──

    async def sync_portfolio(self) -> dict:
        """Sync portfolio from Yangjibao. Requires valid token."""
        token = await self._get_stored_token()
        if not token:
            return {
                "success": False,
                "positions_count": 0,
                "total_value": 0.0,
                "new_transactions": 0,
                "error": "not_authenticated",
            }

        sync = PortfolioSync(self._db)
        return await sync.sync(token)

    async def get_local_portfolio(self) -> dict:
        """Get locally cached portfolio."""
        from app.models.position import Position
        from app.models.fund import FundProfile

        stmt = select(Position).where(Position.source == "yangjibao")
        result = await self._db.execute(stmt)
        positions = result.scalars().all()

        # Load fund names
        codes = [p.symbol for p in positions]
        name_map = {}
        if codes:
            stmt2 = select(FundProfile.code, FundProfile.name).where(FundProfile.code.in_(codes))
            result2 = await self._db.execute(stmt2)
            name_map = {code: name for code, name in result2.all()}

        total_value = sum(p.market_value or 0 for p in positions)
        total_cost = sum(p.cost_basis or (p.shares * p.avg_cost) for p in positions)
        total_pnl = total_value - total_cost

        synced_at = max((p.updated_at for p in positions if p.updated_at), default=None)
        return {
            "connected": await self._get_stored_token() is not None,
            "total_value": total_value,
            "total_cost": total_cost,
            "total_pnl": total_pnl,
            "total_pnl_pct": (total_pnl / total_cost * 100) if total_cost > 0 else 0,
            "synced_at": synced_at.isoformat() if synced_at else None,
            "positions": [
                {
                    "symbol": p.symbol,
                    "name": name_map.get(p.symbol, p.symbol),
                    "type": p.position_type,
                    "shares": p.shares,
                    "avg_cost": p.avg_cost,
                    "current_price": p.current_price,
                    "market_value": p.market_value,
                    "unrealized_pnl": p.unrealized_pnl,
                    "unrealized_pnl_pct": p.unrealized_pnl_pct,
                }
                for p in positions
            ],
        }
