"""MonitoringAlertParser unit tests — cover each pattern + fallback."""
from app.services.monitoring_alert import MonitoringAlertParser


# ── price threshold ─────────────────────────────────────────────────────

def test_price_below_bare_number_creates_price_below_alert():
    p = MonitoringAlertParser()
    alerts = p.parse_bullet("001513 净值跌破 5.5 立即通知")
    assert len(alerts) == 1
    a = alerts[0]
    assert a.symbol == "001513"
    assert a.alert_type == "price_below"
    assert a.threshold == 5.5
    assert a.direction == "below"


def test_price_above_verb_creates_price_above_alert():
    p = MonitoringAlertParser()
    alerts = p.parse_bullet("022184 涨破 7.0 减半仓")
    assert len(alerts) == 1
    assert alerts[0].alert_type == "price_above"
    assert alerts[0].threshold == 7.0
    assert alerts[0].direction == "above"


def test_number_with_percent_is_NOT_treated_as_price():
    """5.5% is a change_pct, not a price of 5.5."""
    p = MonitoringAlertParser()
    alerts = p.parse_bullet("001513 跌破 5.5% 立即通知")
    assert alerts[0].alert_type == "change_pct"


# ── change_pct ──────────────────────────────────────────────────────────

def test_signed_negative_percent_maps_to_below():
    p = MonitoringAlertParser()
    alerts = p.parse_bullet("013171 若继续下跌至 -40% 需评估止损")
    assert alerts[0].alert_type == "change_pct"
    assert alerts[0].threshold == -40.0
    assert alerts[0].direction == "below"


def test_signed_positive_percent_maps_to_above():
    p = MonitoringAlertParser()
    alerts = p.parse_bullet("易方达信息产业浮盈继续上涨至 +50%")
    assert alerts[0].alert_type == "change_pct"
    assert alerts[0].threshold == 50.0
    assert alerts[0].direction == "above"


def test_unsigned_percent_with_up_verb_is_positive():
    p = MonitoringAlertParser()
    alerts = p.parse_bullet("001513 涨超 10% 减仓一半")
    assert alerts[0].threshold == 10.0
    assert alerts[0].direction == "above"


def test_unsigned_percent_with_down_verb_is_negative():
    p = MonitoringAlertParser()
    alerts = p.parse_bullet("022184 跌超 8% 立即通知")
    assert alerts[0].alert_type == "change_pct"
    assert alerts[0].threshold == -8.0
    assert alerts[0].direction == "below"


# ── consecutive days ───────────────────────────────────────────────────

def test_consecutive_down_days():
    p = MonitoringAlertParser()
    alerts = p.parse_bullet("013171 连续 3 日下跌")
    assert alerts[0].alert_type == "consecutive_down"
    assert alerts[0].threshold == 3.0


def test_consecutive_up_days_use_up_alert_type():
    p = MonitoringAlertParser()
    alerts = p.parse_bullet("001513 连续 5 天上涨可考虑加仓")
    assert alerts[0].alert_type == "consecutive_up"
    assert alerts[0].threshold == 5.0


# ── fallback / symbol inheritance ──────────────────────────────────────

def test_bullet_with_no_recognizable_pattern_falls_back_to_technical():
    p = MonitoringAlertParser()
    alerts = p.parse_bullet("尾盘科技板块放量下跌立即通知")
    assert len(alerts) == 1
    assert alerts[0].alert_type == "technical"
    assert "尾盘" in alerts[0].note


def test_bullet_with_no_code_inherits_default_symbol():
    """When the LLM writes '继续下跌立即通知' with no code, inherit target
    fund's code so the alert still points at something."""
    p = MonitoringAlertParser(default_symbol_from_target="001513")
    alerts = p.parse_bullet("跌破 5.5 立即通知")
    assert alerts[0].symbol == "001513"


def test_bullet_with_no_code_and_no_default_uses_portfolio_placeholder():
    p = MonitoringAlertParser()
    alerts = p.parse_bullet("跌破 5.5")
    assert alerts[0].symbol == "_portfolio_"


def test_empty_bullet_yields_no_alerts():
    p = MonitoringAlertParser()
    assert p.parse_bullet("") == []
    assert p.parse_bullet("   ") == []


def test_multiple_symbols_in_one_bullet_yields_one_alert_each():
    """If the LLM says '001513 和 022184 跌破 5%', spawn one alert per code."""
    p = MonitoringAlertParser()
    alerts = p.parse_bullet("001513 和 022184 跌超 5% 立即通知")
    codes = sorted(a.symbol for a in alerts)
    assert codes == ["001513", "022184"]
    for a in alerts:
        assert a.alert_type == "change_pct"
        assert a.threshold == -5.0


def test_cjk_adjacent_digits_still_extract_fund_code():
    """Regression: '001513净值跌破 10' — Python 3 unicode \\b treats CJK as
    word char, so /\\b\\d{6}\\b/ misses this. Must use non-digit lookaround."""
    p = MonitoringAlertParser()
    alerts = p.parse_bullet("001513净值跌破10.0（-6.5%）")
    # Should extract 001513, not fall back to _portfolio_
    assert any(a.symbol == "001513" for a in alerts)


def test_note_preserves_original_text_for_ui():
    """The full bullet lives in `note` so the UI can show it verbatim."""
    p = MonitoringAlertParser()
    original = "001513 净值跌破 5.5 立即减仓一半"
    alerts = p.parse_bullet(original)
    assert alerts[0].note == original
