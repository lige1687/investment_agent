"""OutcomeTracker — 7d/30d hit-rate scorer for stored decisions.

Runs nightly (21:00 default). For every StoredDecision that:
  - has a fund target (kind=='fund') with a snapshot_price recorded
  - is at least 7 days old and outcome_7d_pct is NULL,
    or at least 30 days old and outcome_30d_pct is NULL

it fetches the current FundProfile.nav, computes the % change since
`snapshot_price`, and writes it back. Signs are absolute NAV movement —
downstream analytics can join with `action_verb` to score whether the
call was directionally right (e.g. BUY_CANDIDATE + positive = win).

We deliberately don't backfill missing snapshots — a decision without a
baseline is not scoreable, period.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import StoredDecision
from app.models.fund import FundProfile

logger = logging.getLogger(__name__)


@dataclass
class OutcomeUpdateStats:
    seven_day_updated: int = 0
    thirty_day_updated: int = 0
    skipped_no_snapshot: int = 0
    skipped_no_price: int = 0
    updated_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "seven_day_updated": self.seven_day_updated,
            "thirty_day_updated": self.thirty_day_updated,
            "skipped_no_snapshot": self.skipped_no_snapshot,
            "skipped_no_price": self.skipped_no_price,
            "updated_ids": self.updated_ids,
        }


class OutcomeTracker:
    """Nightly outcome updater."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def update_outstanding(self, *, now: Optional[datetime] = None) -> OutcomeUpdateStats:
        now = now or datetime.utcnow()
        stats = OutcomeUpdateStats()

        # Only look at fund cards — snapshots for other kinds aren't populated.
        stmt = (
            select(StoredDecision)
            .where(StoredDecision.target_kind == "fund")
            .where(
                (StoredDecision.outcome_7d_pct.is_(None))
                | (StoredDecision.outcome_30d_pct.is_(None))
            )
        )
        result = await self._db.execute(stmt)
        candidates = list(result.scalars().all())

        # Pre-load all current NAVs in one query so we don't hit DB per row.
        codes = {c.target_code for c in candidates if c.target_code}
        nav_map: dict[str, float] = {}
        if codes:
            nav_stmt = select(FundProfile.code, FundProfile.nav).where(FundProfile.code.in_(codes))
            for code, nav in (await self._db.execute(nav_stmt)).all():
                if nav is not None:
                    nav_map[code] = float(nav)

        for row in candidates:
            if row.snapshot_price is None or not row.target_code:
                stats.skipped_no_snapshot += 1
                continue
            current = nav_map.get(row.target_code)
            if current is None:
                stats.skipped_no_price += 1
                continue

            baseline = float(row.snapshot_price)
            if baseline <= 0:
                stats.skipped_no_snapshot += 1
                continue
            pct = (current - baseline) / baseline * 100

            age = now - row.created_at
            updated_here = False

            if row.outcome_7d_pct is None and age >= timedelta(days=7):
                row.outcome_7d_pct = pct
                row.outcome_7d_at = now
                stats.seven_day_updated += 1
                updated_here = True

            if row.outcome_30d_pct is None and age >= timedelta(days=30):
                row.outcome_30d_pct = pct
                row.outcome_30d_at = now
                stats.thirty_day_updated += 1
                updated_here = True

            if updated_here:
                stats.updated_ids.append(row.decision_id)

        try:
            await self._db.flush()
        except Exception as e:
            logger.warning("OutcomeTracker flush failed: %s", e)
        return stats

    async def hit_rate_summary(self, *, days: int = 90) -> dict:
        """Aggregate hit rate for closed 7d/30d windows in the last `days`."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        stmt = (
            select(StoredDecision)
            .where(StoredDecision.created_at >= cutoff)
            .where(StoredDecision.target_kind == "fund")
        )
        rows = (await self._db.execute(stmt)).scalars().all()

        seven = [r for r in rows if r.outcome_7d_pct is not None]
        thirty = [r for r in rows if r.outcome_30d_pct is not None]

        def _win_rate(rows_in: list) -> Optional[float]:
            if not rows_in:
                return None
            wins = sum(1 for r in rows_in if self._is_directional_win(r))
            return wins / len(rows_in)

        return {
            "window_days": days,
            "total_scoreable": len(rows),
            "seven_day": {
                "count": len(seven),
                "win_rate": _win_rate(seven),
                "mean_return_pct": (sum(r.outcome_7d_pct for r in seven) / len(seven)) if seven else None,
            },
            "thirty_day": {
                "count": len(thirty),
                "win_rate": _win_rate(thirty),
                "mean_return_pct": (sum(r.outcome_30d_pct for r in thirty) / len(thirty)) if thirty else None,
            },
        }

    @staticmethod
    def _is_directional_win(row: StoredDecision) -> bool:
        """Whether the return direction matched the action verb.

        BUY-family verbs win on positive returns; SELL/REDUCE-family verbs
        win when the fund fell (they got out in time). HOLD/WATCH don't score.
        """
        pct = row.outcome_7d_pct
        if pct is None:
            pct = row.outcome_30d_pct
        if pct is None:
            return False
        verb = (row.action_verb or "").upper()
        if verb in {"BUY", "ADD"}:
            return pct > 0
        if verb in {"SELL", "REDUCE", "AVOID"}:
            return pct < 0
        return False  # HOLD / WATCH are neutral
