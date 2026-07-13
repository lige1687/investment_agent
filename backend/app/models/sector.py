"""Sector/Industry profile model."""
from datetime import date, datetime
from sqlalchemy import String, Float, Integer, Date, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class SectorProfile(Base):
    __tablename__ = "sector_profiles"

    code: Mapped[str] = mapped_column(String(20), primary_key=True, comment="THS sector code")
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    sector_type: Mapped[str] = mapped_column(String(20), nullable=True, comment="industry/concept/region")
    parent_code: Mapped[str] = mapped_column(String(20), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SectorETFSMapping(Base):
    __tablename__ = "sector_etf_mapping"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sector_code: Mapped[str] = mapped_column(String(20), nullable=False)
    etf_code: Mapped[str] = mapped_column(String(20), nullable=False)
    correlation: Mapped[float] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SectorDailyStats(Base):
    __tablename__ = "sector_daily_stats"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sector_code: Mapped[str] = mapped_column(String(20), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    price_change_pct: Mapped[float] = mapped_column(Float, nullable=True)
    turnover: Mapped[float] = mapped_column(Float, nullable=True)
    volume: Mapped[float] = mapped_column(Float, nullable=True)
    capital_flow: Mapped[float] = mapped_column(Float, nullable=True, comment="Net capital flow")
    large_order_flow: Mapped[float] = mapped_column(Float, nullable=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=True)
    rank_change: Mapped[int] = mapped_column(Integer, nullable=True)
    hot_level: Mapped[int] = mapped_column(Integer, nullable=True, comment="1-5 heat level")
