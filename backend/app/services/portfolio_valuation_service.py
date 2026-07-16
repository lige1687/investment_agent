"""Portfolio realtime valuation service.

Provides intraday estimated valuation for holdings, preferring live
Yangjibao data and falling back to DB-cached positions (marked stale)
when the live token is unavailable or the API errors.

Trust boundary: stale estimates are never presented as fresh. When the
live path fails, every row is tagged ``stale=True`` so callers (push
notifications, alerts) can communicate the delay honestly.
"""

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.position import Position
from app.models.fund import FundProfile
from app.models.yangjibao import YangjibaoToken
from app.yangjibao.client import YangjibaoClient
from app.yangjibao.portfolio import _clean_code, _parse_estimate

logger = logging.getLogger(__name__)


class PortfolioValuationService:
    """Live portfolio valuation with DB-cache fallback."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def get_live_valuation(self) -> list[dict]:
        """Return per-holding valuation rows.

        Tries live Yangjibao holdings first; on ANY failure (no token,
        invalid token, network error, parse error) falls back to DB-cached
        positions and marks every row ``stale=True``.

        Never raises - always returns a list (possibly empty, possibly stale).
        """
        rows = await self._try_live()
        if rows is not None:
            return rows
        return await self._fallback_db()

    # ── live path ──

    async def _try_live(self) -> list[dict] | None:
        """Attempt live valuation. Returns None when live path is unavailable."""
        try:
            token = await self._get_stored_token()
            if not token:
                logger.info(
                    "PortfolioValuation: no stored token, falling back to DB cache"
                )
                return None

            client = YangjibaoClient(token=token)
            holdings = await client.get_all_holdings()

            rows: list[dict] = []
            for h in holdings:
                code = _clean_code(h.get("code", ""))
                if len(code) != 6:
                    continue

                nv = h.get("nv_info", {}) or {}
                gsz, gszzl = _parse_estimate(nv)
                dwjz = (
                    float(nv.get("dwjz", 0))
                    if nv.get("dwjz") not in (None, "")
                    else 0.0
                )
                money = float(h.get("money", 0))
                shares = float(h.get("hold_share", 0))

                market_value = money if money > 0 else shares * (gsz or dwjz)
                name = str(h.get("short_name", "") or code)
                position_type = "etf" if code.startswith(("51", "15", "58")) else "fund"

                rows.append(
                    {
                        "symbol": code,
                        "name": name,
                        "position_type": position_type,
                        "market_value": market_value,
                        "unrealized_pnl_pct": None,
                        "today_estimated_pct": gszzl,
                        "estimated_at": datetime.utcnow().isoformat(),
                        "stale": False,
                    }
                )

            return rows

        except Exception as e:
            reason = str(e)[:200]
            logger.info(
                "PortfolioValuation: live fetch failed (%s), falling back to DB cache",
                reason,
            )
            return None

    # ── DB fallback path ──

    async def _fallback_db(self) -> list[dict]:
        """Build valuation rows from cached Position rows, marked stale."""
        stmt = select(Position).where(Position.source == "yangjibao")
        result = await self._db.execute(stmt)
        positions = result.scalars().all()

        codes = [p.symbol for p in positions]
        name_map = await self._load_fund_names(codes)

        rows: list[dict] = []
        for p in positions:
            rows.append(
                {
                    "symbol": p.symbol,
                    "name": name_map.get(p.symbol, p.symbol),
                    "position_type": p.position_type,
                    "market_value": p.market_value,
                    "unrealized_pnl_pct": p.unrealized_pnl_pct,
                    "today_estimated_pct": p.estimated_change_pct,
                    "estimated_at": (
                        p.estimated_at.isoformat() if p.estimated_at else None
                    ),
                    "stale": True,
                }
            )
        return rows

    # ── helpers ──

    async def _get_stored_token(self) -> str | None:
        """Return the most recent stored Yangjibao token, or None."""
        stmt = (
            select(YangjibaoToken).order_by(YangjibaoToken.created_at.desc()).limit(1)
        )
        result = await self._db.execute(stmt)
        record = result.scalar_one_or_none()
        return record.access_token if record else None

    async def _load_fund_names(self, codes: list[str]) -> dict[str, str]:
        """Map fund codes to display names from FundProfile."""
        if not codes:
            return {}
        stmt = select(FundProfile.code, FundProfile.name).where(
            FundProfile.code.in_(codes)
        )
        result = await self._db.execute(stmt)
        return {code: name for code, name in result.all()}
