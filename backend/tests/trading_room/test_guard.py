"""LightTradeGuard deterministic amount-clamping tests."""

from datetime import date, datetime, timezone


def _limited_preflight(limit=10_000, confirmed=True):
    from app.trading_room.execution_preflight import TradeStatusSnapshot
    from app.trading_room.schemas import ActionClass, TradeAvailability

    return TradeStatusSnapshot(
        fund_code="001513",
        share_class="A",
        customer_scope="retail",
        manager_status=TradeAvailability.LIMITED,
        redemption_status=TradeAvailability.OPEN,
        daily_purchase_limit=limit,
        effective_date=date(2026, 6, 25),
        queried_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
        channel_confirmed=confirmed,
        maximum_action_class=ActionClass.IMMEDIATE if confirmed else ActionClass.CONDITIONAL,
    )


def test_buy_guard_intersects_limit_target_headroom_and_available_cash():
    from app.trading_room.guard import LightTradeGuard
    from app.trading_room.schemas import DecisionRange

    result = LightTradeGuard.guard_buy(
        suggested=DecisionRange(minimum=5_000, maximum=10_000),
        preflight=_limited_preflight(),
        consumed_purchase_today=2_500,
        account_equity=100_000,
        current_allocation_pct=0.10,
        target_allocation_pct=0.30,
        available_cash=9_000,
        pending_buy_amount=1_000,
    )

    assert result.guarded == DecisionRange(minimum=5_000, maximum=7_500)
    assert result.immediately_executable is True
    assert "manager_daily_limit" in result.applied_caps


def test_buy_guard_returns_no_range_when_cap_is_below_suggested_minimum():
    from app.trading_room.guard import LightTradeGuard
    from app.trading_room.schemas import DecisionRange

    result = LightTradeGuard.guard_buy(
        suggested=DecisionRange(minimum=5_000, maximum=10_000),
        preflight=_limited_preflight(limit=100_000),
        consumed_purchase_today=0,
        account_equity=100_000,
        current_allocation_pct=0.18,
        target_allocation_pct=0.20,
        available_cash=50_000,
        pending_buy_amount=0,
    )

    assert result.guarded is None
    assert result.immediately_executable is False
    assert "target_allocation" in result.reasons


def test_unknown_or_unconfirmed_preflight_never_becomes_immediate():
    from app.trading_room.guard import LightTradeGuard
    from app.trading_room.schemas import DecisionRange

    result = LightTradeGuard.guard_buy(
        suggested=DecisionRange(minimum=1_000, maximum=2_000),
        preflight=_limited_preflight(confirmed=False),
        consumed_purchase_today=0,
        account_equity=100_000,
        current_allocation_pct=0.10,
        target_allocation_pct=0.20,
        available_cash=20_000,
        pending_buy_amount=0,
    )

    assert result.guarded == DecisionRange(minimum=1_000, maximum=2_000)
    assert result.maximum_action_class.value == "CONDITIONAL"
    assert result.immediately_executable is False


def test_sell_guard_never_exceeds_settled_holding_after_pending_sell():
    from app.trading_room.guard import LightTradeGuard
    from app.trading_room.schemas import DecisionRange

    result = LightTradeGuard.guard_sell(
        suggested=DecisionRange(minimum=5_000, maximum=20_000),
        settled_holding_amount=12_000,
        pending_sell_amount=2_000,
    )

    assert result.guarded == DecisionRange(minimum=5_000, maximum=10_000)


def test_guard_has_no_hidden_single_operation_cap_or_batch_rule():
    from app.trading_room.guard import LightTradeGuard
    from app.trading_room.schemas import DecisionRange

    result = LightTradeGuard.guard_buy(
        suggested=DecisionRange(minimum=80_000, maximum=100_000),
        preflight=_limited_preflight(limit=300_000),
        consumed_purchase_today=0,
        account_equity=1_000_000,
        current_allocation_pct=0.10,
        target_allocation_pct=0.30,
        available_cash=300_000,
        pending_buy_amount=0,
    )

    assert result.guarded == DecisionRange(minimum=80_000, maximum=100_000)
    assert all("operation" not in cap and "batch" not in cap for cap in result.applied_caps)

