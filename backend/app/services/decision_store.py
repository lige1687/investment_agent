"""DecisionCardStore — persist and query DecisionCard emissions.

Every card the agent emits via `emit_decision_card` lands here. The frontend
reads back through this store for:
  - session history ("show me the cards from this chat")
  - lifecycle updates (accepted/ignored)
  - hit-rate analytics (7d/30d outcomes — populated later by Guardian)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import StoredDecision
from app.models.fund import FundProfile
from app.schemas.decision_card import DecisionCard

logger = logging.getLogger(__name__)


VALID_USER_ACTIONS = {"accepted", "ignored", "partial"}


class DecisionCardStore:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def save(
        self,
        card: DecisionCard,
        *,
        session_id: str,
        sync_monitoring: bool = True,
    ) -> int:
        """Persist one card. Returns the DB row id.

        If the agent re-emits a card with the same decision_id (rare, but
        possible on a retry), we overwrite the previous row instead of raising —
        the model is expected to be authoritative for its own id.

        When `sync_monitoring=True` (default), also translate the card's
        `monitoring[]` bullets into PriceAlert rows so the anomaly scanner
        can watch them. Failure here is logged, not raised — a working
        card save shouldn't be blocked by an alert-sync hiccup.
        """
        card_dump = card.model_dump(mode="json")
        card_dump["session_id"] = session_id
        card_json = json.dumps(card_dump, ensure_ascii=False)

        target = card.target
        action = card.action

        # Enum fields on the card use `use_enum_values=True`, so `.value` works
        # on both real enums and already-serialized strings.
        def _val(x) -> str:
            return getattr(x, "value", x)

        existing = await self._db.execute(
            select(StoredDecision).where(StoredDecision.decision_id == card.decision_id)
        )
        row = existing.scalar_one_or_none()

        # Snapshot the fund NAV as the outcome-tracking baseline. Only for
        # fund targets — stocks/ETFs would need K-line data we don't reliably
        # store here yet.
        snapshot_price, snapshot_at = await self._snapshot_price_for(card)

        if row is None:
            row = StoredDecision(
                decision_id=card.decision_id,
                session_id=session_id,
                agent=card.agent,
                type=_val(card.type),
                target_kind=_val(target.kind),
                target_code=target.code,
                target_name=target.name,
                action_verb=_val(action.verb),
                confidence=float(action.confidence),
                card_json=card_json,
                created_at=datetime.utcnow(),
                snapshot_price=snapshot_price,
                snapshot_at=snapshot_at,
            )
            self._db.add(row)
        else:
            row.session_id = session_id
            row.agent = card.agent
            row.type = _val(card.type)
            row.target_kind = _val(target.kind)
            row.target_code = target.code
            row.target_name = target.name
            row.action_verb = _val(action.verb)
            row.confidence = float(action.confidence)
            row.card_json = card_json
            # Only fill snapshot if not already set — the first save wins.
            if row.snapshot_price is None and snapshot_price is not None:
                row.snapshot_price = snapshot_price
                row.snapshot_at = snapshot_at

        try:
            await self._db.flush()
        except Exception as e:
            logger.warning("DecisionCardStore: DB flush failed for %s: %s", card.decision_id, e)

        if sync_monitoring:
            try:
                # Local import to avoid a circular dep at module load time.
                from app.services.monitoring_alert import MonitoringAlertSynthesizer
                await MonitoringAlertSynthesizer(self._db).sync_from_card(card)
            except Exception as e:
                logger.warning(
                    "DecisionCardStore: monitoring sync failed for %s: %s",
                    card.decision_id, e,
                )

        return row.id

    async def get_by_id(self, decision_id: str) -> Optional[DecisionCard]:
        stmt = select(StoredDecision).where(StoredDecision.decision_id == decision_id)
        result = await self._db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return self._row_to_card(row)

    async def list_session(
        self, session_id: str, *, limit: int = 20
    ) -> list[DecisionCard]:
        stmt = (
            select(StoredDecision)
            .where(StoredDecision.session_id == session_id)
            .order_by(desc(StoredDecision.created_at), desc(StoredDecision.id))
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        return [self._row_to_card(r) for r in result.scalars().all()]

    async def mark_user_action(
        self, decision_id: str, action: str
    ) -> Optional[StoredDecision]:
        """Update lifecycle field. Returns the row or None if not found."""
        if action not in VALID_USER_ACTIONS:
            raise ValueError(
                f"invalid user action: {action!r}; "
                f"expected one of {sorted(VALID_USER_ACTIONS)}"
            )
        stmt = select(StoredDecision).where(StoredDecision.decision_id == decision_id)
        result = await self._db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        row.user_action = action
        row.user_action_at = datetime.utcnow()
        await self._db.flush()
        return row

    async def _snapshot_price_for(self, card: DecisionCard) -> tuple[Optional[float], Optional[datetime]]:
        """Best-effort NAV snapshot at decision time. Returns (None, None)
        if we can't find a price — the tracker will simply skip this row."""
        target = card.target
        kind = getattr(target.kind, "value", target.kind)
        if kind != "fund" or not target.code:
            return None, None
        stmt = select(FundProfile.nav).where(FundProfile.code == target.code)
        try:
            result = await self._db.execute(stmt)
            nav = result.scalar_one_or_none()
        except Exception as e:
            logger.debug("snapshot price lookup failed for %s: %s", target.code, e)
            return None, None
        if nav is None:
            return None, None
        return float(nav), datetime.utcnow()

    def _row_to_card(self, row: StoredDecision) -> DecisionCard:
        try:
            payload = json.loads(row.card_json)
        except json.JSONDecodeError:
            # Extremely unlikely; falls back to reconstructing a minimal card.
            payload = {
                "decision_id": row.decision_id,
                "agent": row.agent,
                "type": row.type,
                "target": {
                    "kind": row.target_kind,
                    "code": row.target_code,
                    "name": row.target_name,
                },
                "action": {
                    "verb": row.action_verb,
                    "confidence": row.confidence,
                },
            }
        # Pydantic will validate + coerce enums back
        return DecisionCard.model_validate(payload)
