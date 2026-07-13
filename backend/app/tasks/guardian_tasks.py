"""APScheduler wrappers for Guardian jobs.

Kept thin — each function opens its own DB session, invokes the service,
and logs. Real logic lives in `app.services.guardian` and
`app.services.outcome_tracker`.
"""
from __future__ import annotations

import logging

from app.database import async_session
from app.schemas.guardian import BriefingSlot
from app.services.guardian import GuardianAgent
from app.services.outcome_tracker import OutcomeTracker

logger = logging.getLogger(__name__)


async def _run_briefing(slot: BriefingSlot) -> None:
    async with async_session() as session:
        try:
            agent = GuardianAgent(session, slot=slot)
            result = await agent.run()
            await session.commit()
            logger.info(
                "Guardian %s done: alerts=%d decisions=%d pushed=%s",
                slot.value, len(result.alerts), len(result.decision_ids),
                result.pushed_to_feishu,
            )
        except Exception:
            logger.exception("Guardian %s crashed", slot.value)
            await session.rollback()


async def run_midday_briefing() -> None:
    """11:30 job — 午盘体检."""
    await _run_briefing(BriefingSlot.MIDDAY)


async def run_close_briefing() -> None:
    """14:30 job — 尾盘体检."""
    await _run_briefing(BriefingSlot.CLOSE)


async def run_outcome_tracker() -> None:
    """21:00 job — update 7d/30d outcome for stored decisions."""
    async with async_session() as session:
        try:
            tracker = OutcomeTracker(session)
            stats = await tracker.update_outstanding()
            await session.commit()
            logger.info(
                "OutcomeTracker: 7d updated=%d, 30d updated=%d, "
                "skipped(no_snapshot)=%d, skipped(no_price)=%d",
                stats.seven_day_updated, stats.thirty_day_updated,
                stats.skipped_no_snapshot, stats.skipped_no_price,
            )
        except Exception:
            logger.exception("OutcomeTracker crashed")
            await session.rollback()
