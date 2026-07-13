"""Persistent storage for agent Evidence Bus + Decision Cards + Guardian runs.

Evidence:      Immutable snapshots of tool/skill outputs. Referenced by
               decision cards and by follow-up conversation turns.
StoredDecision: Structured decision cards (JSON) with lifecycle status
               (accepted/ignored) for later hit-rate analysis.
GuardianRun:   One row per scheduled Guardian scan (midday/close/manual).
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, Index, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Evidence(Base):
    """One piece of evidence — the result of a single tool/skill invocation.

    `ev_id` is what the agent references in decision cards and follow-up
    chats ("re-read ev_abc123 without re-fetching").
    """
    __tablename__ = "agent_evidence"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ev_id: Mapped[str] = mapped_column(
        String(48), nullable=False, unique=True, index=True,
        comment="ev_<short-hash>, references target for decision cards",
    )
    session_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        comment="conversation/session grouping — one chat = one session",
    )
    agent: Mapped[str] = mapped_column(
        String(24), nullable=False, default="advisor",
        comment="which agent role produced this: advisor/scout/guardian/system",
    )
    source: Mapped[str] = mapped_column(
        String(80), nullable=False,
        comment="tool or skill name that produced this evidence",
    )
    query_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}",
        comment="serialized input params passed to the source",
    )
    data_json: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="serialized output from the source (already truncated)",
    )
    summary: Mapped[str] = mapped_column(
        String(240), nullable=True,
        comment="optional one-line label for UI display",
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow,
    )
    ttl_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=300,
        comment="0 = permanent; otherwise evidence is stale after this many seconds",
    )

    __table_args__ = (
        Index("ix_evidence_session_fetched", "session_id", "fetched_at"),
    )


class StoredDecision(Base):
    """A DecisionCard as emitted by an agent, serialized for later query.

    `user_action` is updated by the frontend once the user accepts/ignores.
    Populated later by a Guardian background job with outcome_7d/outcome_30d.
    """
    __tablename__ = "agent_decisions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    decision_id: Mapped[str] = mapped_column(
        String(48), nullable=False, unique=True, index=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
    )
    agent: Mapped[str] = mapped_column(String(24), nullable=False, default="advisor")
    type: Mapped[str] = mapped_column(
        String(24), nullable=False,
        comment="BUY_CANDIDATE / SELL_ALERT / REBALANCE / WATCH / NONE",
    )
    target_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    target_code: Mapped[str] = mapped_column(String(24), nullable=True)
    target_name: Mapped[str] = mapped_column(String(120), nullable=False)
    action_verb: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False, default=0.0)
    card_json: Mapped[str] = mapped_column(Text, nullable=False)

    # Lifecycle — set later by user actions and outcome tracking jobs.
    user_action: Mapped[str] = mapped_column(
        String(16), nullable=True,
        comment="accepted | ignored | partial | (null before user responds)",
    )
    user_action_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    # Baseline for outcome tracking. Recorded at save-time (fund NAV, etc.)
    # so OutcomeTracker has something to diff against.
    snapshot_price: Mapped[float] = mapped_column(nullable=True)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    outcome_7d_pct: Mapped[float] = mapped_column(nullable=True)
    outcome_7d_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    outcome_30d_pct: Mapped[float] = mapped_column(nullable=True)
    outcome_30d_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True,
    )

    __table_args__ = (
        Index("ix_decisions_session_created", "session_id", "created_at"),
        Index("ix_decisions_target", "target_kind", "target_code"),
    )


class GuardianRun(Base):
    """One Guardian scheduled scan. One row = one BriefingResult."""
    __tablename__ = "guardian_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True,
        comment="also the session_id under which evidence + decisions were written",
    )
    slot: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True,
        comment="midday | close | manual",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True,
    )
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    alert_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    decision_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pushed_to_feishu: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    result_json: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="serialized BriefingResult for full replay",
    )
    error: Mapped[str] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        Index("ix_guardian_slot_started", "slot", "started_at"),
    )
