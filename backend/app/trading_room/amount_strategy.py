"""Pluggable amount-suggestion strategies for the conversation layer.

The default is a target-gap strategy: (target% - current%) × holdings_value.
Amount numbers are always produced by deterministic code - the Chair LLM only
explains a pre-computed range, never invents one.
"""

from __future__ import annotations

from typing import Any, Iterable, Literal, Protocol

from app.trading_room.conversation.schemas import AmountSuggestion
from app.trading_room.schemas import TargetAllocation


CONDITIONAL_BUY_MIN_SCORE = 65


class AmountStrategy(Protocol):
    def suggest(
        self,
        *,
        action: Literal["buy", "sell"],
        fund_code: str,
        positions: Iterable[dict[str, Any]],
        target_allocations: Iterable[TargetAllocation],
        score: int,
    ) -> AmountSuggestion | None: ...


class TargetGapStrategy:
    """v1 default: gap between target allocation and current allocation."""

    STANDARD_CAVEAT = "实际可买/可卖金额以支付宝为准，本区间为参考"

    def suggest(
        self,
        *,
        action: Literal["buy", "sell"],
        fund_code: str,
        positions: Iterable[dict[str, Any]],
        target_allocations: Iterable[TargetAllocation],
        score: int,
    ) -> AmountSuggestion | None:
        positions_list = list(positions)
        holdings_value = sum(
            max(0.0, float(p.get("market_value") or 0))
            for p in positions_list if isinstance(p, dict)
        )
        if holdings_value <= 0:
            return None

        current_value = sum(
            max(0.0, float(p.get("market_value") or 0))
            for p in positions_list
            if isinstance(p, dict)
            and str(p.get("symbol") or p.get("fund_code") or "") == fund_code
        )
        current_pct = current_value / holdings_value

        target = next(
            (t for t in target_allocations
             if t.scope == "fund" and t.key == fund_code),
            None,
        )
        if target is None:
            return None

        if action == "buy":
            if score < CONDITIONAL_BUY_MIN_SCORE:
                return None
            gap_pct = target.target_pct - current_pct
            if gap_pct <= 0:
                return None
            gap_amount = gap_pct * holdings_value
            # 分数分档折扣
            if score >= 80:
                lo, hi = 0.5, 1.0
            elif score >= 70:
                lo, hi = 0.3, 0.7
            else:
                lo, hi = 0.2, 0.5
            minimum = round(gap_amount * lo, -1)
            maximum = round(gap_amount * hi, -1)
            basis = (
                f"目标仓位 {target.target_pct:.0%} - 当前 {current_pct:.0%}"
                f" = 缺口 {gap_amount:.0f} 元，按分数 {score} 分档取 {lo:.0%}-{hi:.0%}"
            )
        else:  # sell
            over_pct = current_pct - target.target_pct
            if over_pct <= 0:
                return None
            over_amount = over_pct * holdings_value
            minimum = round(over_amount * 0.3, -1)
            maximum = round(over_amount * 0.8, -1)
            basis = (
                f"当前 {current_pct:.0%} - 目标 {target.target_pct:.0%}"
                f" = 超配 {over_amount:.0f} 元，减仓建议区间 30-80%"
            )

        if maximum < minimum:
            minimum, maximum = maximum, minimum
        return AmountSuggestion(
            action=action,
            fund_code=fund_code,
            minimum=float(minimum),
            maximum=float(maximum),
            basis=basis,
            caveats=[self.STANDARD_CAVEAT],
        )
