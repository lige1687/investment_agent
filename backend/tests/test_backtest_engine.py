from datetime import date, timedelta

import pytest

from app.backtest.engine import BacktestEngine
from app.backtest.fees import FundFeeModel
from app.backtest.models import BacktestConfig, FundNavPoint, ProsperityConfig, SignalBar


def _navs(values: list[float]) -> list[FundNavPoint]:
    start = date(2026, 1, 1)
    return [
        FundNavPoint(date=start + timedelta(days=index), nav=value)
        for index, value in enumerate(values)
    ]


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
        "initial_cash": 100_000.0,
        "target_position_pct": 0.2,
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


def test_engine_executes_buy_candidate_on_next_fund_nav_day():
    config = _config()
    engine = BacktestEngine(fee_model=FundFeeModel(subscription_fee_rate=0.001))

    result = engine.run(
        config=config,
        # 添加更多 NAV 点以容纳 2 天观察期：买入候选 (Day 4) → 观察期 (Day 5-6) → 执行 (Day 7)
        fund_nav=_navs([1.0, 1.0, 1.0, 1.0, 1.0, 1.1, 1.1, 1.1]),
        signal_bars=_bars(
            closes=[10.0, 10.2, 10.4, 10.9, 11.3, 11.4, 11.4, 11.4],
            volumes=[100.0, 100.0, 100.0, 140.0, 150.0, 120.0, 120.0, 120.0],
        ),
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.action == "buy"
    assert trade.date == date(2026, 1, 7)  # T+1 执行（观察期末的下一天）
    assert trade.nav == 1.1
    # 现在使用分级建仓：middle_buy (4/5) 信号建仓 70% 目标仓位 = 14%
    # buy_size = min(0.2 * 0.7, 0.2) = min(0.14, 0.2) = 0.14 = 14% = 14000
    assert trade.cash_delta == pytest.approx(-14_000.0)
    assert trade.fee == pytest.approx(14.0)
    assert trade.shares == pytest.approx((14_000.0 - 14.0) / 1.1)
    assert result.metrics.trade_count == 1


def test_engine_sells_high_position_batch_first_after_profit_peak_drawdown():
    config = _config(initial_position_pct=0.8, target_position_pct=0.8)
    engine = BacktestEngine()

    result = engine.run(
        config=config,
        fund_nav=_navs([1.0, 1.1, 1.3, 1.2, 1.18]),
        signal_bars=_bars(
            closes=[10.0, 10.1, 10.2, 10.3, 10.4],
            volumes=[100.0, 100.0, 100.0, 100.0, 100.0],
        ),
    )

    sells = [trade for trade in result.trades if trade.action == "sell"]
    assert len(sells) == 1
    sell = sells[0]
    assert sell.date == date(2026, 1, 5)
    assert sell.nav == 1.18
    assert sell.shares == pytest.approx(16_000.0)
    assert sell.cash_delta == pytest.approx(18_880.0)
    assert "收益高点回撤" in sell.reason
    assert sell.batch_type == "high_position"
    assert result.metrics.final_equity > 100_000.0


def test_engine_does_not_sell_batches_on_etf_breakdown_without_fund_batch_trigger():
    config = _config(
        initial_position_pct=0.2,
        target_position_pct=0.2,
        breakdown_volume_ratio=1.0,
    )
    engine = BacktestEngine()

    result = engine.run(
        config=config,
        fund_nav=_navs([1.0] * 6),
        signal_bars=_bars(
            closes=[10.0, 10.2, 10.4, 10.8, 10.1, 10.0],
            volumes=[100.0, 100.0, 100.0, 120.0, 220.0, 100.0],
        ),
    )

    sells = [trade for trade in result.trades if trade.action == "sell"]
    assert sells == []


def test_engine_labels_confirmation_breakdown_sell_as_batch_stop_loss_when_fund_batch_is_losing():
    config = _config(
        initial_position_pct=0.16,
        target_position_pct=0.2,
        breakdown_volume_ratio=1.0,
    )
    engine = BacktestEngine()

    result = engine.run(
        config=config,
        fund_nav=_navs([1.0, 1.0, 1.0, 1.0, 0.87, 0.87]),
        signal_bars=_bars(
            closes=[10.0, 10.2, 10.4, 10.8, 10.1, 10.0],
            volumes=[100.0, 100.0, 100.0, 120.0, 220.0, 100.0],
        ),
    )

    sells = [trade for trade in result.trades if trade.action == "sell"]
    assert len(sells) == 1
    sell = sells[0]
    assert sell.batch_type == "confirmation"
    assert sell.batch_return_pct == pytest.approx(-13.0)
    assert "批次止损" in sell.reason


def test_engine_does_not_take_profit_confirmation_batch_without_fund_batch_profit():
    config = _config(initial_position_pct=0.3, target_position_pct=0.3)
    engine = BacktestEngine()

    result = engine.run(
        config=config,
        fund_nav=_navs([1.0, 1.2, 1.0, 0.98, 0.97]),
        signal_bars=_bars(
            closes=[10.0, 10.1, 10.2, 10.3, 10.4],
            volumes=[100.0, 100.0, 100.0, 100.0, 100.0],
        ),
    )

    sells = [trade for trade in result.trades if trade.action == "sell"]
    assert all(sell.batch_type != "confirmation" for sell in sells)


def test_engine_protects_confirmation_batch_when_own_profit_returns_near_cost_line():
    config = _config(
        initial_position_pct=0.16,
        target_position_pct=0.2,
        profit_drawdown_trigger_pct=5.0,
    )
    engine = BacktestEngine()

    result = engine.run(
        config=config,
        fund_nav=_navs([1.0, 1.061, 1.01, 1.01, 1.01]),
        signal_bars=_bars(
            closes=[10.0, 10.1, 10.2, 10.3, 10.4],
            volumes=[100.0, 100.0, 100.0, 100.0, 100.0],
        ),
    )

    sells = [trade for trade in result.trades if trade.action == "sell"]
    # 现在有两次卖出：确认仓 + 核心仓的动态止盈保护
    assert len(sells) == 2

    # 第一次：确认仓保护
    confirm_sell = sells[0]
    assert confirm_sell.batch_type == "confirmation"
    assert confirm_sell.batch_return_pct == pytest.approx(1.0)
    assert "成本线附近" in confirm_sell.reason

    # 第二次：核心仓动态止盈保护（基于75%保留率）
    # peak=6.1% * 75% = 4.575% 的阈值，当前 1% 已触发
    core_sell = sells[1]
    assert core_sell.batch_type == "core"
    assert core_sell.batch_return_pct == pytest.approx(1.0)
    assert "动态止盈" in core_sell.reason


def test_engine_keeps_remaining_core_shares_after_half_core_take_profit():
    config = _config(initial_position_pct=0.1, target_position_pct=0.2)
    engine = BacktestEngine()

    result = engine.run(
        config=config,
        fund_nav=_navs([1.0, 2.0, 1.4, 1.4, 1.4]),
        signal_bars=_bars(
            closes=[10.0, 10.1, 10.2, 10.3, 10.4],
            volumes=[100.0, 100.0, 100.0, 100.0, 100.0],
        ),
    )

    sells = [trade for trade in result.trades if trade.action == "sell"]
    assert len(sells) == 1
    assert sells[0].batch_type == "core"
    assert sells[0].shares == pytest.approx(5_000.0)
    sell_index = next(
        index for index, snapshot in enumerate(result.equity_curve)
        if snapshot.date == sells[0].date
    )
    assert result.equity_curve[sell_index].shares == pytest.approx(5_000.0)
    assert result.equity_curve[sell_index].equity == pytest.approx(104_000.0)


def test_engine_applies_sell_cooldown_after_technical_breakdown():
    config = _config(
        initial_position_pct=0.4,
        target_position_pct=0.4,
        breakdown_volume_ratio=1.0,
        sell_cooldown_days=10,
    )
    engine = BacktestEngine()

    result = engine.run(
        config=config,
        fund_nav=_navs([1.0] * 8),
        signal_bars=_bars(
            closes=[10.0, 10.2, 10.4, 9.8, 10.4, 9.7, 10.3, 9.6],
            volumes=[100.0, 100.0, 100.0, 180.0, 100.0, 180.0, 100.0, 180.0],
        ),
    )

    sells = [trade for trade in result.trades if trade.action == "sell"]
    assert sells == []


def test_engine_continues_selling_during_post_sell_observation_window():
    config = _config(
        initial_position_pct=0.2,
        target_position_pct=0.2,
        breakdown_volume_ratio=1.0,
        sell_cooldown_days=10,
    )
    engine = BacktestEngine()

    result = engine.run(
        config=config,
        fund_nav=_navs([1.0, 1.0, 1.0, 1.0, 0.87, 0.86, 0.85, 0.84, 0.83]),
        signal_bars=_bars(
            closes=[10.0, 10.2, 10.4, 10.8, 10.1, 9.9, 9.8, 9.7, 9.6],
            volumes=[100.0, 100.0, 100.0, 120.0, 220.0, 100.0, 100.0, 100.0, 100.0],
        ),
    )

    sells = [trade for trade in result.trades if trade.action == "sell"]
    assert [sell.batch_type for sell in sells[:2]] == ["high_position", "confirmation"]
    assert any(sell.batch_type == "core" and sell.event_type == "post_sell_observation" for sell in sells)
    assert any("卖后观察窗口" in sell.reason for sell in sells)


def test_engine_restarts_post_sell_observation_after_followup_sell():
    config = _config(
        initial_position_pct=0.2,
        target_position_pct=0.2,
        breakdown_volume_ratio=1.0,
        sell_cooldown_days=10,
    )
    engine = BacktestEngine()

    result = engine.run(
        config=config,
        fund_nav=_navs([1.0, 1.0, 1.0, 1.0, 0.87, 0.86, 0.85, 0.84, 0.83, 0.82, 0.81]),
        signal_bars=_bars(
            closes=[10.0, 10.2, 10.4, 10.8, 10.1, 9.9, 9.8, 9.7, 9.6, 9.5, 9.4],
            volumes=[100.0, 100.0, 100.0, 120.0, 220.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
        ),
    )

    core_sells = [
        trade for trade in result.trades
        if trade.action == "sell" and trade.batch_type == "core"
    ]
    assert len(core_sells) >= 2
    assert all(trade.event_type == "post_sell_observation" for trade in core_sells)


def test_engine_protects_core_batch_when_profit_collapses_to_cost_line():
    """核心仓从高位浮盈回吐至成本线附近时，必须触发半仓保护卖出。

    场景：initial_position_pct=0.1, target_position_pct=0.2
    这时 _seed_initial_batches 只 seed 一个 core 批次（10000 股），
    没有 confirmation/high_position/trial 批次分担 peak，
    核心仓独立命中成本线保护条件。"""
    config = _config(
        initial_position_pct=0.1,
        target_position_pct=0.2,
        profit_drawdown_trigger_pct=5.0,
    )
    engine = BacktestEngine()

    # NAV 路径：1.0 → 1.15（core peak=15%）→ 1.005（core current=0.5%）
    # 命中核心仓成本线保护：peak>=10 且 current<=1.5
    result = engine.run(
        config=config,
        fund_nav=_navs([1.0, 1.15, 1.005, 1.005, 1.005]),
        signal_bars=_bars(
            closes=[10.0, 10.1, 10.2, 10.3, 10.4],
            volumes=[100.0, 100.0, 100.0, 100.0, 100.0],
        ),
    )

    core_sells = [
        trade for trade in result.trades
        if trade.action == "sell" and trade.batch_type == "core"
    ]
    assert core_sells, "核心仓应该在成本线保护事件触发时卖出半仓"
    first_core_sell = core_sells[0]
    assert "核心仓" in first_core_sell.reason
    assert "成本线" in first_core_sell.reason
    # 只 seed 了核心仓 10000 股，半仓保护 = 5000 股
    assert first_core_sell.shares == pytest.approx(5_000.0)


def test_engine_core_protection_not_blocked_by_sell_cooldown():
    """卖出冷却期激活时，核心仓成本线保护事件仍能触发卖出，不被冷却期阻断。

    场景：只 seed 核心仓（initial=0.1, target=0.2），
    先在 Day1 触发 technical_breakdown 设置卖出冷却期，
    然后核心仓 peak 涨到 15%、回吐到 0.5%，核心仓保护应绕过冷却期。"""
    config = _config(
        initial_position_pct=0.1,
        target_position_pct=0.2,
        breakdown_volume_ratio=1.0,
        sell_cooldown_days=10,
        profit_drawdown_trigger_pct=5.0,
    )
    engine = BacktestEngine()

    result = engine.run(
        config=config,
        fund_nav=_navs([1.0, 1.15, 1.005, 1.005, 1.005, 1.005]),
        signal_bars=_bars(
            closes=[10.0, 10.8, 10.1, 10.0, 10.0, 10.0],
            volumes=[100.0, 120.0, 220.0, 100.0, 100.0, 100.0],
        ),
    )

    core_sells = [
        trade for trade in result.trades
        if trade.action == "sell" and trade.batch_type == "core"
    ]
    assert core_sells, "核心仓保护事件应绕过冷却期直接触发卖出"


def test_engine_core_tier1_high_peak_takeprofit_triggers_before_cost_line():
    """核心仓 tier1 高位止盈：peak≥50% 且回撤≥15% 就触发，不必等到成本线。

    场景：核心仓 NAV 1.0 → 1.6（peak=60%）→ 1.4（回撤 20%），
    tier1 条件（peak≥50 且 drawdown≥15）在 Day2 就应命中，卖半仓保护 45% 利润。"""
    config = _config(
        initial_position_pct=0.1,
        target_position_pct=0.2,
        profit_drawdown_trigger_pct=5.0,
    )
    engine = BacktestEngine()

    result = engine.run(
        config=config,
        fund_nav=_navs([1.0, 1.6, 1.4, 1.4, 1.4]),
        signal_bars=_bars(
            closes=[10.0, 10.1, 10.2, 10.3, 10.4],
            volumes=[100.0, 100.0, 100.0, 100.0, 100.0],
        ),
    )

    core_sells = [
        trade for trade in result.trades
        if trade.action == "sell" and trade.batch_type == "core"
    ]
    assert core_sells, "核心仓应在 tier1（高位止盈）就触发，无需等成本线"
    first_sell = core_sells[0]
    assert first_sell.batch_return_pct == pytest.approx(40.0)  # 卖出时收益仍在 40% 高位
    assert "高位止盈" in first_sell.reason
    assert "tier1" in first_sell.reason


def test_engine_core_tier2_mid_peak_takeprofit_triggers_on_moderate_drawdown():
    """核心仓 tier2 中位止盈：peak≥20% 且回撤≥12% 触发。

    场景：核心仓 NAV 1.0 → 1.25（peak=25%）→ 1.10（回撤 15%），
    tier2 条件（peak≥20 且 drawdown≥12）在 Day2 应命中。"""
    config = _config(
        initial_position_pct=0.1,
        target_position_pct=0.2,
        profit_drawdown_trigger_pct=5.0,
    )
    engine = BacktestEngine()

    result = engine.run(
        config=config,
        fund_nav=_navs([1.0, 1.25, 1.10, 1.10, 1.10]),
        signal_bars=_bars(
            closes=[10.0, 10.1, 10.2, 10.3, 10.4],
            volumes=[100.0, 100.0, 100.0, 100.0, 100.0],
        ),
    )

    core_sells = [
        trade for trade in result.trades
        if trade.action == "sell" and trade.batch_type == "core"
    ]
    assert core_sells, "核心仓应在 tier2（中位止盈）触发"
    first_sell = core_sells[0]
    assert first_sell.batch_return_pct == pytest.approx(10.0)  # 卖出时收益仍在 10%
    assert "中位止盈" in first_sell.reason
    assert "tier2" in first_sell.reason


def test_engine_core_stop_loss_clears_full_core_position():
    """核心仓曾经浮盈但后续深度回撤触发止损清仓。

    前置条件：peak≥5%（曾经浮盈），然后回撤到 -8% 以下才触发止损，
    避免抢占一路下跌场景的常规 technical_breakdown / 组合级 stop_loss 路径。"""
    config = _config(
        initial_position_pct=0.1,
        target_position_pct=0.2,
        profit_drawdown_trigger_pct=5.0,
        stop_loss_trigger_pct=50.0,  # 组合级止损设高，让核心仓自身止损先触发
    )
    engine = BacktestEngine()

    # NAV 路径：1.0 → 1.08（peak=8%）→ 0.9（current=-10%）
    result = engine.run(
        config=config,
        fund_nav=_navs([1.0, 1.08, 0.9, 0.9, 0.9]),
        signal_bars=_bars(
            closes=[10.0, 10.1, 10.2, 10.3, 10.4],
            volumes=[100.0, 100.0, 100.0, 100.0, 100.0],
        ),
    )

    core_sells = [
        trade for trade in result.trades
        if trade.action == "sell" and trade.batch_type == "core"
    ]
    assert core_sells, "核心仓应触发止损清仓"
    first_sell = core_sells[0]
    # 止损清仓：全部核心仓 shares（初始 10000）都卖掉
    assert first_sell.shares == pytest.approx(10_000.0)
    assert "止损" in first_sell.reason


def test_engine_core_continues_selling_in_post_sell_window_when_trend_not_repaired():
    """核心仓卖出后 3 天观察窗口内，若信号 ETF 仍在关键 EXPMA 下方
    且核心仓仍处保护档位，就继续卖，无需等 10 天冷却。

    场景：core seed 10000 股，peak 涨到 25%，然后连续 4 天回撤，
    signal ETF 破位不修复。期望：Day2 触发 tier2 卖出 5000，
    Day3~Day5 观察窗口内继续卖，最终 shares 应大幅减少（>1 次核心仓卖出）。"""
    config = _config(
        initial_position_pct=0.1,
        target_position_pct=0.2,
        breakdown_volume_ratio=1.0,
        sell_cooldown_days=10,
        expma_window=3,
        profit_drawdown_trigger_pct=5.0,
    )
    engine = BacktestEngine()

    # NAV: 1.0 → 1.25(peak) → 1.10(drawdown 15%, tier2 命中) → 1.08 → 1.05 → 1.02
    # signal ETF 高位后连续下跌保持在 EXPMA 下方
    result = engine.run(
        config=config,
        fund_nav=_navs([1.0, 1.30, 1.15, 1.10, 1.08, 0.95, 0.95, 0.95]),
        signal_bars=_bars(
            closes=[10.0, 12.5, 9.5, 9.3, 9.1, 8.5, 8.5, 8.5],
            volumes=[100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
        ),
    )

    core_sells = [
        trade for trade in result.trades
        if trade.action == "sell" and trade.batch_type == "core"
    ]
    assert len(core_sells) == 2, (
        f"核心仓应该卖 2 次（第1次 tier2 半仓 Day2，第2次观察期末全部 Day5），实际 {len(core_sells)} 次"
    )
    # 第一次是 tier2 半仓保护
    assert core_sells[0].shares == pytest.approx(5_000.0)
    assert core_sells[0].event_type == "profit_drawdown"
    # 第二次应该是观察期末的最终卖出（通过 post_sell_observation）
    assert core_sells[1].shares == pytest.approx(5_000.0)
    assert core_sells[1].event_type == "post_sell_observation", "第二次卖应该由 post_sell_observation 触发（观察期末）"


# ── Task 3: buy path two-layer observation model ──────────────────────────


def _build_breakout_series(confirmed: bool = True):
    """Build signal bars with a volume breakout above EXPMA at index 6.

    expma_window=3, buy_volume_window=3 (from _config default).
    - 6 flat bars at close=10.0, vol=100 (EXPMA converges to 10.0)
    - index 6: close=12.0, vol=150 -> buy trigger (volume breakout above EXPMA)
    - T+1/T+2: confirmed -> stays at 12.0; not confirmed -> T+1 drops to 9.0
    - index 9: T+3 execution day
    """
    closes = [10.0] * 6 + [12.0]
    volumes = [100.0] * 6 + [150.0]
    if confirmed:
        closes.extend([12.0, 12.0, 12.0])
        volumes.extend([100.0, 100.0, 100.0])
    else:
        closes.extend([9.0, 12.0, 12.0])  # T+1 falls back below EXPMA
        volumes.extend([100.0, 100.0, 100.0])
    return _navs([1.0] * len(closes)), _bars(closes, volumes)


def _first_buy_trigger_date(signal_bars, config):
    from app.backtest.trigger_scanner import TriggerScanner

    scanner = TriggerScanner(config)
    triggers = scanner.scan(signal_bars)
    buys = [t for t in triggers if t.kind == "buy"]
    assert buys, "Expected at least one buy trigger"
    return buys[0].date


def test_buy_trigger_fills_on_T_plus_3_when_observation_confirms():
    fund_nav, signal_bars = _build_breakout_series(confirmed=True)
    config = _config()
    result = BacktestEngine().run(config, fund_nav, signal_bars)
    buys = [t for t in result.trades if t.action == "buy"]
    assert len(buys) == 1
    trigger_date = _first_buy_trigger_date(signal_bars, config)
    assert buys[0].date == trigger_date + timedelta(days=3)


def test_buy_not_confirmed_does_not_buy_and_records_gate():
    fund_nav, signal_bars = _build_breakout_series(confirmed=False)
    config = _config()
    result = BacktestEngine().run(config, fund_nav, signal_bars)
    assert not [t for t in result.trades if t.action == "buy"]
    gates = [
        e for e in result.events
        if e.get("details", {}).get("gate") == "observation_not_confirmed"
    ]
    assert gates, "Expected observation_not_confirmed gate event"


# ── Task 4: sell path two-layer observation model ─────────────────────────


def _build_breakdown_series(confirmed: bool = True):
    """Build signal bars with a volume breakdown below EXPMA at index 6.

    expma_window=3, buy_volume_window=3 (from _config default).
    - 6 flat bars at close=10.0, vol=100 (EXPMA converges to 10.0)
    - index 6: close=8.0, vol=200 -> sell trigger (volume breakdown below EXPMA)
    - T+1/T+2: confirmed -> stays at 8.0; not confirmed -> T+1 bounces to 12.0
    - index 9: T+3 execution day
    Fund NAV drops to 0.85 so batch breakdown_sell_allowed triggers.
    """
    closes = [10.0] * 6 + [8.0]
    volumes = [100.0] * 6 + [200.0]
    if confirmed:
        closes.extend([8.0, 8.0, 8.0])
        volumes.extend([100.0, 100.0, 100.0])
    else:
        closes.extend([12.0, 8.0, 8.0])  # T+1 reclaims above EXPMA
        volumes.extend([100.0, 100.0, 100.0])
    fund_nav = _navs([1.0] * 6 + [0.85] * (len(closes) - 6))
    return fund_nav, _bars(closes, volumes)


def _first_sell_trigger_date(signal_bars, config):
    from app.backtest.trigger_scanner import TriggerScanner

    scanner = TriggerScanner(config)
    triggers = scanner.scan(signal_bars)
    sells = [t for t in triggers if t.kind == "sell"]
    assert sells, "Expected at least one sell trigger"
    return sells[0].date


def test_sell_trigger_fills_on_T_plus_3_after_observation_confirms():
    fund_nav, signal_bars = _build_breakdown_series(confirmed=True)
    config = _config(initial_position_pct=0.2, breakdown_volume_ratio=1.5)
    result = BacktestEngine().run(config, fund_nav, signal_bars)
    sells = [t for t in result.trades if t.action == "sell"]
    assert len(sells) >= 1
    trigger_date = _first_sell_trigger_date(signal_bars, config)
    assert sells[0].date == trigger_date + timedelta(days=3)


def test_sell_not_confirmed_does_not_sell():
    fund_nav, signal_bars = _build_breakdown_series(confirmed=False)
    config = _config(initial_position_pct=0.2, breakdown_volume_ratio=1.5)
    result = BacktestEngine().run(config, fund_nav, signal_bars)
    assert not [t for t in result.trades if t.action == "sell"]
    assert [
        e for e in result.events
        if e.get("details", {}).get("gate") == "observation_not_confirmed"
    ]


# ── Task 5: visible gates + incomplete window handling ────────────────────


def test_buy_at_full_position_records_target_reached_gate():
    """Buy trigger confirms but position already at target -> hold with gate=target_reached."""
    # initial_position_pct=0.19, fund NAV rises to 1.1 during observation
    # -> position_pct > target -> _decide_buy returns hold with target_reached
    closes = [10.0] * 6 + [12.0, 12.0, 12.0, 12.0]
    volumes = [100.0] * 6 + [150.0, 100.0, 100.0, 100.0]
    fund_nav = _navs([1.0] * 8 + [1.1, 1.1])
    signal_bars = _bars(closes, volumes)
    config = _config(initial_position_pct=0.19, target_position_pct=0.2)
    result = BacktestEngine().run(config, fund_nav, signal_bars)
    assert not [t for t in result.trades if t.action == "buy"]
    assert any(
        e.get("details", {}).get("gate") == "target_reached"
        for e in result.events
    )


def test_trigger_near_last_bar_records_incomplete_window():
    """Buy trigger near end of data -> window incomplete -> hold with gate=incomplete_window."""
    # 8 bars total, trigger at index 6, observation until index 8 (beyond data)
    closes = [10.0] * 6 + [12.0, 12.0]
    volumes = [100.0] * 6 + [150.0, 100.0]
    fund_nav = _navs([1.0] * 8)
    signal_bars = _bars(closes, volumes)
    config = _config()
    result = BacktestEngine().run(config, fund_nav, signal_bars)
    assert not [t for t in result.trades if t.action == "buy"]
    assert any(
        e.get("details", {}).get("gate") == "incomplete_window"
        for e in result.events
    )
