"""EvidenceBus — the session-scoped registry of tool outputs.

Every tool/skill invocation that the agent makes is snapshot'd here and
handed back a short `ev_id`. Decision cards reference those ids; follow-up
questions in the same session can inspect them without paying to re-fetch.

Two-tier design:
  1. In-memory dict on the bus instance (fast lookups within one request)
  2. `agent_evidence` table (survives across API requests within a session)

The bus is meant to be constructed once per InvestmentAgent instance;
`session_id` is what makes evidence cross request boundaries.
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import Evidence

logger = logging.getLogger(__name__)

# Cap what we write to disk — the tool result may already be truncated by the
# caller, but we want a defense in depth against runaway payloads.
MAX_STORED_DATA_CHARS = 32_000


@dataclass(frozen=True)
class EvidenceRecord:
    """Read-model returned to callers. Immutable snapshot."""
    ev_id: str
    session_id: str
    agent: str
    source: str
    query: dict[str, Any]
    data: str
    summary: Optional[str]
    fetched_at: datetime
    ttl_seconds: int

    @property
    def is_fresh(self) -> bool:
        if self.ttl_seconds == 0:
            return True
        return datetime.utcnow() < self.fetched_at + timedelta(seconds=self.ttl_seconds)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ev_id": self.ev_id,
            "session_id": self.session_id,
            "agent": self.agent,
            "source": self.source,
            "query": self.query,
            "data": self.data,
            "summary": self.summary,
            "fetched_at": self.fetched_at.isoformat(timespec="seconds"),
            "ttl_seconds": self.ttl_seconds,
            "is_fresh": self.is_fresh,
        }


def _short_id(source: str, seed: str = "") -> str:
    """Produce a stable-ish short id: ev_<10-hex>.

    We mix in `secrets.token_hex(3)` so identical (source, query) pairs
    called twice in a row still get distinct ids — evidence is versioned
    by time-of-fetch, not by content hash.
    """
    salt = seed or secrets.token_hex(3)
    h = hashlib.blake2b(f"{source}|{salt}".encode("utf-8"), digest_size=5).hexdigest()
    return f"ev_{h}"


def _truncate(text: str, limit: int = MAX_STORED_DATA_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


def _to_query_json(query: Any) -> str:
    try:
        return json.dumps(query, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return json.dumps({"repr": repr(query)}, ensure_ascii=False)


class EvidenceBus:
    """Session-scoped evidence registry."""

    def __init__(self, db: AsyncSession, session_id: str, agent: str = "advisor"):
        self._db = db
        self.session_id = session_id
        self.agent = agent
        self._cache: dict[str, EvidenceRecord] = {}

    async def store(
        self,
        source: str,
        query: Any,
        data: str,
        *,
        summary: Optional[str] = None,
        ttl_seconds: int = 300,
    ) -> EvidenceRecord:
        """Register a new evidence snapshot. Returns the immutable record."""
        ev_id = _short_id(source)
        # Collision defense — cache lookup is cheap, DB lookup only on miss.
        while ev_id in self._cache:
            ev_id = _short_id(source)

        stored_data = _truncate(data)
        row = Evidence(
            ev_id=ev_id,
            session_id=self.session_id,
            agent=self.agent,
            source=source,
            query_json=_to_query_json(query),
            data_json=stored_data,
            summary=(summary or "")[:240] if summary else None,
            fetched_at=datetime.utcnow(),
            ttl_seconds=ttl_seconds,
        )
        self._db.add(row)
        try:
            await self._db.flush()
        except Exception as e:
            # Non-fatal — we still keep the in-memory copy so the current
            # turn can succeed, but future sessions won't see it.
            logger.warning("EvidenceBus: DB flush failed for %s: %s", ev_id, e)

        record = EvidenceRecord(
            ev_id=ev_id,
            session_id=self.session_id,
            agent=self.agent,
            source=source,
            query=self._parse_query(row.query_json),
            data=stored_data,
            summary=row.summary,
            fetched_at=row.fetched_at,
            ttl_seconds=row.ttl_seconds,
        )
        self._cache[ev_id] = record
        return record

    async def get(self, ev_id: str) -> Optional[EvidenceRecord]:
        """Look up by id — memory first, then DB (any session)."""
        cached = self._cache.get(ev_id)
        if cached is not None:
            return cached

        stmt = select(Evidence).where(Evidence.ev_id == ev_id).limit(1)
        result = await self._db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None

        record = self._row_to_record(row)
        self._cache[ev_id] = record
        return record

    async def list_session(
        self,
        *,
        limit: int = 50,
        only_fresh: bool = False,
    ) -> list[EvidenceRecord]:
        """Recent evidence for this session, newest first."""
        stmt = (
            select(Evidence)
            .where(Evidence.session_id == self.session_id)
            .order_by(desc(Evidence.fetched_at), desc(Evidence.id))
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        records = [self._row_to_record(r) for r in result.scalars().all()]
        if only_fresh:
            records = [r for r in records if r.is_fresh]
        return records

    def _row_to_record(self, row: Evidence) -> EvidenceRecord:
        return EvidenceRecord(
            ev_id=row.ev_id,
            session_id=row.session_id,
            agent=row.agent,
            source=row.source,
            query=self._parse_query(row.query_json),
            data=row.data_json,
            summary=row.summary,
            fetched_at=row.fetched_at,
            ttl_seconds=row.ttl_seconds,
        )

    @staticmethod
    def _parse_query(raw: str) -> dict[str, Any]:
        try:
            value = json.loads(raw or "{}")
            return value if isinstance(value, dict) else {"value": value}
        except json.JSONDecodeError:
            return {"raw": raw}
