"""Small deterministic guard for cash, holdings, allocation, and trade rules."""

import math

from pydantic import BaseModel, ConfigDict

from app.trading_room.execution_preflight import TradeStatusSnapshot
from app.trading_room.schemas import ActionClass, DecisionRange, TradeAvailability


class LightTradeGuardResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    suggested: DecisionRange
    guarded: DecisionRange | None
    maximum_action_class: ActionClass
    immediately_executable: bool
    applied_caps: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


class LightTradeGuard:
    @staticmethod
    def guard_buy(
        *,
        suggested: DecisionRange,
        preflight: TradeStatusSnapshot,
        consumed_purchase_today: float,
        account_equity: float,
        current_allocation_pct: float,
        target_allocation_pct: float,
        available_cash: float,
        pending_buy_amount: float,
    ) -> LightTradeGuardResult:
        if preflight.manager_status is TradeAvailability.SUSPENDED:
            return LightTradeGuardResult(
                suggested=suggested,
                guarded=None,
                maximum_action_class=ActionClass.NO_ACTION,
                immediately_executable=False,
                reasons=("manager_suspended",),
            )

        remaining_limit = preflight.remaining_purchase_limit(
            consumed_today=consumed_purchase_today
        )
        caps = {
            "manager_daily_limit": remaining_limit if remaining_limit is not None else math.inf,
            "target_allocation": max(
                0.0,
                (target_allocation_pct - current_allocation_pct) * account_equity,
            ),
            "available_cash": max(0.0, available_cash - max(0.0, pending_buy_amount)),
        }
        maximum = min(caps.values())
        limiting = tuple(name for name, value in caps.items() if math.isclose(value, maximum))
        if maximum < suggested.minimum:
            return LightTradeGuardResult(
                suggested=suggested,
                guarded=None,
                maximum_action_class=preflight.maximum_action_class,
                immediately_executable=False,
                applied_caps=limiting,
                reasons=limiting,
            )

        guarded = DecisionRange(
            minimum=suggested.minimum,
            maximum=min(suggested.maximum, maximum),
        )
        return LightTradeGuardResult(
            suggested=suggested,
            guarded=guarded,
            maximum_action_class=preflight.maximum_action_class,
            immediately_executable=(
                preflight.maximum_action_class is ActionClass.IMMEDIATE
            ),
            applied_caps=limiting if maximum < suggested.maximum else (),
            reasons=(),
        )

    @staticmethod
    def guard_sell(
        *,
        suggested: DecisionRange,
        settled_holding_amount: float,
        pending_sell_amount: float,
    ) -> LightTradeGuardResult:
        maximum = max(0.0, settled_holding_amount - max(0.0, pending_sell_amount))
        if maximum < suggested.minimum:
            return LightTradeGuardResult(
                suggested=suggested,
                guarded=None,
                maximum_action_class=ActionClass.NO_ACTION,
                immediately_executable=False,
                applied_caps=("settled_holding",),
                reasons=("settled_holding",),
            )
        guarded = DecisionRange(
            minimum=suggested.minimum,
            maximum=min(suggested.maximum, maximum),
        )
        return LightTradeGuardResult(
            suggested=suggested,
            guarded=guarded,
            maximum_action_class=ActionClass.IMMEDIATE,
            immediately_executable=True,
            applied_caps=("settled_holding",) if maximum < suggested.maximum else (),
        )

