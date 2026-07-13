"""Persisted Agent context snapshots for follow-up questions."""
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AgentContextSnapshot(Base):
    __tablename__ = "agent_context_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, comment="feishu_card/web_chat/scheduler")
    intent: Mapped[str] = mapped_column(String(60), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=True)
    context_json: Mapped[str] = mapped_column(Text, nullable=False)
    decision_json: Mapped[str] = mapped_column(Text, nullable=False)
    skill_calls_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
