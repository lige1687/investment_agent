from datetime import date, timedelta

import pytest

from app.backtest.events import BacktestEvent, EventDetector
from app.backtest.models import (
    BacktestConfig,
    PortfolioSnapshot,
    ProsperityConfig,
    SignalBar,
)
from app.backtest.strategy import RuleBasedStrategyAgent


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


def _config(**overrides) -> BacktestConfig:
    values = {
        "fund_code": "001513",
        "fund_name": "易方达信息产业混合A",
        "signal_code": "sh510300",
        "signal_name": "通信设备ETF",
        "buy_ma_window": 3,
        "buy_volume_window": 3,
        "buy_volume_ratio": 1.2,
        "buy_stand_days": 2,
        "expma_window": 3,
        "profit_drawdown_trigger_pct": 5.0,
        "prosperity": ProsperityConfig(score=8.0, reasons=["业绩预期改善"]),
    }
    values.update(overrides)
    return BacktestConfig(**values)


def test_detector_emits_buy_candidate_when_prosperity_and_volume_trend_confirm():
    bars = _bars(
        closes=[10.0, 10.2, 10.4, 10.9, 11.3],
        volumes=[100.0, 100.0, 100.0, 140.0, 150.0],
    )
    snapshot = PortfolioSnapshot(
        date=bars[-1].date,
        cash=100_000.0,
        shares=0.0,
        nav=1.0,
        equity=100_000.0,
        position_pct=0.0,
        cumulative_return_pct=0.0,
        peak_return_pct=0.0,
    )

    events = EventDetector(_config()).detect(index=4, bars=bars, snapshot=snapshot)

    assert [event.event_type for event in events] == ["buy_candidate"]
    assert "五维买入信号闭环" in events[0].reason
    assert events[0].details["buy_signal"]["passed_count"] >= 3
    assert events[0].details["buy_signal"]["account_allowed"] is True


def test_detector_emits_risk_block_when_buy_signal_forms_but_account_redline_blocks():
    bars = _bars(
        closes=[10.0, 9.8, 9.9, 10.0, 10.2, 10.5, 10.8],
        volumes=[180.0, 120.0, 95.0, 90.0, 100.0, 130.0, 150.0],
    )
    snapshot = PortfolioSnapshot(
        date=bars[-1].date,
        cash=80_000.0,
        shares=20_000.0,
        nav=1.0,
        equity=100_000.0,
        position_pct=0.2,
        cumulative_return_pct=-11.0,
        peak_return_pct=0.0,
    )

    events = EventDetector(_config(target_position_pct=0.4)).detect(index=6, bars=bars, snapshot=snapshot)

    risk_events = [event for event in events if event.event_type == "risk_block"]
    assert len(risk_events) == 1
    assert risk_events[0].details["buy_signal"]["recommended_action"] == "禁止买入/禁止加仓"
    assert risk_events[0].details["trigger_signals"][0]["priority"] == "P0"
    assert risk_events[0].details["trigger_signals"][0]["trigger_family"] == "account_risk"


def test_detector_emits_account_risk_event_even_without_buy_signal():
    bars = _bars(
        closes=[10.0, 9.9, 9.8, 9.7, 9.6],
        volumes=[100.0, 100.0, 100.0, 100.0, 100.0],
    )
    snapshot = PortfolioSnapshot(
        date=bars[-1].date,
        cash=5_000.0,
        shares=95_000.0,
        nav=1.0,
        equity=100_000.0,
        position_pct=0.95,
        cumulative_return_pct=-6.0,
        peak_return_pct=0.0,
    )

    events = EventDetector(_config()).detect(index=4, bars=bars, snapshot=snapshot)

    risk_events = [event for event in events if event.event_type == "account_risk"]
    assert len(risk_events) == 1
    assert risk_events[0].reason == "账户级风控触发，必须优先重新评估风险"
    assert any(
        trigger["reason"] == "现金比例低于系统要求"
        for trigger in risk_events[0].details["trigger_signals"]
    )


def test_detector_does_not_emit_same_account_risk_trigger_every_day():
    bars = _bars(
        closes=[10.0, 9.9, 9.8, 9.7, 9.6, 9.5],
        volumes=[100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
    )
    detector = EventDetector(_config())
    snapshot = PortfolioSnapshot(
        date=bars[-1].date,
        cash=5_000.0,
        shares=95_000.0,
        nav=1.0,
        equity=100_000.0,
        position_pct=0.95,
        cumulative_return_pct=-6.0,
        peak_return_pct=0.0,
    )

    first_events = detector.detect(index=4, bars=bars, snapshot=snapshot)
    second_events = detector.detect(index=5, bars=bars, snapshot=snapshot)

    assert any(event.event_type == "account_risk" for event in first_events)
    assert not any(event.event_type == "account_risk" for event in second_events)


def test_detector_emits_profit_drawdown_when_return_falls_from_peak():
    bars = _bars(
        closes=[10.0, 10.1, 10.2, 10.3],
        volumes=[100.0, 100.0, 100.0, 100.0],
    )
    snapshot = PortfolioSnapshot(
        date=bars[-1].date,
        cash=20_000.0,
        shares=80_000.0,
        nav=1.0,
        equity=120_000.0,
        position_pct=0.8,
        cumulative_return_pct=12.0,
        peak_return_pct=20.0,
    )

    events = EventDetector(_config()).detect(index=3, bars=bars, snapshot=snapshot)

    assert "profit_drawdown" in [event.event_type for event in events]


def test_detector_emits_technical_breakdown_on_high_volume_expma_break():
    bars = _bars(
        closes=[10.0, 10.2, 10.4, 10.8, 10.1],
        volumes=[100.0, 100.0, 100.0, 120.0, 210.0],
    )
    snapshot = PortfolioSnapshot(
        date=bars[-1].date,
        cash=20_000.0,
        shares=80_000.0,
        nav=1.0,
        equity=100_000.0,
        position_pct=0.8,
        cumulative_return_pct=0.0,
        peak_return_pct=8.0,
    )

    events = EventDetector(_config()).detect(index=4, bars=bars, snapshot=snapshot)

    assert "technical_breakdown" in [event.event_type for event in events]


def test_strategy_observes_weak_buy_candidate_instead_of_trading():
    event = BacktestEvent(
        event_type="buy_candidate",
        date=date(2026, 1, 5),
        reason="五维买入信号闭环达到至少3项，触发分批买入判断",
        details={"buy_signal": {"signal_level": "weak_buy"}},
        snapshot=PortfolioSnapshot(
            date=date(2026, 1, 5),
            cash=100_000.0,
            shares=0.0,
            nav=1.0,
            equity=100_000.0,
            position_pct=0.0,
            cumulative_return_pct=0.0,
            peak_return_pct=0.0,
        ),
    )

    decision = RuleBasedStrategyAgent(_config()).decide(event)

    assert decision.action == "observe"
    assert "弱买信号" in decision.reason or "3/5维度" in decision.reason


def test_strategy_observes_account_risk_event_and_blocks_new_risk():
    event = BacktestEvent(
        event_type="account_risk",
        date=date(2026, 1, 5),
        reason="账户级风控触发，必须优先重新评估风险",
        details={"trigger_signals": [{"priority": "P0", "reason": "账户回撤达到5%"}]},
        snapshot=PortfolioSnapshot(
            date=date(2026, 1, 5),
            cash=5_000.0,
            shares=95_000.0,
            nav=1.0,
            equity=100_000.0,
            position_pct=0.95,
            cumulative_return_pct=-6.0,
            peak_return_pct=0.0,
        ),
    )

    decision = RuleBasedStrategyAgent(_config()).decide(event)

    assert decision.action == "observe"
    assert "禁止买入/禁止加仓" in decision.reason


def test_strategy_buys_half_plan_for_middle_or_strong_buy_candidate():
    # EventDetector.detect() returns buy_candidate event, not buy_confirmation
    # buy_candidate now enters observation period instead of deciding to buy immediately
    # So we test the buy_confirmation path directly
    event = BacktestEvent(
        event_type="buy_confirmation",
        date=date(2026, 1, 7),  # 观察期后的确认日期
        reason="买入候选经过2天观察确认持续满足条件",
        details={
            "original_buy_signal": {"signal_level": "middle_buy"}
        },
        snapshot=PortfolioSnapshot(
            date=date(2026, 1, 7),
            cash=100_000.0,
            shares=0.0,
            nav=1.1,
            equity=110_000.0,
            position_pct=0.0,
            cumulative_return_pct=0.0,
            peak_return_pct=0.0,
        ),
    )

    decision = RuleBasedStrategyAgent(_config()).decide(event)

    assert decision.action == "buy"
    # middle_buy (4/5) 信号现在建仓 70% 目标仓位 = 0.2 * 0.7 = 0.14
    assert decision.target_position_delta_pct == pytest.approx(0.14)


def test_strategy_blocks_buy_when_p0_account_trigger_is_present():
    # P0 account_risk 现在在 buy_candidate 阶段就被检测并阻止，而不需要等到 buy_confirmation
    event = BacktestEvent(
        event_type="buy_candidate",
        date=date(2026, 1, 5),
        reason="五维买入信号闭环达到至少3项，触发分批买入判断",
        details={
            "buy_signal": {"signal_level": "middle_buy"},
            "trigger_signals": [
                {"priority": "P0", "trigger_family": "account_risk", "reason": "账户回撤达到5%"}
            ],
        },
        snapshot=PortfolioSnapshot(
            date=date(2026, 1, 5),
            cash=80_000.0,
            shares=20_000.0,
            nav=1.0,
            equity=100_000.0,
            position_pct=0.2,
            cumulative_return_pct=-5.0,
            peak_return_pct=0.0,
        ),
    )

    decision = RuleBasedStrategyAgent(_config(target_position_pct=0.4)).decide(event)

    assert decision.action == "observe"
    assert "P0账户风控" in decision.reason


def test_strategy_ignores_dust_buy_when_remaining_room_is_too_small():
    event = BacktestEvent(
        event_type="buy_candidate",
        date=date(2026, 1, 5),
        reason="五维买入信号闭环达到至少3项，触发分批买入判断",
        details={"buy_signal": {"signal_level": "middle_buy"}},
        snapshot=PortfolioSnapshot(
            date=date(2026, 1, 5),
            cash=80_000.0,
            shares=20_000.0,
            nav=1.0,
            equity=100_000.0,
            position_pct=0.195,
            cumulative_return_pct=0.0,
            peak_return_pct=0.0,
        ),
    )

    decision = RuleBasedStrategyAgent(_config()).decide(event)

    assert decision.action == "hold"
    assert "低于最小交易仓位" in decision.reason


def test_strategy_sells_half_for_profit_drawdown():
    events = EventDetector(_config()).detect(
        index=3,
        bars=_bars(
            closes=[10.0, 10.1, 10.2, 10.3],
            volumes=[100.0, 100.0, 100.0, 100.0],
        ),
        snapshot=PortfolioSnapshot(
            date=date(2026, 1, 4),
            cash=20_000.0,
            shares=80_000.0,
            nav=1.0,
            equity=112_000.0,
            position_pct=0.8,
            cumulative_return_pct=12.0,
            peak_return_pct=20.0,
        ),
    )
    event = next(event for event in events if event.event_type == "profit_drawdown")

    decision = RuleBasedStrategyAgent(_config()).decide(event)

    assert decision.action == "sell"
    assert decision.ratio_of_position == 0.5
    assert "收益高点回撤" in decision.reason


def test_strategy_does_not_take_profit_on_tiny_remaining_position():
    event = BacktestEvent(
        event_type="profit_drawdown",
        date=date(2026, 1, 5),
        reason="收益从阶段高点回撤达到阈值，触发止盈保护判断",
        details={"drawdown_from_peak_pct": 8.0},
        snapshot=PortfolioSnapshot(
            date=date(2026, 1, 5),
            cash=98_500.0,
            shares=1_500.0,
            nav=1.0,
            equity=100_000.0,
            position_pct=0.015,
            cumulative_return_pct=5.0,
            peak_return_pct=13.0,
        ),
    )

    decision = RuleBasedStrategyAgent(_config()).decide(event)

    assert decision.action == "hold"
    assert "小仓位不做碎片化止盈" in decision.reason
