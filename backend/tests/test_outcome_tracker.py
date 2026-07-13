"""OutcomeTracker — 7d/30d NAV comparison writeback."""
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.evidence import StoredDecision
from app.models.fund import FundProfile
from app.services.outcome_tracker import OutcomeTracker


@pytest_asyncio.fixture
async def db_session():
    import app.models  # noqa: F401
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed_fund(db, code: str, nav: float):
    db.add(FundProfile(code=code, name=f"Fund {code}", nav=nav))
    await db.flush()


async def _seed_decision(
    db,
    *,
    decision_id: str,
    code: str,
    action_verb: str = "BUY",
    snapshot_price: float | None = 1.0,
    created_offset_days: int = 8,
    card_type: str = "BUY_CANDIDATE",
):
    """Create a stored decision from N days ago."""
    now = datetime.utcnow()
    row = StoredDecision(
        decision_id=decision_id,
        session_id=f"sess_{decision_id}",
        agent="advisor",
        type=card_type,
        target_kind="fund",
        target_code=code,
        target_name=f"Fund {code}",
        action_verb=action_verb,
        confidence=0.6,
        card_json="{}",
        created_at=now - timedelta(days=created_offset_days),
        snapshot_price=snapshot_price,
        snapshot_at=now - timedelta(days=created_offset_days),
    )
    db.add(row)
    await db.flush()
    return row


@pytest.mark.asyncio
async def test_seven_day_window_updates_when_age_over_7d(db_session):
    await _seed_fund(db_session, "F001", nav=1.10)
    await _seed_decision(
        db_session, decision_id="dec_a", code="F001",
        snapshot_price=1.00, created_offset_days=8,
    )

    tracker = OutcomeTracker(db_session)
    stats = await tracker.update_outstanding()

    assert stats.seven_day_updated == 1
    assert stats.thirty_day_updated == 0

    from sqlalchemy import select
    row = (await db_session.execute(
        select(StoredDecision).where(StoredDecision.decision_id == "dec_a")
    )).scalar_one()
    # +10% NAV move
    assert row.outcome_7d_pct is not None
    assert abs(row.outcome_7d_pct - 10.0) < 0.01
    assert row.outcome_30d_pct is None  # not old enough


@pytest.mark.asyncio
async def test_seven_day_not_updated_before_7d_age(db_session):
    await _seed_fund(db_session, "F001", nav=1.20)
    await _seed_decision(
        db_session, decision_id="dec_early", code="F001",
        snapshot_price=1.00, created_offset_days=3,
    )
    tracker = OutcomeTracker(db_session)
    stats = await tracker.update_outstanding()
    assert stats.seven_day_updated == 0


@pytest.mark.asyncio
async def test_thirty_day_window_also_populates_seven_day(db_session):
    """A card older than 30 days should get BOTH windows filled in one pass."""
    await _seed_fund(db_session, "F001", nav=1.30)
    await _seed_decision(
        db_session, decision_id="dec_old", code="F001",
        snapshot_price=1.00, created_offset_days=45,
    )
    tracker = OutcomeTracker(db_session)
    stats = await tracker.update_outstanding()
    assert stats.seven_day_updated == 1
    assert stats.thirty_day_updated == 1


@pytest.mark.asyncio
async def test_missing_snapshot_is_skipped(db_session):
    """Cards without a baseline price can't be scored — must be skipped, not crash."""
    await _seed_fund(db_session, "F001", nav=1.50)
    await _seed_decision(
        db_session, decision_id="dec_no_snap", code="F001",
        snapshot_price=None, created_offset_days=20,
    )
    tracker = OutcomeTracker(db_session)
    stats = await tracker.update_outstanding()
    assert stats.skipped_no_snapshot == 1
    assert stats.seven_day_updated == 0


@pytest.mark.asyncio
async def test_missing_current_price_is_skipped(db_session):
    """Fund vanished from FundProfile — skip and count."""
    await _seed_decision(
        db_session, decision_id="dec_no_price", code="F_ghost",
        snapshot_price=1.00, created_offset_days=20,
    )
    tracker = OutcomeTracker(db_session)
    stats = await tracker.update_outstanding()
    assert stats.skipped_no_price == 1


@pytest.mark.asyncio
async def test_negative_return_recorded_correctly(db_session):
    await _seed_fund(db_session, "F001", nav=0.90)
    await _seed_decision(
        db_session, decision_id="dec_loss", code="F001",
        snapshot_price=1.00, created_offset_days=8,
    )
    tracker = OutcomeTracker(db_session)
    await tracker.update_outstanding()

    from sqlalchemy import select
    row = (await db_session.execute(
        select(StoredDecision).where(StoredDecision.decision_id == "dec_loss")
    )).scalar_one()
    assert row.outcome_7d_pct is not None
    assert abs(row.outcome_7d_pct - (-10.0)) < 0.01


@pytest.mark.asyncio
async def test_already_scored_not_touched_again(db_session):
    """A card with outcome_7d_pct set is skipped by the query filter."""
    await _seed_fund(db_session, "F001", nav=1.10)
    row = await _seed_decision(
        db_session, decision_id="dec_done", code="F001",
        snapshot_price=1.00, created_offset_days=10,
    )
    row.outcome_7d_pct = 999.0  # sentinel value
    row.outcome_7d_at = datetime.utcnow()
    await db_session.flush()

    tracker = OutcomeTracker(db_session)
    stats = await tracker.update_outstanding()
    # No 7d update this pass (already had a value); 30d also not since <30d
    assert stats.seven_day_updated == 0

    from sqlalchemy import select
    got = (await db_session.execute(
        select(StoredDecision).where(StoredDecision.decision_id == "dec_done")
    )).scalar_one()
    assert got.outcome_7d_pct == 999.0  # unchanged


@pytest.mark.asyncio
async def test_hit_rate_summary_directional_wins(db_session):
    """BUY that made money = win; SELL that dodged loss = win; HOLD is neutral."""
    await _seed_fund(db_session, "F_up", nav=1.10)
    await _seed_fund(db_session, "F_down", nav=0.90)
    await _seed_fund(db_session, "F_flat", nav=1.00)

    # BUY that went up → win
    await _seed_decision(
        db_session, decision_id="d1", code="F_up",
        action_verb="BUY", snapshot_price=1.00, created_offset_days=8,
    )
    # SELL of something that went down → win
    await _seed_decision(
        db_session, decision_id="d2", code="F_down",
        action_verb="SELL", snapshot_price=1.00, created_offset_days=8,
    )
    # BUY that went down → loss
    await _seed_decision(
        db_session, decision_id="d3", code="F_down",
        action_verb="BUY", snapshot_price=1.00, created_offset_days=8,
    )
    # HOLD of flat → not counted as win
    await _seed_decision(
        db_session, decision_id="d4", code="F_flat",
        action_verb="HOLD", snapshot_price=1.00, created_offset_days=8,
    )

    tracker = OutcomeTracker(db_session)
    await tracker.update_outstanding()
    summary = await tracker.hit_rate_summary(days=90)

    assert summary["seven_day"]["count"] == 4
    # 2 wins out of 4
    assert summary["seven_day"]["win_rate"] is not None
    assert abs(summary["seven_day"]["win_rate"] - 0.5) < 0.01
