"""Persistence facade for daily trading-room audit records."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.trading_room import (
    FundExposureSnapshotRecord,
    FundTradeStatusSnapshotRecord,
    PolicyChangeProposalRecord,
    SpecialistMemoRecord,
    TradingPolicyVersion,
    TradingRoomMessageRecord,
    TradingRoomSession,
)
from app.trading_room.policy import TradingPolicy


VALID_FEEDBACK_STATES = {"accepted", "partial", "ignored", "watch"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class TradingRoomStore:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def save_policy(self, policy: TradingPolicy) -> TradingPolicyVersion:
        existing = await self._db.get(TradingPolicyVersion, policy.version_id)
        if existing is not None:
            return existing
        row = TradingPolicyVersion(
            version_id=policy.version_id,
            template_id=policy.template_id,
            ready=policy.ready,
            policy_json=policy.model_dump_json(),
            created_at=policy.created_at.replace(tzinfo=None),
        )
        self._db.add(row)
        await self._db.flush()
        return row

    async def get_policy(self, version_id: str) -> TradingPolicyVersion | None:
        return await self._db.get(TradingPolicyVersion, version_id)

    async def get_current_policy(self) -> TradingPolicyVersion | None:
        result = await self._db.execute(
            select(TradingPolicyVersion)
            .order_by(desc(TradingPolicyVersion.created_at), desc(TradingPolicyVersion.version_id))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create_session(
        self,
        *,
        policy_version_id: str,
        context_snapshot: dict[str, Any],
        session_id: str | None = None,
    ) -> TradingRoomSession:
        if await self.get_policy(policy_version_id) is None:
            raise ValueError(f"unknown policy version: {policy_version_id}")
        row = TradingRoomSession(
            id=session_id or str(uuid4()),
            policy_version_id=policy_version_id,
            status="context_ready",
            context_json=_json(context_snapshot),
        )
        self._db.add(row)
        await self._db.flush()
        return row

    async def get_session(self, session_id: str) -> TradingRoomSession | None:
        statement = (
            select(TradingRoomSession)
            .where(TradingRoomSession.id == session_id)
            .options(
                selectinload(TradingRoomSession.specialist_memos),
                selectinload(TradingRoomSession.messages),
                selectinload(TradingRoomSession.policy_proposals),
                selectinload(TradingRoomSession.exposure_snapshots),
                selectinload(TradingRoomSession.trade_status_snapshots),
            )
        )
        result = await self._db.execute(statement)
        return result.scalar_one_or_none()

    async def add_memo(
        self,
        session_id: str,
        *,
        role: str,
        state: str,
        payload: dict[str, Any],
        skill_versions: dict[str, str],
    ) -> SpecialistMemoRecord:
        row = SpecialistMemoRecord(
            session_id=session_id,
            role=role,
            state=state,
            memo_json=_json(payload),
            skill_versions_json=_json(skill_versions),
        )
        self._db.add(row)
        await self._db.flush()
        return row

    async def add_message(
        self,
        session_id: str,
        *,
        sender_role: str,
        content: str,
        payload: dict[str, Any] | None = None,
    ) -> TradingRoomMessageRecord:
        row = TradingRoomMessageRecord(
            session_id=session_id,
            sender_role=sender_role,
            content=content,
            message_json=_json(payload or {}),
        )
        self._db.add(row)
        await self._db.flush()
        return row

    async def add_policy_proposal(
        self,
        session_id: str,
        *,
        field: str,
        proposed_value: Any,
        reason: str,
    ) -> PolicyChangeProposalRecord:
        row = PolicyChangeProposalRecord(
            session_id=session_id,
            field=field,
            proposed_value_json=_json(proposed_value),
            reason=reason,
        )
        self._db.add(row)
        await self._db.flush()
        return row

    async def save_exposure_snapshot(
        self,
        session_id: str,
        *,
        fund_code: str,
        payload: dict[str, Any],
    ) -> FundExposureSnapshotRecord:
        row = FundExposureSnapshotRecord(
            session_id=session_id,
            fund_code=fund_code,
            snapshot_json=_json(payload),
        )
        self._db.add(row)
        await self._db.flush()
        return row

    async def save_trade_status_snapshot(
        self,
        session_id: str,
        *,
        fund_code: str,
        share_class: str,
        channel: str,
        payload: dict[str, Any],
    ) -> FundTradeStatusSnapshotRecord:
        row = FundTradeStatusSnapshotRecord(
            session_id=session_id,
            fund_code=fund_code,
            share_class=share_class,
            channel=channel,
            snapshot_json=_json(payload),
        )
        self._db.add(row)
        await self._db.flush()
        return row

    async def record_feedback(
        self,
        session_id: str,
        *,
        state: str,
        selected_amount: float | None = None,
        note: str | None = None,
    ) -> TradingRoomSession:
        if state not in VALID_FEEDBACK_STATES:
            raise ValueError(
                f"invalid feedback state: {state!r}; expected one of {sorted(VALID_FEEDBACK_STATES)}"
            )
        row = await self._db.get(TradingRoomSession, session_id)
        if row is None:
            raise KeyError(f"unknown trading-room session: {session_id}")
        row.feedback_state = state
        row.selected_amount = selected_amount
        row.feedback_note = note
        row.feedback_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._db.flush()
        return row

    async def finalize_session(
        self,
        session_id: str,
        *,
        decision: dict[str, Any],
    ) -> TradingRoomSession:
        row = await self._db.get(TradingRoomSession, session_id)
        if row is None:
            raise KeyError(f"unknown trading-room session: {session_id}")
        row.status = "finalized"
        row.final_decision_json = _json(decision)
        await self._db.flush()
        return row
