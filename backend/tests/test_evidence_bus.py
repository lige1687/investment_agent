"""EvidenceBus — store/retrieve, session scoping, freshness."""
import asyncio
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.evidence import Evidence
from app.services.evidence_bus import EvidenceBus, EvidenceRecord


@pytest_asyncio.fixture
async def db_session():
    import app.models  # noqa: F401 — register all models
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


@pytest.mark.asyncio
async def test_store_returns_record_with_stable_id_shape(db_session):
    bus = EvidenceBus(db_session, session_id="sess_x")
    rec = await bus.store(
        source="get_portfolio_summary",
        query={"detail": True},
        data='{"total": 1000}',
    )
    assert rec.ev_id.startswith("ev_")
    assert len(rec.ev_id) >= 10  # ev_ + 10 hex
    assert rec.session_id == "sess_x"
    assert rec.source == "get_portfolio_summary"
    assert rec.data == '{"total": 1000}'
    assert rec.ttl_seconds == 300  # default


@pytest.mark.asyncio
async def test_get_hits_cache_before_db(db_session):
    bus = EvidenceBus(db_session, session_id="sess_x")
    rec = await bus.store(source="foo", query={}, data="bar")

    # Fetch by id — cached
    got = await bus.get(rec.ev_id)
    assert got is not None
    assert got.ev_id == rec.ev_id
    assert got.data == "bar"


@pytest.mark.asyncio
async def test_get_falls_through_to_db_across_bus_instances(db_session):
    """A second bus instance (different in-memory cache) should still find
    evidence written by the first."""
    bus1 = EvidenceBus(db_session, session_id="sess_a")
    rec = await bus1.store(source="foo", query={}, data="payload")

    bus2 = EvidenceBus(db_session, session_id="sess_a")
    assert not bus2._cache
    got = await bus2.get(rec.ev_id)
    assert got is not None
    assert got.data == "payload"


@pytest.mark.asyncio
async def test_get_returns_none_for_unknown_id(db_session):
    bus = EvidenceBus(db_session, session_id="sess_x")
    assert await bus.get("ev_missing") is None


@pytest.mark.asyncio
async def test_list_session_orders_newest_first_and_filters_by_session(db_session):
    bus_a = EvidenceBus(db_session, session_id="sess_a")
    r1 = await bus_a.store(source="s1", query={}, data="d1")
    await asyncio.sleep(0.01)
    r2 = await bus_a.store(source="s2", query={}, data="d2")

    bus_b = EvidenceBus(db_session, session_id="sess_b")
    await bus_b.store(source="s3", query={}, data="d3")

    listing = await bus_a.list_session(limit=10)
    ids = [r.ev_id for r in listing]
    assert r2.ev_id in ids
    assert r1.ev_id in ids
    assert not any(r.source == "s3" for r in listing), "cross-session leak"
    # r2 was written second → should come first
    assert ids[0] == r2.ev_id


@pytest.mark.asyncio
async def test_query_json_round_trips_dict(db_session):
    bus = EvidenceBus(db_session, session_id="sess_x")
    query = {"code": "022184", "period": "1y"}
    rec = await bus.store(source="detail", query=query, data="{}")
    assert rec.query == query


@pytest.mark.asyncio
async def test_data_is_truncated_when_over_limit(db_session):
    from app.services.evidence_bus import MAX_STORED_DATA_CHARS
    huge = "x" * (MAX_STORED_DATA_CHARS + 5000)
    bus = EvidenceBus(db_session, session_id="sess_x")
    rec = await bus.store(source="huge", query={}, data=huge)
    assert len(rec.data) < len(huge)
    assert "[truncated" in rec.data


def test_is_fresh_true_when_within_ttl():
    rec = EvidenceRecord(
        ev_id="ev_1", session_id="s", agent="advisor", source="x",
        query={}, data="", summary=None,
        fetched_at=datetime.utcnow() - timedelta(seconds=10),
        ttl_seconds=60,
    )
    assert rec.is_fresh


def test_is_fresh_false_when_ttl_expired():
    rec = EvidenceRecord(
        ev_id="ev_1", session_id="s", agent="advisor", source="x",
        query={}, data="", summary=None,
        fetched_at=datetime.utcnow() - timedelta(seconds=120),
        ttl_seconds=60,
    )
    assert not rec.is_fresh


def test_is_fresh_true_when_ttl_zero():
    """ttl_seconds=0 means the evidence is permanent."""
    rec = EvidenceRecord(
        ev_id="ev_1", session_id="s", agent="advisor", source="x",
        query={}, data="", summary=None,
        fetched_at=datetime.utcnow() - timedelta(days=365),
        ttl_seconds=0,
    )
    assert rec.is_fresh
