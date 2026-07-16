"""Portfolio sync from Yangjibao browser-plug-api to local SQLite.

Real data mapping from yjbHoldingToMutualRow / yjbHoldingToEstimateSnapshot
in the original Fund-Holdings-Tracker project.
"""

import logging
import re
from datetime import date, datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.position import Position
from app.models.fund import FundProfile
from app.yangjibao.client import YangjibaoClient

logger = logging.getLogger(__name__)


def _clean_code(raw: str) -> str:
    """Extract 6-digit fund code."""
    return re.sub(r"\D", "", str(raw))[:6]


def _parse_estimate(nv: dict) -> tuple[float | None, float | None]:
    """Parse intraday estimate fields from a Yangjibao ``nv_info`` block.

    Returns ``(gsz, gszzl)`` where ``gsz`` is the estimated NAV and
    ``gszzl`` is the estimated change percent (may be ``None`` when absent).
    """
    gsz_raw = nv.get("gsz", nv.get("vgsz", nv.get("zsgz", 0)))
    gsz = float(gsz_raw) if gsz_raw not in (None, "") else None
    gszzl_raw = nv.get("gszzl") or nv.get("vgszzl") or nv.get("zsgzzl")
    gszzl = float(gszzl_raw) if gszzl_raw not in (None, "") else None
    return gsz, gszzl


class PortfolioSync:
    """Sync Yangjibao holdings to local database."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def sync(self, token: str) -> dict:
        """Full sync: fetch holdings from Yangjibao and save to DB.

        Args:
            token: Yangjibao access token from QR login.
        """
        result = {
            "success": False,
            "positions_count": 0,
            "total_value": 0.0,
            "new_transactions": 0,
            "error": None,
        }

        try:
            client = YangjibaoClient(token=token)
            holdings = await client.get_all_holdings()

            total_value = 0.0
            for h in holdings:
                code = _clean_code(h.get("code", ""))
                if len(code) != 6:
                    continue

                # Parse fields (matching yjbHoldingToMutualRow)
                name = str(h.get("short_name", "") or f"基金{code}")
                shares = float(h.get("hold_share", 0))
                cost_price = float(h.get("hold_cost", 0))
                money = float(h.get("money", 0))

                nv = h.get("nv_info", {}) or {}
                dwjz = (
                    float(nv.get("dwjz", 0))
                    if nv.get("dwjz") not in (None, "")
                    else 0.0
                )
                gsz, gszzl = _parse_estimate(nv)
                jzrq = str(nv.get("jzrq", ""))[:10] if nv.get("jzrq") else ""

                # Cost fallback
                if not (cost_price > 0) and dwjz > 0:
                    cost_price = dwjz
                if not (cost_price > 0):
                    continue

                # Market value
                market_value = (
                    money if money > 0 else shares * (gsz or dwjz or cost_price)
                )
                cost_basis = shares * cost_price
                unrealized_pnl = market_value - cost_basis

                total_value += market_value

                # Determine if ETF
                position_type = "etf" if code.startswith(("51", "15", "58")) else "fund"

                # Upsert position
                stmt = select(Position).where(
                    Position.symbol == code,
                    Position.position_type == position_type,
                )
                res = await self._db.execute(stmt)
                existing = res.scalar_one_or_none()

                if existing:
                    existing.shares = shares
                    existing.avg_cost = cost_price
                    existing.current_price = gsz or dwjz
                    existing.market_value = market_value
                    existing.cost_basis = cost_basis
                    existing.unrealized_pnl = unrealized_pnl
                    existing.unrealized_pnl_pct = (
                        (unrealized_pnl / cost_basis * 100) if cost_basis > 0 else 0
                    )
                    existing.source = "yangjibao"
                    existing.updated_at = datetime.utcnow()
                    existing.estimated_change_pct = gszzl
                    existing.estimated_nav = gsz or dwjz
                    existing.estimated_at = datetime.utcnow()
                else:
                    self._db.add(
                        Position(
                            symbol=code,
                            position_type=position_type,
                            shares=shares,
                            avg_cost=cost_price,
                            current_price=gsz or dwjz,
                            market_value=market_value,
                            cost_basis=cost_basis,
                            unrealized_pnl=unrealized_pnl,
                            unrealized_pnl_pct=(
                                (unrealized_pnl / cost_basis * 100)
                                if cost_basis > 0
                                else 0
                            ),
                            estimated_change_pct=gszzl,
                            estimated_nav=gsz or dwjz,
                            estimated_at=datetime.utcnow(),
                            source="yangjibao",
                        )
                    )

                # Cache fund profile
                await self._cache_fund(code, name, h, nv, jzrq, dwjz)

            await self._db.flush()

            result.update(
                {
                    "success": True,
                    "positions_count": len(holdings),
                    "total_value": total_value,
                }
            )
            logger.info(
                f"Yangjibao sync: {len(holdings)} holdings, total value={total_value:.2f}"
            )

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Yangjibao sync failed: {e}")

        return result

    async def _cache_fund(
        self, code: str, name: str, h: dict, nv: dict, jzrq: str, dwjz: float
    ):
        """Cache fund profile info."""
        stmt = select(FundProfile).where(FundProfile.code == code)
        res = await self._db.execute(stmt)
        existing = res.scalar_one_or_none()

        if not existing:
            nav_date = None
            if jzrq:
                try:
                    nav_date = date.fromisoformat(jzrq)
                except (ValueError, TypeError):
                    pass

            self._db.add(
                FundProfile(
                    code=code,
                    name=name,
                    fund_type="etf" if code.startswith(("51", "15", "58")) else "stock",
                    nav=dwjz if dwjz > 0 else None,
                    nav_date=nav_date,
                    fund_company=str(h.get("company", "")),
                    raw_data=str(h),
                )
            )
