"""Position, transaction, and investment plan models."""

from datetime import date, datetime, time
from sqlalchemy import (
    String,
    Float,
    Integer,
    Date,
    Time,
    DateTime,
    Text,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("symbol", "position_type", name="uq_position"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="ETF/fund code"
    )
    position_type: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="etf/fund"
    )
    shares: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Current shares held"
    )
    avg_cost: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Average cost per share"
    )
    current_price: Mapped[float] = mapped_column(Float, nullable=True)
    market_value: Mapped[float] = mapped_column(Float, nullable=True)
    cost_basis: Mapped[float] = mapped_column(
        Float, nullable=True, comment="Total cost"
    )
    unrealized_pnl: Mapped[float] = mapped_column(Float, nullable=True)
    unrealized_pnl_pct: Mapped[float] = mapped_column(Float, nullable=True)
    estimated_change_pct: Mapped[float] = mapped_column(
        Float, nullable=True, comment="今日预估涨跌%% (gszzl)"
    )
    estimated_nav: Mapped[float] = mapped_column(
        Float, nullable=True, comment="盘中估算净值 (gsz)"
    )
    estimated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=True, comment="估值时间戳"
    )
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    allocation_pct: Mapped[float] = mapped_column(
        Float, nullable=True, comment="Target allocation %"
    )
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(
        String(20), default="manual", comment="manual/yangjibao"
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    position_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("positions.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    tx_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="buy/sell/dividend/split"
    )
    shares: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    amount: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Total transaction amount"
    )
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    tx_date: Mapped[date] = mapped_column(Date, nullable=False)
    tx_time: Mapped[time] = mapped_column(Time, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(
        String(20), default="manual", comment="manual/yangjibao"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class InvestmentPlan(Base):
    __tablename__ = "investment_plans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    plan_type: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="etf/fund"
    )
    frequency: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="daily/weekly/biweekly/monthly"
    )
    day_of_week: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="0=Mon..6=Sun"
    )
    day_of_month: Mapped[int] = mapped_column(Integer, nullable=True, comment="1-31")
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(
        String(10), default="active", comment="active/paused/cancelled"
    )
    next_run_date: Mapped[date] = mapped_column(Date, nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=True)
    end_date: Mapped[date] = mapped_column(Date, nullable=True)
    total_invested: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(
        String(20), default="manual", comment="manual/yangjibao"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
