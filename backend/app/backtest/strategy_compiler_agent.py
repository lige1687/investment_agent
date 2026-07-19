"""AI strategy compiler: natural-language strategy text -> executable config."""
from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import Any, Protocol

from app.backtest.models import BacktestConfig
from app.backtest.strategy_text import apply_strategy_text
from app.config import settings
from app.llm.registry import get_llm_client

logger = logging.getLogger(__name__)


class StrategyCompilerClient(Protocol):
    async def complete_json(self, prompt: str) -> dict[str, Any]:
        ...


class RegistryStrategyCompilerClient:
    """Uses the LLM registry to compile strategies (via get_llm_client)."""

    def __init__(self, role: str = "backtest_compiler"):
        self.role = role

    async def complete_json(self, prompt: str) -> dict[str, Any]:
        client = get_llm_client(self.role)

        # Call chat with the prompt; expect structured JSON response
        response = await client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=8192,
        )

        text = response.get("text", "")
        return _parse_json_object(text)


class StrategyCompilerAgent:
    """Uses AI to compile a user's full trading system into strategy DSL."""

    def __init__(self, client: StrategyCompilerClient | None = None):
        self.client = client or RegistryStrategyCompilerClient()

    async def compile(self, strategy_text: str) -> dict[str, Any]:
        return await self.client.complete_json(_build_compile_prompt(strategy_text))


async def compile_and_apply_strategy_text(
    config: BacktestConfig,
    strategy_text: str | None,
    compiler: StrategyCompilerAgent | None = None,
    use_ai: bool = True,
) -> tuple[BacktestConfig, dict[str, Any]]:
    text = (strategy_text or "").strip()
    if not text:
        return config, {
            "source": "default",
            "recognized_rules": [],
            "notes": ["未提供自定义策略文本，本次使用预设策略参数"],
        }

    if not use_ai:
        return apply_strategy_text(config, text)

    agent = compiler or StrategyCompilerAgent()
    try:
        compiled = await agent.compile(text)
        updated = apply_compiled_strategy(config, compiled)
        return updated, {
            "source": "ai_compiler",
            "recognized_rules": compiled.get("recognized_rules", []),
            "unrecognized_rules": compiled.get("unrecognized_rules", []),
            "compiled_strategy": compiled,
            "notes": [
                "本次使用 AI 策略编译 Agent 将自然语言策略拆解为结构化执行参数",
                "AI 只负责编译策略，回测执行仍由确定性引擎完成",
            ],
        }
    except Exception as exc:
        logger.warning("AI strategy compiler failed, falling back: %s", exc)
        updated, profile = apply_strategy_text(config, text)
        profile = dict(profile)
        profile["source"] = "ai_fallback"
        profile.setdefault("notes", []).append(f"AI 策略编译失败，已回退到确定性解析器：{exc}")
        return updated, profile


def apply_compiled_strategy(config: BacktestConfig, compiled: dict[str, Any]) -> BacktestConfig:
    updated = config
    account_risk = _dict(compiled.get("account_risk"))
    position_limits = _dict(compiled.get("position_limits"))
    buy_policy = _dict(compiled.get("buy_policy"))
    execution = _dict(compiled.get("execution"))
    category_rules = _dict(compiled.get("category_rules"))
    high_elastic = _dict(category_rules.get("high_elastic"))

    replacements: dict[str, Any] = {}
    _assign_pct(replacements, "max_account_position_pct", account_risk.get("max_total_position_pct"))
    _assign_pct(replacements, "min_cash_pct", account_risk.get("min_cash_pct"))
    _assign_number(replacements, "account_drawdown_redline_pct", account_risk.get("account_drawdown_redline_pct"))
    _assign_pct(replacements, "max_single_position_pct", position_limits.get("special_conviction_max_pct"))
    _assign_pct(
        replacements,
        "max_correlated_growth_exposure_pct",
        position_limits.get("correlated_growth_exposure_limit_pct"),
    )
    if buy_policy.get("weak_buy_action") is not None:
        replacements["weak_buy_allows_trade"] = buy_policy.get("weak_buy_action") not in {"observe", "只观察"}
    _assign_number(replacements, "first_entry_plan_ratio", buy_policy.get("first_entry_ratio"))
    _assign_number(replacements, "min_trade_position_pct", execution.get("min_trade_position_pct"))
    _assign_int(replacements, "buy_cooldown_days", execution.get("buy_cooldown_days"))
    _assign_int(replacements, "sell_cooldown_days", execution.get("sell_cooldown_days"))

    trailing = high_elastic.get("trailing_drawdown_pct")
    if isinstance(trailing, list) and trailing:
        _assign_number(replacements, "profit_drawdown_trigger_pct", trailing[0])
    else:
        _assign_number(replacements, "profit_drawdown_trigger_pct", high_elastic.get("trailing_drawdown_pct"))

    stop_loss = high_elastic.get("stop_loss_pct")
    if isinstance(stop_loss, list) and stop_loss:
        numeric = [float(item) for item in stop_loss if isinstance(item, int | float)]
        if numeric:
            replacements["stop_loss_trigger_pct"] = sum(numeric) / len(numeric)
    else:
        _assign_number(replacements, "stop_loss_trigger_pct", stop_loss)

    if replacements:
        updated = replace(updated, **replacements)
    return updated


def _build_compile_prompt(strategy_text: str) -> str:
    return f"""你是交易系统策略编译 Agent。你的任务不是给投资建议，而是把用户的自然语言交易系统拆解为可执行 JSON。

要求：
1. 只输出 JSON，不要 Markdown，不要解释文字。
2. 不要预测市场，不要新增用户没有写的交易规则。
3. 无法执行或依赖缺失数据的规则，放入 unrecognized_rules。
4. 百分比用小数表示仓位比例时输出 0-1，用百分数阈值时输出数字，例如 10% 回撤输出 10。

输出 JSON schema：
{{
  "account_risk": {{
    "max_total_position_pct": 0.9,
    "min_cash_pct": 0.1,
    "account_drawdown_redline_pct": 10
  }},
  "position_limits": {{
    "special_conviction_max_pct": 0.5,
    "normal_conviction_max_pct": 0.15,
    "correlated_growth_exposure_limit_pct": 0.6
  }},
  "buy_policy": {{
    "dimensions": ["trend_repair", "healthy_volume", "funds_return", "logic_catalyst", "portfolio_allowed"],
    "weak_buy_action": "observe",
    "middle_buy_action": "small_build",
    "strong_buy_action": "build_or_add",
    "first_entry_ratio": 0.5
  }},
  "execution": {{
    "min_trade_position_pct": 0.02,
    "buy_cooldown_days": 10,
    "sell_cooldown_days": 10
  }},
  "category_rules": {{
    "high_elastic": {{
      "profit_monitor_pct": 15,
      "trailing_drawdown_pct": [8, 10],
      "stop_loss_pct": [18, 22]
    }}
  }},
  "recognized_rules": [],
  "unrecognized_rules": []
}}

用户策略文本：
{strategy_text}
"""


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped.removeprefix("json").strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ValueError("AI compiler did not return a JSON object")
    payload = json.loads(stripped[start:end + 1])
    if not isinstance(payload, dict):
        raise ValueError("AI compiler JSON was not an object")
    return payload


def _extract_model_text(data: dict[str, Any]) -> str:
    """Extract text from registry chat response."""
    # Registry's chat method returns {"text": "...", ...}
    if isinstance(data, dict):
        text = data.get("text")
        if isinstance(text, str):
            return text
    return ""



def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _assign_pct(target: dict[str, Any], key: str, value: Any) -> None:
    number = _number(value)
    if number is None:
        return
    target[key] = number / 100 if number > 1 else number


def _assign_number(target: dict[str, Any], key: str, value: Any) -> None:
    number = _number(value)
    if number is not None:
        target[key] = number


def _assign_int(target: dict[str, Any], key: str, value: Any) -> None:
    number = _number(value)
    if number is not None:
        target[key] = int(number)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None
