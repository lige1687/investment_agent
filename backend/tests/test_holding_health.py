"""HoldingHealthChecker rule tests — each trigger, each severity boundary."""
from app.schemas.guardian import AlertSeverity, AlertTrigger
from app.services.holding_health import (
    HealthThresholds,
    HoldingHealthChecker,
    HoldingSummary,
)


def _h(code: str, name: str, alloc: float, pnl: float, mv: float = 10000.0) -> HoldingSummary:
    return HoldingSummary(code=code, name=name, market_value=mv, pnl_pct=pnl, allocation_pct=alloc)


def _find(alerts, code: str, trigger: AlertTrigger | str):
    tv = trigger.value if hasattr(trigger, "value") else trigger
    for a in alerts:
        atrig = a.trigger if isinstance(a.trigger, str) else a.trigger.value
        if a.code == code and atrig == tv:
            return a
    return None


# ── LOSS_DEEP ─────────────────────────────────────────────────────────────

def test_loss_below_medium_threshold_does_not_alert():
    checker = HoldingHealthChecker()
    alerts = checker.detect_alerts([_h("F1", "小亏基金", alloc=5, pnl=-10)])
    assert _find(alerts, "F1", AlertTrigger.LOSS_DEEP) is None


def test_loss_between_thresholds_is_medium():
    checker = HoldingHealthChecker()
    alerts = checker.detect_alerts([_h("F1", "中亏基金", alloc=5, pnl=-20)])
    a = _find(alerts, "F1", AlertTrigger.LOSS_DEEP)
    assert a is not None and a.severity == AlertSeverity.MEDIUM.value


def test_loss_below_high_threshold_is_high():
    checker = HoldingHealthChecker()
    alerts = checker.detect_alerts([_h("F1", "深亏基金", alloc=5, pnl=-35)])
    a = _find(alerts, "F1", AlertTrigger.LOSS_DEEP)
    assert a is not None and a.severity == AlertSeverity.HIGH.value


def test_tiny_position_loss_ignored():
    """Position too small to matter — skip alert."""
    checker = HoldingHealthChecker()
    alerts = checker.detect_alerts([_h("F1", "尘埃基金", alloc=0.5, pnl=-40)])
    assert _find(alerts, "F1", AlertTrigger.LOSS_DEEP) is None


# ── CONCENTRATION_HIGH ────────────────────────────────────────────────────

def test_single_position_between_thresholds_medium():
    checker = HoldingHealthChecker()
    alerts = checker.detect_alerts([_h("F1", "集中基金", alloc=25, pnl=5)])
    a = _find(alerts, "F1", AlertTrigger.CONCENTRATION_HIGH)
    assert a is not None and a.severity == AlertSeverity.MEDIUM.value


def test_single_position_above_high_threshold_is_high():
    checker = HoldingHealthChecker()
    alerts = checker.detect_alerts([_h("F1", "巨仓基金", alloc=35, pnl=5)])
    a = _find(alerts, "F1", AlertTrigger.CONCENTRATION_HIGH)
    assert a is not None and a.severity == AlertSeverity.HIGH.value


# ── TOP3_CONCENTRATION ────────────────────────────────────────────────────

def test_top3_concentration_below_threshold_no_alert():
    checker = HoldingHealthChecker()
    holdings = [
        _h("F1", "科技A", alloc=15, pnl=5),
        _h("F2", "科技B", alloc=15, pnl=5),
        _h("F3", "科技C", alloc=15, pnl=5),
        _h("F4", "消费", alloc=10, pnl=5),
    ]
    alerts = checker.detect_alerts(holdings)
    assert not any((a.trigger if isinstance(a.trigger, str) else a.trigger.value) == "TOP3_CONCENTRATION" for a in alerts)


def test_top3_concentration_medium_and_anchored_to_biggest():
    checker = HoldingHealthChecker()
    holdings = [
        _h("F1", "领头", alloc=25, pnl=5),
        _h("F2", "老二", alloc=20, pnl=5),
        _h("F3", "老三", alloc=15, pnl=5),
    ]
    alerts = checker.detect_alerts(holdings)
    a = _find(alerts, "F1", AlertTrigger.TOP3_CONCENTRATION)
    assert a is not None
    assert a.severity == AlertSeverity.MEDIUM.value
    # anchored to the biggest one
    assert a.code == "F1"


def test_top3_concentration_high_severity():
    checker = HoldingHealthChecker()
    holdings = [
        _h("F1", "领头", alloc=30, pnl=5),
        _h("F2", "老二", alloc=25, pnl=5),
        _h("F3", "老三", alloc=15, pnl=5),
    ]
    alerts = checker.detect_alerts(holdings)
    a = _find(alerts, "F1", AlertTrigger.TOP3_CONCENTRATION)
    assert a is not None and a.severity == AlertSeverity.HIGH.value


# ── OVERLAP_DUPLICATE ─────────────────────────────────────────────────────

def test_duplicate_share_class_detected():
    checker = HoldingHealthChecker()
    holdings = [
        _h("100055", "富国全球科技互联网A", alloc=12, pnl=8),
        _h("022184", "富国全球科技互联网C", alloc=22, pnl=13),
    ]
    alerts = checker.detect_alerts(holdings)
    # anchored to the biggest of the group (022184)
    a = _find(alerts, "022184", AlertTrigger.OVERLAP_DUPLICATE)
    assert a is not None
    assert a.severity == AlertSeverity.MEDIUM.value
    # Note lists both codes
    assert "100055" in a.note and "022184" in a.note


def test_duplicate_below_5pct_combined_not_flagged():
    checker = HoldingHealthChecker()
    holdings = [
        _h("018922", "纳指A", alloc=1.5, pnl=5),
        _h("018923", "纳指C", alloc=1.5, pnl=5),
    ]
    alerts = checker.detect_alerts(holdings)
    assert not any((a.trigger if isinstance(a.trigger, str) else a.trigger.value) == "OVERLAP_DUPLICATE" for a in alerts)


def test_single_share_class_never_flagged_as_duplicate():
    checker = HoldingHealthChecker()
    alerts = checker.detect_alerts([_h("F1", "唯一基金C", alloc=10, pnl=5)])
    assert not any((a.trigger if isinstance(a.trigger, str) else a.trigger.value) == "OVERLAP_DUPLICATE" for a in alerts)


# ── PROFIT_TAKE ───────────────────────────────────────────────────────────

def test_profit_take_triggers_above_40pct_gain():
    checker = HoldingHealthChecker()
    alerts = checker.detect_alerts([_h("F1", "翻倍基金", alloc=10, pnl=50)])
    a = _find(alerts, "F1", AlertTrigger.PROFIT_TAKE)
    assert a is not None and a.severity == AlertSeverity.MEDIUM.value


def test_profit_take_ignored_for_tiny_position():
    checker = HoldingHealthChecker()
    alerts = checker.detect_alerts([_h("F1", "翻倍尘埃", alloc=0.5, pnl=100)])
    assert _find(alerts, "F1", AlertTrigger.PROFIT_TAKE) is None


# ── Multi-rule stacking ───────────────────────────────────────────────────

def test_one_holding_can_trigger_multiple_alerts():
    """Deep loss + high concentration on the same holding — both should fire."""
    checker = HoldingHealthChecker()
    alerts = checker.detect_alerts([_h("F1", "又亏又重", alloc=32, pnl=-28)])
    triggers = {
        (a.trigger if isinstance(a.trigger, str) else a.trigger.value)
        for a in alerts if a.code == "F1"
    }
    assert "LOSS_DEEP" in triggers
    assert "CONCENTRATION_HIGH" in triggers


def test_custom_thresholds_change_behavior():
    """Aggressive thresholds should flag things default thresholds miss."""
    strict = HealthThresholds(loss_medium_pct=-5.0, single_position_medium=10.0)
    checker = HoldingHealthChecker(strict)
    alerts = checker.detect_alerts([_h("F1", "普通基金", alloc=12, pnl=-8)])
    assert _find(alerts, "F1", AlertTrigger.LOSS_DEEP) is not None
    assert _find(alerts, "F1", AlertTrigger.CONCENTRATION_HIGH) is not None


def test_dict_holding_input_normalized():
    """Real portfolio_summary output comes as dicts, not HoldingSummary."""
    checker = HoldingHealthChecker()
    holdings = [{
        "code": "F1", "name": "字典基金",
        "market_value": 5000, "pnl_pct": -30, "allocation_pct": 8,
    }]
    alerts = checker.detect_alerts(holdings)
    assert _find(alerts, "F1", AlertTrigger.LOSS_DEEP) is not None
