from app.trading_room.conversation.presets import (
    preset_extra_skills, preset_participants, preset_question_text,
)
from app.trading_room.conversation.schemas import PresetId


def test_daily_action_participants_are_five():
    parts = preset_participants(PresetId.DAILY_ACTION)
    assert set(parts) == {
        "portfolio_risk", "market_regime", "theme_fund", "buy", "sell_protection",
    }


def test_discovery_extra_skills_bind_to_theme_fund_only():
    theme_extras = preset_extra_skills(PresetId.DISCOVERY, "theme_fund")
    assert "hithink-sector-selector" in theme_extras
    assert "hithink-fund-selector" in theme_extras
    assert "sector-rotation-analysis" in theme_extras
    # 其它角色不应被打扰
    assert preset_extra_skills(PresetId.DISCOVERY, "buy") == ()
    # 非 discovery preset 也不加
    assert preset_extra_skills(PresetId.RISK_SCAN, "theme_fund") == ()


def test_preset_question_texts_present():
    for p in PresetId:
        text = preset_question_text(p)
        assert text and isinstance(text, str)
