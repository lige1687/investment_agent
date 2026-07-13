"""Fund transaction fee simulation."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RedemptionFeeTier:
    """Redemption fee tier selected by holding days."""

    max_holding_days: int | None
    fee_rate: float


@dataclass(frozen=True)
class FundFeeModel:
    """Fee model for fund subscription and redemption.

    Management and custodian fees are assumed to be reflected in NAV.
    """

    subscription_fee_rate: float = 0.0
    redemption_fee_tiers: list[RedemptionFeeTier] = field(default_factory=list)

    def calculate_buy_shares(self, cash: float, nav: float) -> tuple[float, float]:
        if cash < 0:
            raise ValueError("cash must be non-negative")
        if nav <= 0:
            raise ValueError("nav must be positive")

        fee = cash * self.subscription_fee_rate
        shares = (cash - fee) / nav
        return shares, fee

    def calculate_sell_cash(
        self,
        shares: float,
        nav: float,
        holding_days: int,
    ) -> tuple[float, float]:
        if shares < 0:
            raise ValueError("shares must be non-negative")
        if nav <= 0:
            raise ValueError("nav must be positive")
        if holding_days < 0:
            raise ValueError("holding_days must be non-negative")

        gross = shares * nav
        fee_rate = self._redemption_fee_rate(holding_days)
        fee = gross * fee_rate
        return gross - fee, fee

    def _redemption_fee_rate(self, holding_days: int) -> float:
        for tier in self.redemption_fee_tiers:
            if tier.max_holding_days is None or holding_days <= tier.max_holding_days:
                return tier.fee_rate
        return 0.0

