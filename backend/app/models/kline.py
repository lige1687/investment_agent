"""K-line cache and market calendar models."""
from datetime import date, datetime
from sqlalchemy import String, Float, Integer, Date, DateTime, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class KlineCache(Base):
    __tablename__ = "kline_cache"
    __table_args__ = (
        UniqueConstraint("symbol", "period", "timestamp", name="uq_kline"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    period: Mapped[str] = mapped_column(String(10), nullable=False, comment="1min/5min/15min/30min/60min/daily/weekly/monthly")
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=True, comment="Turnover amount")


class MarketCalendar(Base):
    __tablename__ = "market_calendar"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    is_trading: Mapped[bool] = mapped_column(default=True)
    market: Mapped[str] = mapped_column(String(20), default="A-share")
    description: Mapped[str] = mapped_column(String(100), nullable=True, comment="Holiday name if applicable")


class DailySummary(Base):
    __tablename__ = "daily_summaries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    summary_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="market_open/market_close")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="JSON structured summary")
    feishu_msg_id: Mapped[str] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
