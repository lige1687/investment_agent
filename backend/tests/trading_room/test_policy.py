"""Trading-room policy template and schema contract tests."""

import pytest
from pydantic import ValidationError


def test_mid_term_theme_template_contains_only_confirmed_defaults():
    from app.trading_room.policy import get_policy_template

    template = get_policy_template("mid-term-theme-v1")

    assert template.buy_obvious_threshold == 80
    assert template.conditional_buy_min == 65
    assert template.account_drawdown_warning_pct == 5.0
    assert template.account_drawdown_derisk_pct == 7.5
    assert template.account_drawdown_protection_pct == 10.0
    assert template.percentage_stop_enabled is False
    assert template.stop_priority == (
        "logic_failure",
        "effective_trend_break",
        "percentage_stop",
    )
    assert template.trend_break.consecutive_closes_min == 2
    assert template.trend_break.consecutive_closes_max == 3
    dumped = template.model_dump()
    assert "single_operation_cap" not in dumped
    assert "batch" not in dumped
    assert "risk_budget" not in dumped


def test_import_without_target_allocations_remains_not_ready():
    from app.trading_room.policy import import_policy_template

    policy = import_policy_template("mid-term-theme-v1", target_allocations=[])

    assert policy.ready is False
    assert policy.missing_confirmations == ("target_allocations",)
    assert policy.version_id


def test_confirmed_target_allocations_make_policy_ready_and_versioned():
    from app.trading_room.policy import import_policy_template
    from app.trading_room.schemas import TargetAllocation

    targets = [
        TargetAllocation(scope="theme", key="communication", target_pct=0.20),
        TargetAllocation(scope="theme", key="nasdaq", target_pct=0.20),
    ]
    first = import_policy_template("mid-term-theme-v1", target_allocations=targets)
    second = import_policy_template("mid-term-theme-v1", target_allocations=targets)

    assert first.ready is True
    assert first.missing_confirmations == ()
    assert first.target_allocations == tuple(targets)
    assert first.version_id != second.version_id
    with pytest.raises(ValidationError):
        first.buy_obvious_threshold = 70


def test_target_allocation_rejects_invalid_percentage():
    from app.trading_room.schemas import TargetAllocation

    with pytest.raises(ValidationError):
        TargetAllocation(scope="fund", key="001513", target_pct=1.01)


def test_trading_room_settings_default_to_deepseek_without_exposing_a_key():
    from app.config import Settings

    config = Settings(_env_file=None)

    assert config.trading_room_llm_provider == "deepseek"
    assert config.trading_room_llm_model == "deepseek-v4-flash"
    assert config.trading_room_analysis_temperature == 0.1
    assert config.trading_room_chair_temperature == 0.2
    assert config.execution_preflight_fresh_minutes == 15
    assert "api_key" not in config.model_dump(include={"trading_room_llm_provider", "trading_room_llm_model"})

