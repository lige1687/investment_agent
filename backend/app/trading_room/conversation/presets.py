"""Quick-action presets. Task 5 fills in the full map."""

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


def preset_participants(preset_id: PresetId) -> tuple[str, ...]:
    return _PARTICIPANTS[preset_id]
