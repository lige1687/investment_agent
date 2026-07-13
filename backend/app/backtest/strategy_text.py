"""Compile user strategy text into deterministic backtest config overrides."""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from app.backtest.models import BacktestConfig


def apply_strategy_text(
    config: BacktestConfig,
    strategy_text: str | None,
) -> tuple[BacktestConfig, dict[str, Any]]:
    text = (strategy_text or "").strip()
    if not text:
        return config, {
            "source": "default",
            "recognized_rules": [],
            "notes": ["未提供自定义策略文本，本次使用预设策略参数"],
        }

    updated = config
    recognized: list[str] = []
    notes: list[str] = []

    total_position_pct = _extract_pct_after(text, "总仓位上限")
    if total_position_pct is not None:
        updated = replace(updated, max_account_position_pct=total_position_pct / 100)
        recognized.append("总仓位上限")

    cash_pct = _extract_pct_after(text, "保留")
    if cash_pct is not None and "现金" in text:
        updated = replace(updated, min_cash_pct=cash_pct / 100)
        recognized.append("现金保留比例")
        if total_position_pct is None:
            updated = replace(updated, max_account_position_pct=1 - cash_pct / 100)

    single_position_pct = _extract_pct_after(text, "特别看好")
    if single_position_pct is not None:
        updated = replace(updated, max_single_position_pct=single_position_pct / 100)
        recognized.append("单标的上限")

    account_drawdown_pct = _extract_pct_after(text, "账户最大回撤红线") or _extract_pct_after(text, "总账户最大回撤红线")
    if account_drawdown_pct is not None:
        updated = replace(updated, account_drawdown_redline_pct=account_drawdown_pct)
        recognized.append("账户回撤红线")

    if "弱买点" in text and ("只观察" in text or "不视为正式建仓" in text):
        updated = replace(updated, weak_buy_allows_trade=False)
        recognized.append("弱买点只观察")
    elif "弱买点" in text and "小仓试错" in text:
        updated = replace(updated, weak_buy_allows_trade=True)
        recognized.append("弱买点允许小仓试错")

    if "首次建仓" in text and ("一半" in text or "50%" in text):
        updated = replace(updated, first_entry_plan_ratio=0.5)
        recognized.append("首次建仓半仓")

    high_elastic_stop = _extract_range_midpoint_after(text, "高波动成长")
    if high_elastic_stop is not None:
        updated = replace(updated, stop_loss_trigger_pct=high_elastic_stop)
        recognized.append("高波动成长止损线")

    profit_drawdown = _extract_range_low_after(text, "移动止盈回撤阈值")
    if profit_drawdown is not None:
        updated = replace(updated, profit_drawdown_trigger_pct=profit_drawdown)
        recognized.append("移动止盈回撤阈值")

    if "冷静期" in text:
        cooldown_days = _extract_int_before_or_after(text, "冷静期")
        if cooldown_days is not None:
            updated = replace(updated, buy_cooldown_days=cooldown_days, sell_cooldown_days=cooldown_days)
            recognized.append("交易冷静期")

    notes.append("当前为确定性规则编译器，只识别仓位、回撤、弱买点、建仓比例、止盈止损和冷静期等关键规则")
    if not recognized:
        notes.append("未识别到可执行参数，文本会随本次回测记录但不改变预设参数")

    return updated, {
        "source": "custom_text",
        "recognized_rules": recognized,
        "notes": notes,
    }


def _extract_pct_after(text: str, keyword: str) -> float | None:
    index = text.find(keyword)
    if index < 0:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", text[index:index + 80])
    return float(match.group(1)) if match else None


def _extract_range_low_after(text: str, keyword: str) -> float | None:
    index = text.find(keyword)
    if index < 0:
        return None
    segment = text[index:index + 100]
    range_match = re.search(r"(\d+(?:\.\d+)?)\s*%?\s*[~\-到至]\s*(\d+(?:\.\d+)?)\s*%", segment)
    if range_match:
        return float(range_match.group(1))
    pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", segment)
    return float(pct_match.group(1)) if pct_match else None


def _extract_range_midpoint_after(text: str, keyword: str) -> float | None:
    index = text.find(keyword)
    if index < 0:
        return None
    segment = text[index:index + 120]
    range_match = re.search(r"(\d+(?:\.\d+)?)\s*%?\s*[~\-到至]\s*(\d+(?:\.\d+)?)\s*%", segment)
    if range_match:
        low = float(range_match.group(1))
        high = float(range_match.group(2))
        return (low + high) / 2
    pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", segment)
    return float(pct_match.group(1)) if pct_match else None


def _extract_int_before_or_after(text: str, keyword: str) -> int | None:
    index = text.find(keyword)
    if index < 0:
        return None
    segment = text[max(0, index - 20):index + 40]
    match = re.search(r"(\d+)\s*天", segment)
    return int(match.group(1)) if match else None
