"""DecisionCardStore — persistence, session listing, lifecycle updates."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.schemas.decision_card import (
    Action,
    ActionVerb,
    DecisionCard,
    DecisionType,
    Dimension,
    DimensionKey,
    Target,
    TargetKind,
)
from app.services.decision_store import DecisionCardStore


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


def _card(decision_id="dec_1", agent="advisor", verb=ActionVerb.BUY) -> DecisionCard:
    return DecisionCard(
        decision_id=decision_id,
        agent=agent,
        type=DecisionType.BUY_CANDIDATE,
        target=Target(kind=TargetKind.FUND, code="006503", name="财通集成电路"),
        action=Action(verb=verb, confidence=0.7),
        dimensions=[
            Dimension(key=DimensionKey.TECHNICAL, score=8, signal="up", evidence_ref="ev_a"),
        ],
    )


@pytest.mark.asyncio
async def test_save_new_card_persists_all_fields(db_session):
    store = DecisionCardStore(db_session)
    card = _card()
    stored_id = await store.save(card, session_id="sess_x")
    assert stored_id > 0

    got = await store.get_by_id("dec_1")
    assert got is not None
    assert got.target.code == "006503"
    assert got.dimensions[0].evidence_ref == "ev_a"


@pytest.mark.asyncio
async def test_save_upserts_when_same_decision_id(db_session):
    """Re-emitting a card with the same decision_id should overwrite,
    not raise a unique-constraint error."""
    store = DecisionCardStore(db_session)
    original = _card(verb=ActionVerb.BUY)
    first_id = await store.save(original, session_id="sess_x")

    revised = _card(verb=ActionVerb.WATCH)
    second_id = await store.save(revised, session_id="sess_x")

    assert first_id == second_id  # same row
    got = await store.get_by_id("dec_1")
    assert got.action.verb == "WATCH"


@pytest.mark.asyncio
async def test_list_session_returns_newest_first(db_session):
    store = DecisionCardStore(db_session)
    await store.save(_card(decision_id="dec_a"), session_id="sess_x")
    await store.save(_card(decision_id="dec_b"), session_id="sess_x")
    await store.save(_card(decision_id="dec_c"), session_id="sess_other")

    listing = await store.list_session("sess_x", limit=10)
    ids = [c.decision_id for c in listing]
    assert set(ids) == {"dec_a", "dec_b"}
    # dec_b saved after dec_a → should be first
    assert ids[0] == "dec_b"


@pytest.mark.asyncio
async def test_mark_user_action_updates_lifecycle(db_session):
    store = DecisionCardStore(db_session)
    await store.save(_card(decision_id="dec_x"), session_id="sess_x")

    row = await store.mark_user_action("dec_x", "accepted")
    assert row is not None
    assert row.user_action == "accepted"
    assert row.user_action_at is not None


@pytest.mark.asyncio
async def test_mark_user_action_rejects_invalid_action(db_session):
    store = DecisionCardStore(db_session)
    await store.save(_card(decision_id="dec_x"), session_id="sess_x")

    with pytest.raises(ValueError):
        await store.mark_user_action("dec_x", "yolo")


@pytest.mark.asyncio
async def test_mark_user_action_returns_none_for_unknown_id(db_session):
    store = DecisionCardStore(db_session)
    result = await store.mark_user_action("dec_missing", "accepted")
    assert result is None
