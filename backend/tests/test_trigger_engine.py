from datetime import date, timedelta

from app.backtest.models import BacktestConfig, PortfolioSnapshot, SignalBar
from app.backtest.trigger_engine import TriggerEngine


def _bars(closes: list[float], volumes: list[float] | None = None) -> list[SignalBar]:
    volumes = volumes or [100.0] * len(closes)
    start = date(2026, 1, 1)
    return [
        SignalBar(
            date=start + timedelta(days=index),
            open=close * 0.99,
            high=close * 1.01,
            low=close * 0.99,
            close=close,
            volume=volumes[index],
            amount=close * volumes[index],
        )
        for index, close in enumerate(closes)
    ]


def _snapshot(**overrides) -> PortfolioSnapshot:
    values = {
        "date": date(2026, 3, 1),
        "cash": 90_000.0,
        "shares": 10_000.0,
        "nav": 1.0,
        "equity": 100_000.0,
        "position_pct": 0.1,
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
    }
    values.update(overrides)
    return BacktestConfig(**values)


def test_trigger_engine_prioritizes_account_risk_before_buy_opportunities():
    bars = _bars(
        closes=[10.0] * 25 + [10.2, 10.4, 10.8],
        volumes=[100.0] * 25 + [105.0, 110.0, 180.0],
    )
    snapshot = _snapshot(position_pct=0.92, cumulative_return_pct=-7.5, peak_return_pct=0.0)

    triggers = TriggerEngine(_config()).evaluate(index=len(bars) - 1, bars=bars, snapshot=snapshot)

    assert triggers[0].priority == "P0"
    assert triggers[0].trigger_family == "account_risk"
    assert "账户回撤达到7%~8%" in [trigger.reason for trigger in triggers]
    assert any(trigger.trigger_family == "buy_observation" for trigger in triggers)


def test_trigger_engine_detects_buy_observation_signals_without_trading():
    bars = _bars(
        closes=[10.0] * 20 + [9.8, 9.9, 10.0, 10.1, 10.5],
        volumes=[120.0] * 20 + [80.0, 75.0, 70.0, 85.0, 150.0],
    )

    triggers = TriggerEngine(_config()).evaluate(
        index=len(bars) - 1,
        bars=bars,
        snapshot=_snapshot(position_pct=0.0),
    )

    reasons = [trigger.reason for trigger in triggers]
    assert "连续3天不创新低" in reasons
    assert "放量突破" in reasons
    assert all(trigger.priority == "P3" for trigger in triggers)
    assert all(trigger.should_call_ai for trigger in triggers)


def test_trigger_engine_detects_take_profit_and_stop_loss_inputs():
    bars = _bars(
        closes=[10.0] * 60 + [10.8, 10.4, 9.8],
        volumes=[100.0] * 60 + [220.0, 210.0, 240.0],
    )

    profit_triggers = TriggerEngine(_config()).evaluate(
        index=61,
        bars=bars,
        snapshot=_snapshot(position_pct=0.2, cumulative_return_pct=12.0, peak_return_pct=15.0),
    )
    stop_triggers = TriggerEngine(_config()).evaluate(
        index=62,
        bars=bars,
        snapshot=_snapshot(position_pct=0.2, cumulative_return_pct=-6.0, peak_return_pct=0.0),
    )

    assert any(trigger.priority == "P2" and trigger.trigger_family == "take_profit" for trigger in profit_triggers)
    assert any(trigger.priority == "P1" and trigger.trigger_family == "stop_loss" for trigger in stop_triggers)
