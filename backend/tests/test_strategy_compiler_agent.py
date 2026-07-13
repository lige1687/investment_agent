import pytest

from app.backtest.models import BacktestConfig, ProsperityConfig
from app.backtest.strategy_compiler_agent import (
    StrategyCompilerAgent,
    _extract_model_text,
    _parse_json_object,
    compile_and_apply_strategy_text,
)


class FakeCompilerClient:
    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    async def complete_json(self, prompt: str):
        self.prompts.append(prompt)
        return self.payload


def _config() -> BacktestConfig:
    return BacktestConfig(
        fund_code="001513",
        fund_name="易方达信息产业混合A",
        signal_code="sh515880",
        signal_name="通信ETF参考",
        prosperity=ProsperityConfig(score=8, reasons=["景气度高"]),
    )


@pytest.mark.asyncio
async def test_ai_strategy_compiler_maps_structured_strategy_to_execution_config():
    client = FakeCompilerClient({
        "account_risk": {
            "max_total_position_pct": 0.85,
            "min_cash_pct": 0.15,
            "account_drawdown_redline_pct": 9,
        },
        "position_limits": {
            "special_conviction_max_pct": 0.45,
            "correlated_growth_exposure_limit_pct": 0.55,
        },
        "buy_policy": {
            "weak_buy_action": "observe",
            "first_entry_ratio": 0.4,
        },
        "execution": {
            "min_trade_position_pct": 0.03,
            "buy_cooldown_days": 12,
            "sell_cooldown_days": 15,
        },
        "category_rules": {
            "high_elastic": {
                "trailing_drawdown_pct": [7, 9],
                "stop_loss_pct": [18, 22],
            }
        },
        "recognized_rules": ["账户风控", "五维买入", "高波动成长止损"],
        "unrecognized_rules": ["美股龙头联动暂未接入数据"],
    })

    config, profile = await compile_and_apply_strategy_text(
        _config(),
        "我的完整策略文本",
        compiler=StrategyCompilerAgent(client=client),
    )

    assert config.max_account_position_pct == 0.85
    assert config.min_cash_pct == 0.15
    assert config.account_drawdown_redline_pct == 9
    assert config.max_single_position_pct == 0.45
    assert config.max_correlated_growth_exposure_pct == 0.55
    assert config.weak_buy_allows_trade is False
    assert config.first_entry_plan_ratio == 0.4
    assert config.min_trade_position_pct == 0.03
    assert config.buy_cooldown_days == 12
    assert config.sell_cooldown_days == 15
    assert config.profit_drawdown_trigger_pct == 7
    assert config.stop_loss_trigger_pct == 20
    assert profile["source"] == "ai_compiler"
    assert profile["compiled_strategy"]["unrecognized_rules"] == ["美股龙头联动暂未接入数据"]
    assert "只输出 JSON" in client.prompts[0]


@pytest.mark.asyncio
async def test_ai_strategy_compiler_falls_back_to_deterministic_parser_on_failure():
    class BrokenClient:
        async def complete_json(self, prompt: str):
            raise RuntimeError("model unavailable")

    config, profile = await compile_and_apply_strategy_text(
        _config(),
        "总仓位上限 90%，弱买点：只观察。",
        compiler=StrategyCompilerAgent(client=BrokenClient()),
    )

    assert config.max_account_position_pct == 0.9
    assert config.weak_buy_allows_trade is False
    assert profile["source"] == "ai_fallback"
    assert "model unavailable" in profile["notes"][-1]


def test_strategy_compiler_extracts_json_from_common_model_response_shapes():
    anthropic_text = _extract_model_text({"content": [{"type": "text", "text": '{"ok": true}'}]})
    openai_text = _extract_model_text({"choices": [{"message": {"content": '```json\n{"ok": true}\n```'}}]})

    assert _parse_json_object(anthropic_text) == {"ok": True}
    assert _parse_json_object(openai_text) == {"ok": True}
