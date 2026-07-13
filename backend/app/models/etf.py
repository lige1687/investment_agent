"""ETF profile model."""
from datetime import date, datetime
from sqlalchemy import String, Float, Date, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class ETFProfile(Base):
    __tablename__ = "etf_profiles"

    code: Mapped[str] = mapped_column(String(20), primary_key=True, comment="ETF code e.g. 510050")
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=True)
    fund_type: Mapped[str] = mapped_column(String(20), nullable=True, comment="equity/bond/commodity/overseas")
    underlying_index: Mapped[str] = mapped_column(String(20), nullable=True, comment="Tracked index code")
    nav: Mapped[float] = mapped_column(Float, nullable=True, comment="Latest NAV")
    nav_date: Mapped[date] = mapped_column(Date, nullable=True)
    management_fee: Mapped[float] = mapped_column(Float, nullable=True)
    custodian_fee: Mapped[float] = mapped_column(Float, nullable=True)
    fund_size: Mapped[float] = mapped_column(Float, nullable=True, comment="Fund size in 100M CNY")
    establishment_date: Mapped[date] = mapped_column(Date, nullable=True)
    manager_company: Mapped[str] = mapped_column(String(200), nullable=True)
    raw_data: Mapped[str] = mapped_column(Text, default="{}", comment="Full raw data as JSON")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
