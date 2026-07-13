"""Alert rule and alert history models."""
from datetime import datetime
from sqlalchemy import String, Float, Integer, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class PriceAlert(Base):
    __tablename__ = "price_alerts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    alert_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="price_above/price_below/change_pct/consecutive_up/consecutive_down/volume_spike/rank_change/technical",
    )
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    direction: Mapped[str] = mapped_column(
        String(20), nullable=True,
        comment="above/below/cross_up/cross_down",
    )
    enabled: Mapped[bool] = mapped_column(default=True)
    last_triggered: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    cooldown_min: Mapped[int] = mapped_column(
        Integer, default=60, comment="Min between re-triggers",
    )

    # Provenance — how this alert was born.
    source: Mapped[str] = mapped_column(
        String(24), nullable=False, default="manual",
        comment="manual | decision | guardian | scout",
    )
    source_ref: Mapped[str] = mapped_column(
        String(48), nullable=True,
        comment="decision_id (or other artifact id) that spawned this alert",
    )
    note: Mapped[str] = mapped_column(
        Text, nullable=True,
        comment="original human text (e.g. the monitoring[] entry it came from)",
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_price_alerts_source_ref", "source_ref"),
        Index("ix_price_alerts_symbol", "symbol"),
    )


class AlertHistory(Base):
    __tablename__ = "alert_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    alert_rule_id: Mapped[int] = mapped_column(Integer, ForeignKey("price_alerts.id"), nullable=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(20), nullable=False)
    triggered_value: Mapped[float] = mapped_column(Float, nullable=True)
    threshold: Mapped[float] = mapped_column(Float, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=True)
    pushed_to_feishu: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
