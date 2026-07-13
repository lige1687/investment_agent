"""Fund subscription-state restoration and freshness tests."""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest


FIXTURE = Path(__file__).parents[1] / "fixtures" / "trading_room" / "announcements_001513.json"


def _records():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_restore_uses_latest_effective_announcement_for_exact_share_class():
    from app.trading_room.execution_preflight import ExecutionPreflight
    from app.trading_room.schemas import TradeAvailability

    snapshot = ExecutionPreflight.restore(
        records=_records(),
        fund_code="001513",
        share_class="A",
        customer_scope="retail",
        as_of=date(2026, 7, 13),
        queried_at=datetime(2026, 7, 13, 6, 0, tzinfo=timezone.utc),
        channel_confirmed=True,
    )

    assert snapshot.manager_status is TradeAvailability.LIMITED
    assert snapshot.daily_purchase_limit == 10000
    assert snapshot.effective_date == date(2026, 6, 25)
    assert snapshot.announcement_url.endswith("001513-limit-10000")
    assert snapshot.share_class == "A"


def test_suspended_unknown_and_unconfirmed_channel_fail_closed():
    from app.trading_room.execution_preflight import ExecutionPreflight
    from app.trading_room.schemas import ActionClass, TradeAvailability

    now = datetime(2026, 7, 13, tzinfo=timezone.utc)
    suspended = ExecutionPreflight.restore(
        records=[
            {
                "fund_code": "001513",
                "share_classes": ["A"],
                "customer_scope": "all",
                "action": "SUSPENDED",
                "effective_date": "2026-07-01",
                "published_at": "2026-06-30T18:00:00+08:00",
                "title": "暂停申购",
                "url": "https://example.test/suspended",
            }
        ],
        fund_code="001513",
        share_class="A",
        customer_scope="retail",
        as_of=now.date(),
        queried_at=now,
        channel_confirmed=True,
    )
    unknown = ExecutionPreflight.restore(
        records=[],
        fund_code="001513",
        share_class="A",
        customer_scope="retail",
        as_of=now.date(),
        queried_at=now,
        channel_confirmed=False,
    )
    unconfirmed = ExecutionPreflight.restore(
        records=_records(),
        fund_code="001513",
        share_class="A",
        customer_scope="retail",
        as_of=now.date(),
        queried_at=now,
        channel_confirmed=False,
    )

    assert suspended.manager_status is TradeAvailability.SUSPENDED
    assert suspended.maximum_action_class is ActionClass.NO_ACTION
    assert unknown.manager_status is TradeAvailability.UNKNOWN
    assert unknown.maximum_action_class is ActionClass.CONDITIONAL
    assert unconfirmed.maximum_action_class is ActionClass.CONDITIONAL


def test_limited_status_reports_remaining_daily_allowance():
    from app.trading_room.execution_preflight import ExecutionPreflight

    snapshot = ExecutionPreflight.restore(
        records=_records(),
        fund_code="001513",
        share_class="A",
        customer_scope="retail",
        as_of=date(2026, 7, 13),
        queried_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
        channel_confirmed=True,
    )

    assert snapshot.remaining_purchase_limit(consumed_today=2500) == 7500
    assert snapshot.remaining_purchase_limit(consumed_today=12000) == 0


@pytest.mark.asyncio
async def test_finalize_refreshes_preflight_only_after_15_minutes():
    from app.trading_room.execution_preflight import ExecutionPreflight, ExecutionPreflightService

    now = datetime(2026, 7, 13, 6, 30, tzinfo=timezone.utc)
    old = ExecutionPreflight.restore(
        records=_records(),
        fund_code="001513",
        share_class="A",
        customer_scope="retail",
        as_of=now.date(),
        queried_at=now - timedelta(minutes=16),
        channel_confirmed=True,
    )
    provider = AsyncMock(return_value=_records())
    service = ExecutionPreflightService(provider=provider, fresh_minutes=15)

    refreshed = await service.refresh_if_stale(old, now=now)

    provider.assert_awaited_once_with("001513")
    assert refreshed.queried_at == now


@pytest.mark.asyncio
async def test_finalize_keeps_preflight_younger_than_15_minutes():
    from app.trading_room.execution_preflight import ExecutionPreflight, ExecutionPreflightService

    now = datetime(2026, 7, 13, 6, 30, tzinfo=timezone.utc)
    recent = ExecutionPreflight.restore(
        records=_records(),
        fund_code="001513",
        share_class="A",
        customer_scope="retail",
        as_of=now.date(),
        queried_at=now - timedelta(minutes=14),
        channel_confirmed=True,
    )
    provider = AsyncMock(return_value=_records())
    service = ExecutionPreflightService(provider=provider, fresh_minutes=15)

    unchanged = await service.refresh_if_stale(recent, now=now)

    provider.assert_not_awaited()
    assert unchanged is recent

