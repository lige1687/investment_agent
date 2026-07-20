"""Quick-action presets: fixed routing + per-preset skill augmentation."""

from __future__ import annotations

from app.trading_room.conversation.schemas import PresetId

_PARTICIPANTS: dict[PresetId, tuple[str, ...]] = {
    PresetId.DAILY_ACTION: (
        "portfolio_risk", "market_regime", "theme_fund", "buy", "sell_protection",
    ),
    PresetId.DISCOVERY: ("market_regime", "theme_fund", "buy"),
    PresetId.RISK_SCAN: ("portfolio_risk",),
    PresetId.MARKET_READ: ("market_regime",),
}

_QUESTION_TEXTS: dict[PresetId, str] = {
    PresetId.DAILY_ACTION: "扫描我当前所有持仓，给出今日操作建议（买/卖/持有/观察）。",
    PresetId.DISCOVERY: "结合当前市场热点和板块轮动，为我发现值得研究的新机会。",
    PresetId.RISK_SCAN: "深度检查我的组合风险：回撤、集中度、题材暴露重叠、流动性。",
    PresetId.MARKET_READ: "解读当前市场状态：宏观、指数、资金流向、板块轮动阶段。",
}

_DISCOVERY_THEME_FUND_EXTRAS = (
    "hithink-sector-selector",
    "hithink-fund-selector",
    "sector-rotation-analysis",
)


def preset_participants(preset_id: PresetId) -> tuple[str, ...]:
    return _PARTICIPANTS[preset_id]


def preset_question_text(preset_id: PresetId) -> str:
    return _QUESTION_TEXTS[preset_id]


def preset_extra_skills(preset_id: PresetId, role: str) -> tuple[str, ...]:
    if preset_id is PresetId.DISCOVERY and role == "theme_fund":
        return _DISCOVERY_THEME_FUND_EXTRAS
    return ()
