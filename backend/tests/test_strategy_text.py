from app.backtest.models import BacktestConfig, ProsperityConfig
from app.backtest.strategy_text import apply_strategy_text


def _config() -> BacktestConfig:
    return BacktestConfig(
        fund_code="001513",
        fund_name="易方达信息产业混合A",
        signal_code="sh515880",
        signal_name="通信ETF参考",
        prosperity=ProsperityConfig(score=8, reasons=["景气度高"]),
    )


def test_apply_strategy_text_overrides_risk_and_execution_parameters():
    text = """
    总仓位上限 90%，必须永远保留 10% 现金。
    特别看好的标的：最高 50%。
    总账户最大回撤红线 10%。
    弱买点：只观察，不视为正式建仓信号。
    首次建仓：只上计划资金的一半。
    高波动成长（半导体、新能源、通信、光模块）：18%~22%。
    启动监控点：盈利 15%，移动止盈回撤阈值：8%~10%。
    """

    config, profile = apply_strategy_text(_config(), text)

    assert config.max_account_position_pct == 0.9
    assert config.min_cash_pct == 0.1
    assert config.max_single_position_pct == 0.5
    assert config.account_drawdown_redline_pct == 10.0
    assert config.weak_buy_allows_trade is False
    assert config.first_entry_plan_ratio == 0.5
    assert config.stop_loss_trigger_pct == 20.0
    assert config.profit_drawdown_trigger_pct == 8.0
    assert profile["source"] == "custom_text"
    assert "总仓位上限" in profile["recognized_rules"]


def test_apply_strategy_text_leaves_config_unchanged_when_text_is_blank():
    config, profile = apply_strategy_text(_config(), "  ")

    assert config == _config()
    assert profile["source"] == "default"
    assert profile["recognized_rules"] == []
