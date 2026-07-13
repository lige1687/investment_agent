"""Feishu configuration model."""
from datetime import datetime
from sqlalchemy import String, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class FeishuConfig(Base):
    __tablename__ = "feishu_config"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    webhook_url: Mapped[str] = mapped_column(String(500), nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True)
    notify_market_open: Mapped[bool] = mapped_column(default=True)
    notify_market_close: Mapped[bool] = mapped_column(default=True)
    notify_alerts: Mapped[bool] = mapped_column(default=True)
    notify_signals: Mapped[bool] = mapped_column(default=True)
    notify_pnl: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
