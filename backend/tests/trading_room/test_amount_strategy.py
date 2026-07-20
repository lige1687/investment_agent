from app.trading_room.amount_strategy import TargetGapStrategy
from app.trading_room.schemas import TargetAllocation


POSITIONS = [
    {"symbol": "001513", "name": "易方达信息产业混合A", "market_value": 20_000},
    {"symbol": "008888", "name": "别的基金", "market_value": 30_000},
]  # holdings_value = 50_000


def _target(code: str, pct: float) -> TargetAllocation:
    return TargetAllocation(scope="fund", key=code, target_pct=pct)


def test_buy_gap_returns_range_when_target_exceeds_current():
    strat = TargetGapStrategy()
    # 001513 当前 40%，目标 60% -> 缺口 20% × 50000 = 10000
    result = strat.suggest(
        action="buy", fund_code="001513", positions=POSITIONS,
        target_allocations=[_target("001513", 0.60)], score=80,
    )
    assert result is not None
    assert result.action == "buy"
    assert result.minimum > 0
    assert result.maximum >= result.minimum
    assert "目标" in result.basis or "缺口" in result.basis
    assert any("养基宝" in c or "支付宝" in c for c in result.caveats)


def test_buy_no_target_returns_none():
    strat = TargetGapStrategy()
    result = strat.suggest(
        action="buy", fund_code="001513", positions=POSITIONS,
        target_allocations=[], score=80,
    )
    assert result is None


def test_buy_score_below_threshold_returns_none():
    strat = TargetGapStrategy()
    # 分数低于 conditional_buy_min（默认 65）
    result = strat.suggest(
        action="buy", fund_code="001513", positions=POSITIONS,
        target_allocations=[_target("001513", 0.60)], score=40,
    )
    assert result is None


def test_sell_overweight_returns_range():
    strat = TargetGapStrategy()
    # 001513 当前 40%，目标 20% -> 超配 20% × 50000 = 10000
    result = strat.suggest(
        action="sell", fund_code="001513", positions=POSITIONS,
        target_allocations=[_target("001513", 0.20)], score=0,  # sell 忽略 score
    )
    assert result is not None
    assert result.action == "sell"
    assert result.minimum > 0


def test_sell_at_or_below_target_returns_none():
    strat = TargetGapStrategy()
    result = strat.suggest(
        action="sell", fund_code="001513", positions=POSITIONS,
        target_allocations=[_target("001513", 0.60)], score=0,
    )
    assert result is None
