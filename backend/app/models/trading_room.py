"""Replayable persistence models for the daily trading discussion room.

Policy payloads and session input snapshots are append-only.  Deliberately
mutable fields (session status and user feedback) live beside, but never
overwrite, the facts that the discussion originally saw.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, event, inspect
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ImmutableTradingRecordError(RuntimeError):
    """Raised when code tries to rewrite an audit snapshot."""


class TradingPolicyVersion(Base):
    __tablename__ = "trading_policy_versions"

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    template_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ready: Mapped[bool] = mapped_column(nullable=False)
    policy_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class TradingRoomSession(Base):
    __tablename__ = "trading_room_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    policy_version_id: Mapped[str] = mapped_column(
        ForeignKey("trading_policy_versions.version_id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="context_ready")
    context_json: Mapped[str] = mapped_column(Text, nullable=False)
    final_decision_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    selected_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    feedback_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    specialist_memos: Mapped[list["SpecialistMemoRecord"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", lazy="selectin"
    )
    messages: Mapped[list["TradingRoomMessageRecord"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", lazy="selectin"
    )
    policy_proposals: Mapped[list["PolicyChangeProposalRecord"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", lazy="selectin"
    )
    exposure_snapshots: Mapped[list["FundExposureSnapshotRecord"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", lazy="selectin"
    )
    trade_status_snapshots: Mapped[list["FundTradeStatusSnapshotRecord"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", lazy="selectin",
        order_by="FundTradeStatusSnapshotRecord.id",
    )

    __table_args__ = (Index("ix_trading_room_created", "created_at"),)


class SpecialistMemoRecord(Base):
    __tablename__ = "trading_room_specialist_memos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("trading_room_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    memo_json: Mapped[str] = mapped_column(Text, nullable=False)
    skill_versions_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    session: Mapped[TradingRoomSession] = relationship(back_populates="specialist_memos")


class TradingRoomMessageRecord(Base):
    __tablename__ = "trading_room_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("trading_room_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_role: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    session: Mapped[TradingRoomSession] = relationship(back_populates="messages")


class PolicyChangeProposalRecord(Base):
    __tablename__ = "trading_room_policy_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("trading_room_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field: Mapped[str] = mapped_column(String(160), nullable=False)
    proposed_value_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    session: Mapped[TradingRoomSession] = relationship(back_populates="policy_proposals")


class FundExposureSnapshotRecord(Base):
    __tablename__ = "trading_room_exposure_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("trading_room_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fund_code: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    session: Mapped[TradingRoomSession] = relationship(back_populates="exposure_snapshots")


class FundTradeStatusSnapshotRecord(Base):
    __tablename__ = "trading_room_trade_status_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("trading_room_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fund_code: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    share_class: Mapped[str] = mapped_column(String(16), nullable=False)
    channel: Mapped[str] = mapped_column(String(40), nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    session: Mapped[TradingRoomSession] = relationship(back_populates="trade_status_snapshots")


class AccountValuationSnapshotRecord(Base):
    __tablename__ = "account_valuation_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    holdings_value: Mapped[float] = mapped_column(Float, nullable=False)
    cash: Mapped[float | None] = mapped_column(Float, nullable=True)
    equity: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class TradingRoomFundingConfirmationRecord(Base):
    __tablename__ = "trading_room_funding_confirmations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("trading_room_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fund_code: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(40), nullable=False)
    available_cash: Mapped[float] = mapped_column(Float, nullable=False)
    pending_buy_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    consumed_purchase_today: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


@event.listens_for(TradingPolicyVersion, "before_update")
def _prevent_policy_rewrite(_mapper, _connection, target: TradingPolicyVersion) -> None:
    state = inspect(target)
    if any(state.attrs[name].history.has_changes() for name in ("template_id", "ready", "policy_json", "created_at")):
        raise ImmutableTradingRecordError("policy snapshot is immutable")


@event.listens_for(TradingRoomSession, "before_update")
def _prevent_session_snapshot_rewrite(_mapper, _connection, target: TradingRoomSession) -> None:
    state = inspect(target)
    if state.attrs.context_json.history.has_changes() or state.attrs.policy_version_id.history.has_changes():
        raise ImmutableTradingRecordError("session context and policy reference are immutable")
