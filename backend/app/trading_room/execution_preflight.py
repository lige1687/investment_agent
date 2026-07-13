"""Restore current fund trading availability from effective announcements."""

from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.trading_room.schemas import ActionClass, TradeAvailability


class TradeStatusSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    fund_code: str
    share_class: str
    customer_scope: str
    manager_status: TradeAvailability
    redemption_status: TradeAvailability
    daily_purchase_limit: float | None = Field(default=None, ge=0)
    effective_date: date | None = None
    announcement_title: str | None = None
    announcement_url: str | None = None
    published_at: datetime | None = None
    queried_at: datetime
    manager_source: str = "announcement-search"
    channel_confirmed: bool = False
    maximum_action_class: ActionClass

    def remaining_purchase_limit(self, *, consumed_today: float) -> float | None:
        if self.daily_purchase_limit is None:
            return None
        return max(0.0, self.daily_purchase_limit - max(0.0, consumed_today))


class ExecutionPreflight:
    @staticmethod
    def restore(
        *,
        records: list[dict[str, Any]],
        fund_code: str,
        share_class: str,
        customer_scope: str,
        as_of: date,
        queried_at: datetime,
        channel_confirmed: bool,
    ) -> TradeStatusSnapshot:
        applicable: list[tuple[date, datetime, dict[str, Any]]] = []
        for record in records:
            if str(record.get("fund_code") or "") != fund_code:
                continue
            share_classes = record.get("share_classes")
            if not isinstance(share_classes, list) or share_class not in share_classes:
                continue
            record_scope = str(record.get("customer_scope") or "")
            if record_scope not in {"all", customer_scope}:
                continue
            try:
                effective = date.fromisoformat(str(record["effective_date"]))
                published = datetime.fromisoformat(str(record["published_at"]))
                status = TradeAvailability(str(record["action"]))
            except (KeyError, TypeError, ValueError):
                continue
            if effective > as_of:
                continue
            normalized = dict(record)
            normalized["_status"] = status
            applicable.append((effective, published, normalized))

        if not applicable:
            return TradeStatusSnapshot(
                fund_code=fund_code,
                share_class=share_class,
                customer_scope=customer_scope,
                manager_status=TradeAvailability.UNKNOWN,
                redemption_status=TradeAvailability.UNKNOWN,
                queried_at=queried_at,
                channel_confirmed=channel_confirmed,
                maximum_action_class=ActionClass.CONDITIONAL,
            )

        effective, published, current = max(applicable, key=lambda item: (item[0], item[1]))
        status: TradeAvailability = current["_status"]
        raw_limit = current.get("purchase_limit")
        try:
            purchase_limit = float(raw_limit) if raw_limit is not None else None
        except (TypeError, ValueError):
            purchase_limit = None

        if status is TradeAvailability.SUSPENDED:
            maximum_action = ActionClass.NO_ACTION
        elif status is TradeAvailability.UNKNOWN or not channel_confirmed:
            maximum_action = ActionClass.CONDITIONAL
        else:
            maximum_action = ActionClass.IMMEDIATE

        return TradeStatusSnapshot(
            fund_code=fund_code,
            share_class=share_class,
            customer_scope=customer_scope,
            manager_status=status,
            redemption_status=TradeAvailability.OPEN,
            daily_purchase_limit=purchase_limit if status is TradeAvailability.LIMITED else None,
            effective_date=effective,
            announcement_title=str(current.get("title") or "") or None,
            announcement_url=str(current.get("url") or "") or None,
            published_at=published,
            queried_at=queried_at,
            channel_confirmed=channel_confirmed,
            maximum_action_class=maximum_action,
        )


AnnouncementProvider = Callable[[str], Awaitable[list[dict[str, Any]]]]


class ExecutionPreflightService:
    def __init__(self, *, provider: AnnouncementProvider, fresh_minutes: int = 15):
        self._provider = provider
        self._fresh_minutes = fresh_minutes

    async def refresh_if_stale(
        self,
        snapshot: TradeStatusSnapshot,
        *,
        now: datetime,
    ) -> TradeStatusSnapshot:
        age_minutes = (now - snapshot.queried_at).total_seconds() / 60
        if age_minutes <= self._fresh_minutes:
            return snapshot
        records = await self._provider(snapshot.fund_code)
        return ExecutionPreflight.restore(
            records=records,
            fund_code=snapshot.fund_code,
            share_class=snapshot.share_class,
            customer_scope=snapshot.customer_scope,
            as_of=now.date(),
            queried_at=now,
            channel_confirmed=snapshot.channel_confirmed,
        )

