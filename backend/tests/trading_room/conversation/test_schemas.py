import pytest
from pydantic import ValidationError

from app.trading_room.conversation.schemas import (
    AmountSuggestion, MessagePayload, PresetId, RouterDecision, TurnRequest,
)


def test_turn_request_requires_text_or_preset():
    with pytest.raises(ValidationError):
        TurnRequest(text=None, preset_id=None)
    ok_text = TurnRequest(text="信息产业那只要不要减")
    ok_preset = TurnRequest(preset_id=PresetId.DAILY_ACTION)
    assert ok_text.text
    assert ok_preset.preset_id is PresetId.DAILY_ACTION


def test_router_decision_participants_must_be_known():
    ok = RouterDecision(
        resolved_funds=[], ambiguities=[],
        participants=["sell_protection", "portfolio_risk"], reason="test",
    )
    assert ok.participants == ["sell_protection", "portfolio_risk"]
    with pytest.raises(ValidationError):
        RouterDecision(
            resolved_funds=[], ambiguities=[],
            participants=["nonexistent_role"], reason="test",
        )


def test_amount_suggestion_range_valid():
    with pytest.raises(ValidationError):
        AmountSuggestion(
            action="buy", fund_code="001513",
            minimum=5000, maximum=1000, basis="缺口",  # 反区间
            caveats=[],
        )
    ok = AmountSuggestion(
        action="buy", fund_code="001513",
        minimum=1000, maximum=5000, basis="缺口", caveats=["示例"],
    )
    assert ok.maximum >= ok.minimum


def test_message_payload_kind_whitelist():
    ok = MessagePayload(turn_id="t1", kind="routing", payload={"reason": "x"})
    assert ok.kind == "routing"
    with pytest.raises(ValidationError):
        MessagePayload(turn_id="t1", kind="broadcast", payload={})
