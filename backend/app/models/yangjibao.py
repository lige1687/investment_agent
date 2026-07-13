"""Yangjibao token storage model."""
from datetime import datetime
from sqlalchemy import String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class YangjibaoToken(Base):
    __tablename__ = "yangjibao_token"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    access_token: Mapped[str] = mapped_column(String(500), nullable=False)
    refresh_token: Mapped[str] = mapped_column(String(500), nullable=True)
    token_type: Mapped[str] = mapped_column(String(50), default="bearer")
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    raw_response: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
