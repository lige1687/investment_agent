"""MonitoringAlertSynthesizer integration tests — sync/upsert/disable."""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.alert import PriceAlert
from app.schemas.decision_card import (
    Action,
    ActionVerb,
    DecisionCard,
    DecisionType,
    Target,
    TargetKind,
)
from app.services.monitoring_alert import MonitoringAlertSynthesizer


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


def _card(
    decision_id: str = "dec_test",
    agent: str = "advisor",
    code: str = "001513",
    name: str = "易方达信息产业混合A",
    monitoring: list[str] | None = None,
) -> DecisionCard:
    return DecisionCard(
        decision_id=decision_id,
        agent=agent,
        type=DecisionType.WATCH,
        target=Target(kind=TargetKind.FUND, code=code, name=name),
        action=Action(verb=ActionVerb.HOLD, confidence=0.6),
        monitoring=monitoring or [],
    )


# ── Basic sync ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_writes_one_alert_per_bullet(db_session):
    card = _card(monitoring=[
        "001513 跌破 5.5 减仓一半",
        "022184 涨超 15% 分批止盈",
        "尾盘板块放量下跌立即通知",
    ])
    synth = MonitoringAlertSynthesizer(db_session)
    rows = await synth.sync_from_card(card)
    assert len(rows) == 3

    types = {r.alert_type for r in rows}
    assert "price_below" in types
    assert "change_pct" in types
    assert "technical" in types  # fallback bullet


@pytest.mark.asyncio
async def test_sync_stamps_source_and_source_ref(db_session):
    card = _card(agent="advisor", monitoring=["001513 跌破 5.5"])
    synth = MonitoringAlertSynthesizer(db_session)
    rows = await synth.sync_from_card(card)
    assert rows[0].source == "decision"
    assert rows[0].source_ref == "dec_test"


@pytest.mark.asyncio
async def test_guardian_agent_source_marker(db_session):
    card = _card(agent="guardian", monitoring=["001513 跌破 5.5"])
    synth = MonitoringAlertSynthesizer(db_session)
    rows = await synth.sync_from_card(card)
    assert rows[0].source == "guardian"


@pytest.mark.asyncio
async def test_sync_inherits_target_code_for_headless_bullet(db_session):
    """A bullet with no code but a fund target should attach to the target."""
    card = _card(code="001513", monitoring=["若继续下跌至 -20% 立即通知"])
    synth = MonitoringAlertSynthesizer(db_session)
    rows = await synth.sync_from_card(card)
    assert rows[0].symbol == "001513"
    assert rows[0].alert_type == "change_pct"
    assert rows[0].threshold == -20.0


# ── Idempotency / upsert ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_re_sync_replaces_prior_batch(db_session):
    """A second sync with a different monitoring list should REPLACE, not append."""
    synth = MonitoringAlertSynthesizer(db_session)

    card_v1 = _card(monitoring=["001513 跌破 5.5", "001513 跌破 5.0"])
    await synth.sync_from_card(card_v1)
    v1 = await synth.list_for_decision("dec_test")
    assert len(v1) == 2

    # Same id, new monitoring
    card_v2 = _card(monitoring=["001513 涨破 6.0"])
    await synth.sync_from_card(card_v2)
    v2 = await synth.list_for_decision("dec_test")
    assert len(v2) == 1
    assert v2[0].alert_type == "price_above"

    # Verify no orphan rows on the wider table
    all_rows = (await db_session.execute(select(PriceAlert))).scalars().all()
    assert len(all_rows) == 1


@pytest.mark.asyncio
async def test_empty_monitoring_removes_prior_alerts(db_session):
    synth = MonitoringAlertSynthesizer(db_session)
    await synth.sync_from_card(_card(monitoring=["001513 跌破 5.5"]))
    assert len(await synth.list_for_decision("dec_test")) == 1

    # Card revised with no monitoring — old alerts must be cleared
    await synth.sync_from_card(_card(monitoring=[]))
    assert await synth.list_for_decision("dec_test") == []


# ── Disable batch ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disable_batch_flips_enabled_flag(db_session):
    synth = MonitoringAlertSynthesizer(db_session)
    await synth.sync_from_card(_card(monitoring=[
        "001513 跌破 5.5",
        "001513 涨破 7.0",
    ]))

    n = await synth.disable_batch("dec_test")
    assert n == 2

    rows = await synth.list_for_decision("dec_test")
    assert len(rows) == 2  # still present, just disabled
    assert all(r.enabled is False for r in rows)


# ── Cross-card isolation ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_does_not_touch_other_cards_alerts(db_session):
    """Two decision cards, syncing one must leave the other's alerts alone."""
    synth = MonitoringAlertSynthesizer(db_session)
    await synth.sync_from_card(_card(decision_id="dec_A", monitoring=["001513 跌破 5.5"]))
    await synth.sync_from_card(_card(decision_id="dec_B", monitoring=["022184 涨破 7.0"]))

    # Re-sync A with new conditions — B's alerts must survive
    await synth.sync_from_card(_card(decision_id="dec_A", monitoring=["001513 涨破 6.0"]))

    b_rows = await synth.list_for_decision("dec_B")
    assert len(b_rows) == 1
    assert b_rows[0].symbol == "022184"


# ── DecisionCardStore auto-sync integration ───────────────────────────

@pytest.mark.asyncio
async def test_decision_card_store_auto_syncs_monitoring(db_session):
    """Saving a card via DecisionCardStore should automatically write the
    PriceAlert rows, without the caller having to invoke the synthesizer."""
    from app.services.decision_store import DecisionCardStore

    card = _card(decision_id="dec_auto", monitoring=[
        "001513 跌破 5.5 立即通知",
        "001513 涨破 7.0 减半仓",
    ])
    store = DecisionCardStore(db_session)
    await store.save(card, session_id="sess_auto")

    synth = MonitoringAlertSynthesizer(db_session)
    rows = await synth.list_for_decision("dec_auto")
    assert len(rows) == 2
    assert {r.alert_type for r in rows} == {"price_below", "price_above"}


@pytest.mark.asyncio
async def test_decision_card_store_can_opt_out_of_sync(db_session):
    from app.services.decision_store import DecisionCardStore

    card = _card(decision_id="dec_no_sync", monitoring=["001513 跌破 5.5"])
    store = DecisionCardStore(db_session)
    await store.save(card, session_id="sess_x", sync_monitoring=False)

    synth = MonitoringAlertSynthesizer(db_session)
    assert await synth.list_for_decision("dec_no_sync") == []
