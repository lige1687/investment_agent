"""APScheduler setup with all cron jobs."""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.memory import MemoryJobStore

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(
    jobstores={"default": MemoryJobStore()},
    timezone="Asia/Shanghai",
)


def is_trading_day() -> bool:
    """Check if today is likely a trading day (Mon-Fri, not checking holidays yet)."""
    from datetime import date
    today = date.today()
    return today.weekday() < 5  # Monday=0 ... Friday=4


def is_market_hours() -> bool:
    """Check if currently within A-share market hours (9:30-11:30, 13:00-15:00)."""
    from datetime import datetime
    now = datetime.now()
    morning = now.hour == 9 and now.minute >= 30 or now.hour == 10 or (now.hour == 11 and now.minute <= 30)
    afternoon = now.hour == 13 or now.hour == 14 or (now.hour == 15 and now.minute == 0)
    return morning or afternoon


def setup_scheduler():
    """Register all cron jobs. Call this after FastAPI app starts."""
    from app.tasks import daily_summary, portfolio_eval

    # ── Daily Tasks ──

    # US Overnight Summary: 09:20 Mon-Fri. Uses THS SkillHub via Claude CLI.
    scheduler.add_job(
        daily_summary.us_overnight_push,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=20),
        id="us_overnight_summary",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Morning Session Summary: 12:05 Mon-Fri. Uses THS SkillHub via Claude CLI.
    scheduler.add_job(
        daily_summary.morning_session_push,
        CronTrigger(day_of_week="mon-fri", hour=12, minute=5),
        id="morning_session_summary",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Tail Session Summary: 14:35 Mon-Fri. Uses THS SkillHub via Claude CLI.
    scheduler.add_job(
        daily_summary.tail_session_push,
        CronTrigger(day_of_week="mon-fri", hour=14, minute=35),
        id="tail_session_summary",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Position P&L Update: 15:30 after market close
    scheduler.add_job(
        portfolio_eval.daily_pnl_push,
        CronTrigger(day_of_week="mon-fri", hour=15, minute=30),
        id="daily_pnl",
        replace_existing=True,
    )

    # Portfolio Sync from Yangjibao: 20:00 daily
    scheduler.add_job(
        portfolio_eval.sync_yangjibao,
        CronTrigger(hour=20, minute=0),
        id="yangjibao_sync",
        replace_existing=True,
    )

    # ── Guardian Jobs ──
    # Midday health scan: 11:30 (right after A-share morning close)
    # Close health scan:  14:30 (30 min before final close — decision window)
    # Outcome tracker:    21:00 (roll up 7d/30d hit rates for stored cards)
    from app.config import settings
    if settings.guardian_scheduler_enabled:
        from app.tasks import guardian_tasks
        scheduler.add_job(
            guardian_tasks.run_midday_briefing,
            CronTrigger(day_of_week="mon-fri", hour=11, minute=30),
            id="guardian_midday",
            replace_existing=True,
            misfire_grace_time=600,
        )
        scheduler.add_job(
            guardian_tasks.run_close_briefing,
            CronTrigger(day_of_week="mon-fri", hour=14, minute=30),
            id="guardian_close",
            replace_existing=True,
            misfire_grace_time=600,
        )
        scheduler.add_job(
            guardian_tasks.run_outcome_tracker,
            CronTrigger(hour=21, minute=0),
            id="guardian_outcome_tracker",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("Guardian scheduler jobs registered (11:30 / 14:30 / 21:00)")

    scheduler.start()
    logger.info("APScheduler started")
