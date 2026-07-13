from datetime import date

from app.backtest.events import BacktestEvent
from app.backtest.models import BacktestConfig, PortfolioSnapshot, ProsperityConfig
from app.backtest.report_agent import ReportAgent
from app.backtest.strategy import StrategyDecision


def _snapshot() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        date=date(2026, 1, 5),
        cash=90_000.0,
        shares=10_000.0,
        nav=1.0,
        equity=100_000.0,
        position_pct=0.1,
        cumulative_return_pct=6.0,
        peak_return_pct=12.0,
    )


def _config() -> BacktestConfig:
    return BacktestConfig(
        fund_code="001513",
        fund_name="易方达信息产业混合A",
        signal_code="sh515880",
        signal_name="通信ETF参考",
        prosperity=ProsperityConfig(score=8, reasons=["景气度高"]),
    )


def test_report_agent_formats_buy_event_using_user_required_sections():
    event = BacktestEvent(
        event_type="buy_candidate",
        date=date(2026, 1, 5),
        reason="五维买入信号闭环达到至少3项，触发分批买入判断",
        details={
            "buy_signal": {
                "signal_level": "middle_buy",
                "recommended_action": "按计划建仓/补仓",
                "passed_count": 4,
                "account_allowed": True,
                "account_reasons": ["账户风控允许"],
                "dimensions": [
                    {"name": "趋势修复", "passed": True, "reason": "满足至少2项趋势修复条件", "details": {}},
                    {"name": "量能健康", "passed": True, "reason": "缩量企稳后温和放量", "details": {}},
                    {"name": "资金回流", "passed": True, "reason": "成交额连续改善且价格同步转强", "details": {}},
                    {"name": "逻辑/催化验证", "passed": True, "reason": "景气度与催化描述通过", "details": {}},
                    {"name": "组合允许", "passed": False, "reason": "组合仓位或高相关暴露越线", "details": {}},
                ],
            }
        },
        snapshot=_snapshot(),
    )
    decision = StrategyDecision(
        action="buy",
        reason="买入信号闭环形成，首次建仓只上计划资金的一半，保留后续确认仓位",
        target_position_delta_pct=0.1,
        observe_days=5,
    )

    report = ReportAgent(_config()).build(event, decision)

    assert report["current_conclusion"]["signal_level"] == "中买点"
    assert report["current_conclusion"]["suggested_action"] == "按计划建仓"
    assert report["account_check"]["risk_control_passed"] is True
    assert report["buy_signal_checks"]["趋势修复"]["passed"] is True
    assert report["buy_signal_checks"]["组合允许"]["passed"] is False
    assert "突破后第一次回踩不破" in report["trigger_conditions"]["upgrade_conditions"]
    assert len(report["risk_warnings"]) == 3
    assert "首次建仓" in report["one_sentence"]


def test_report_agent_formats_sell_event_without_buy_signal():
    event = BacktestEvent(
        event_type="technical_breakdown",
        date=date(2026, 1, 5),
        reason="参考标的放量跌破EXPMA，触发止盈/止损判断",
        details={"close": 10.0, "expma": 10.5, "volume_ratio": 1.8},
        snapshot=_snapshot(),
    )
    decision = StrategyDecision(
        action="sell",
        reason="参考标的放量跌破关键EXPMA，按批次交易系统优先卖出高位/灵活仓和确认仓，核心仓继续观察",
        ratio_of_position=0.5,
        observe_days=3,
    )

    report = ReportAgent(_config()).build(event, decision)

    assert report["current_conclusion"]["signal_level"] == "观察"
    assert report["current_conclusion"]["suggested_action"] == "减仓"
    assert report["account_check"]["current_total_position_safe"] is True
    assert report["trigger_conditions"]["event"] == "参考标的放量跌破EXPMA，触发止盈/止损判断"
    assert report["one_sentence"] == "系统已触发破位减仓条件，先卖高位/灵活仓和确认仓，核心仓只观察是否重新站回关键均线。"
