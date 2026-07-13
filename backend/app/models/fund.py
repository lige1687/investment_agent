"""Fund (non-ETF) profile and watchlist models."""
from datetime import date, datetime
from sqlalchemy import String, Float, Integer, Date, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class FundProfile(Base):
    __tablename__ = "fund_profiles"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    fund_type: Mapped[str] = mapped_column(String(20), nullable=True, comment="stock/hybrid/bond/money/index/QDII")
    risk_level: Mapped[str] = mapped_column(String(5), nullable=True, comment="R1-R5")
    manager_name: Mapped[str] = mapped_column(String(100), nullable=True)
    manager_since: Mapped[date] = mapped_column(Date, nullable=True)
    fund_company: Mapped[str] = mapped_column(String(200), nullable=True)
    nav: Mapped[float] = mapped_column(Float, nullable=True)
    nav_date: Mapped[date] = mapped_column(Date, nullable=True)
    cumulative_nav: Mapped[float] = mapped_column(Float, nullable=True)
    aum: Mapped[float] = mapped_column(Float, nullable=True, comment="Assets under management")
    establishment_date: Mapped[date] = mapped_column(Date, nullable=True)
    fee_management: Mapped[float] = mapped_column(Float, nullable=True)
    fee_custodian: Mapped[float] = mapped_column(Float, nullable=True)
    fee_subscription: Mapped[str] = mapped_column(String(200), nullable=True)
    fee_redemption: Mapped[str] = mapped_column(String(200), nullable=True)
    performance_1y: Mapped[float] = mapped_column(Float, nullable=True)
    performance_3y: Mapped[float] = mapped_column(Float, nullable=True)
    performance_5y: Mapped[float] = mapped_column(Float, nullable=True)
    max_drawdown: Mapped[float] = mapped_column(Float, nullable=True)
    sharpe_ratio: Mapped[float] = mapped_column(Float, nullable=True)
    volatility: Mapped[float] = mapped_column(Float, nullable=True)
    raw_data: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    items: Mapped[list["WatchlistItem"]] = relationship(back_populates="watchlist", cascade="all, delete-orphan")


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("watchlist_id", "symbol", "item_type", name="uq_watchlist_item"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    watchlist_id: Mapped[int] = mapped_column(Integer, ForeignKey("watchlists.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, comment="ETF/sector/index/fund code")
    item_type: Mapped[str] = mapped_column(String(10), nullable=False, comment="etf/sector/index/fund")
    item_name: Mapped[str] = mapped_column(String(100), nullable=True, comment="Cached display name")
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    watchlist: Mapped["Watchlist"] = relationship(back_populates="items")
