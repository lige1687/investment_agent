from datetime import date, timedelta

from app.backtest.models import BacktestConfig, PortfolioSnapshot, ProsperityConfig, SignalBar
from app.backtest.policy import TradingSystemPolicy


def _bars(closes: list[float], volumes: list[float]) -> list[SignalBar]:
    start = date(2026, 1, 1)
    return [
        SignalBar(
            date=start + timedelta(days=index),
            open=close,
            high=close + 0.2,
            low=close - 0.2,
            close=close,
            volume=volumes[index],
            amount=close * volumes[index],
        )
        for index, close in enumerate(closes)
    ]


def _snapshot(**overrides) -> PortfolioSnapshot:
    values = {
        "date": date(2026, 1, 7),
        "cash": 80_000.0,
        "shares": 20_000.0,
        "nav": 1.0,
        "equity": 100_000.0,
        "position_pct": 0.2,
        "cumulative_return_pct": 0.0,
        "peak_return_pct": 0.0,
    }
    values.update(overrides)
    return PortfolioSnapshot(**values)


def _config(**overrides) -> BacktestConfig:
    values = {
        "fund_code": "001513",
        "fund_name": "易方达信息产业混合A",
        "signal_code": "sh515880",
        "signal_name": "通信ETF参考",
        "target_position_pct": 0.4,
        "buy_ma_window": 3,
        "buy_volume_window": 3,
        "buy_volume_ratio": 1.1,
        "buy_stand_days": 2,
        "prosperity": ProsperityConfig(
            score=8.0,
            min_score_to_buy=7.0,
            reasons=["业绩预期改善", "新催化验证"],
        ),
    }
    values.update(overrides)
    return BacktestConfig(**values)


def test_policy_marks_strong_buy_when_five_dimension_loop_closes():
    bars = _bars(
        closes=[10.0, 9.8, 9.9, 10.0, 10.2, 10.5, 10.8],
        volumes=[180.0, 120.0, 95.0, 90.0, 100.0, 130.0, 150.0],
    )

    checklist = TradingSystemPolicy(_config()).evaluate_buy(index=6, bars=bars, snapshot=_snapshot())

    assert checklist.signal_level == "strong_buy"
    assert checklist.passed_count == 5
    assert checklist.account_allowed is True
    assert checklist.recommended_action == "按计划建仓/补仓"


def test_policy_blocks_buy_when_account_drawdown_redline_is_hit():
    bars = _bars(
        closes=[10.0, 9.8, 9.9, 10.0, 10.2, 10.5, 10.8],
        volumes=[180.0, 120.0, 95.0, 90.0, 100.0, 130.0, 150.0],
    )

    checklist = TradingSystemPolicy(_config()).evaluate_buy(
        index=6,
        bars=bars,
        snapshot=_snapshot(cumulative_return_pct=-11.0, peak_return_pct=0.0),
    )

    assert checklist.account_allowed is False
    assert checklist.signal_level == "risk_blocked"
    assert "账户回撤红线" in " ".join(checklist.account_reasons)

