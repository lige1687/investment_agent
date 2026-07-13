"""Trading signal model."""
from datetime import datetime
from sqlalchemy import String, Float, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="buy/sell/hold/strong_buy/strong_sell")
    signal_source: Mapped[str] = mapped_column(String(30), nullable=False, comment="kline_pattern/ma_cross/rsi/macd/bollinger/composite")
    confidence: Mapped[float] = mapped_column(Float, nullable=True, comment="0-1")
    price_at_signal: Mapped[float] = mapped_column(Float, nullable=True)
    timeframe: Mapped[str] = mapped_column(String(10), default="daily", comment="1min/5min/15min/30min/60min/daily/weekly")
    reason: Mapped[str] = mapped_column(Text, nullable=True, comment="Human-readable explanation")
    pattern_name: Mapped[str] = mapped_column(String(50), nullable=True, comment="e.g. morning_star/head_and_shoulders")
    indicators: Mapped[str] = mapped_column(Text, default="{}", comment="JSON: indicator values at signal time")
    status: Mapped[str] = mapped_column(String(20), default="active", comment="active/executed/expired/cancelled")
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
