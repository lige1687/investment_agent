from datetime import date

from app.backtest.batch_skill_router import BatchTradingSkillRouter
from app.backtest.events import BacktestEvent
from app.backtest.models import BacktestConfig, PortfolioSnapshot
from app.backtest.strategy import StrategyDecision


def _config() -> BacktestConfig:
    return BacktestConfig(
        fund_code="001513",
        fund_name="易方达信息产业混合A",
        signal_code="sh515880",
        signal_name="通信ETF参考",
    )


def _snapshot() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        date=date(2026, 1, 5),
        cash=80_000.0,
        shares=20_000.0,
        nav=1.0,
        equity=100_000.0,
        position_pct=0.2,
        cumulative_return_pct=0.0,
        peak_return_pct=0.0,
    )


def test_router_routes_account_risk_to_position_stop_loss_and_sell_execution():
    event = BacktestEvent(
        event_type="account_risk",
        date=date(2026, 1, 5),
        reason="账户级风控触发，必须优先重新评估风险",
        details={"trigger_signals": [{"priority": "P0", "trigger_family": "account_risk"}]},
        snapshot=_snapshot(),
    )

    route = BatchTradingSkillRouter(_config()).route(event, StrategyDecision(action="observe", reason="禁止买入"))

    assert route["system"] == "batch-trading"
    assert route["highest_priority"] == "P0"
    assert route["direct_answer_allowed"] is False
    assert route["required_skill_order"] == [
        "batch-trading-router",
        "batch-trading-position-risk",
        "batch-trading-stop-loss",
        "batch-trading-sell-execution",
    ]
    assert "账户风控优先" in route["priority_note"]


def test_router_routes_buy_candidate_through_market_risk_buy_and_batch_planner():
    event = BacktestEvent(
        event_type="buy_candidate",
        date=date(2026, 1, 5),
        reason="五维买入信号闭环达到至少3项，触发分批买入判断",
        details={"buy_signal": {"signal_level": "middle_buy"}, "trigger_signals": [{"priority": "P3"}]},
        snapshot=_snapshot(),
    )

    route = BatchTradingSkillRouter(_config()).route(event, StrategyDecision(action="buy", reason="买入"))

    assert route["classified_intent"] == "buy_or_add"
    assert route["required_skill_order"] == [
        "batch-trading-router",
        "batch-trading-market-regime",
        "batch-trading-position-risk",
        "batch-trading-buy-signal",
        "batch-trading-batch-planner",
    ]


def test_router_routes_profit_and_stop_loss_to_correct_specialists():
    profit_event = BacktestEvent(
        event_type="profit_drawdown",
        date=date(2026, 1, 5),
        reason="收益从阶段高点回撤达到阈值，触发止盈保护判断",
        details={"trigger_signals": [{"priority": "P2", "trigger_family": "take_profit"}]},
        snapshot=_snapshot(),
    )
    stop_event = BacktestEvent(
        event_type="stop_loss",
        date=date(2026, 1, 5),
        reason="持仓亏损达到止损阈值，触发止损判断",
        details={"trigger_signals": [{"priority": "P1", "trigger_family": "stop_loss"}]},
        snapshot=_snapshot(),
    )

    router = BatchTradingSkillRouter(_config())
    profit_route = router.route(profit_event, StrategyDecision(action="sell", reason="止盈"))
    stop_route = router.route(stop_event, StrategyDecision(action="sell", reason="止损"))

    assert profit_route["required_skill_order"] == [
        "batch-trading-router",
        "batch-trading-market-regime",
        "batch-trading-take-profit",
        "batch-trading-sell-execution",
    ]
    assert stop_route["required_skill_order"] == [
        "batch-trading-router",
        "batch-trading-position-risk",
        "batch-trading-stop-loss",
        "batch-trading-sell-execution",
    ]


def test_router_treats_technical_breakdown_as_p1_even_when_profit_signal_is_p2():
    event = BacktestEvent(
        event_type="technical_breakdown",
        date=date(2026, 1, 5),
        reason="参考标的放量跌破EXPMA，触发止盈/止损判断",
        details={"trigger_signals": [{"priority": "P2", "trigger_family": "take_profit"}]},
        snapshot=_snapshot(),
    )

    route = BatchTradingSkillRouter(_config()).route(event, StrategyDecision(action="sell", reason="减仓"))

    assert route["classified_intent"] == "stop_loss_or_breakdown"
    assert route["highest_priority"] == "P1"
    assert route["required_skill_order"] == [
        "batch-trading-router",
        "batch-trading-position-risk",
        "batch-trading-stop-loss",
        "batch-trading-sell-execution",
    ]


def test_router_routes_system_check_buy_observation_to_buy_chain():
    event = BacktestEvent(
        event_type="system_check",
        date=date(2026, 1, 5),
        reason="测试模式：机械触发系统判断，但未形成实际交易事件",
        details={"trigger_signals": [{"priority": "P3", "trigger_family": "buy_observation"}]},
        snapshot=_snapshot(),
    )

    route = BatchTradingSkillRouter(_config()).route(event, StrategyDecision(action="observe", reason="观察"))

    assert route["classified_intent"] == "buy_or_add"
    assert route["required_skill_order"] == [
        "batch-trading-router",
        "batch-trading-market-regime",
        "batch-trading-position-risk",
        "batch-trading-buy-signal",
        "batch-trading-batch-planner",
    ]
