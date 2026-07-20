import json
import pytest

from app.trading_room.conversation.router import ConversationRouter, RouterError
from app.trading_room.conversation.schemas import PresetId, RouterDecision


class FakeLLMClient:
    def __init__(self, response_text: str):
        self._text = response_text
        self.model = "fake"

    async def chat(self, messages, **kwargs):
        from app.llm.schemas import LLMResponse
        return LLMResponse(text=self._text, model=self.model)


class FakeSkillRegistry:
    def load(self, name):
        from app.trading_room.skill_registry import SkillBundle
        return SkillBundle(name=name, files=("SKILL.md",),
                           content=f"skill for {name}", sha256=f"hash-{name}")


POSITIONS = [{"code": "001513", "name": "易方达信息产业混合A"}]


@pytest.mark.asyncio
async def test_route_resolves_fund_name_and_picks_specialists():
    payload = {
        "resolved_funds": [{"code": "001513", "name": "易方达信息产业混合A", "matched_from": "信息产业那只"}],
        "ambiguities": [],
        "participants": ["sell_protection", "portfolio_risk"],
        "reason": "用户询问减仓",
    }
    router = ConversationRouter(
        client=FakeLLMClient(json.dumps(payload, ensure_ascii=False)),
        skill_registry=FakeSkillRegistry(),
    )
    decision = await router.route(text="信息产业那只要不要减", positions=POSITIONS)
    assert isinstance(decision, RouterDecision)
    assert decision.resolved_funds[0].code == "001513"
    assert "sell_protection" in decision.participants


@pytest.mark.asyncio
async def test_route_returns_ambiguity_when_multiple_matches():
    payload = {
        "resolved_funds": [],
        "ambiguities": [{
            "hint": "存在 A/C 两个份额",
            "candidates": [
                {"code": "001513", "name": "易方达信息产业混合A", "matched_from": "信息产业"},
                {"code": "001514", "name": "易方达信息产业混合C", "matched_from": "信息产业"},
            ],
        }],
        "participants": [],
        "reason": "需要用户澄清份额",
    }
    router = ConversationRouter(
        client=FakeLLMClient(json.dumps(payload, ensure_ascii=False)),
        skill_registry=FakeSkillRegistry(),
    )
    decision = await router.route(text="信息产业那只", positions=POSITIONS)
    assert decision.ambiguities
    assert not decision.participants


@pytest.mark.asyncio
async def test_route_returns_all_participants_for_daily_action_preset():
    router = ConversationRouter(
        client=FakeLLMClient(""),  # preset 不需要 LLM
        skill_registry=FakeSkillRegistry(),
    )
    decision = await router.route(
        text=None, positions=POSITIONS, preset_id=PresetId.DAILY_ACTION,
    )
    assert set(decision.participants) >= {
        "portfolio_risk", "market_regime", "theme_fund", "buy", "sell_protection",
    }


@pytest.mark.asyncio
async def test_route_malformed_output_raises_router_error():
    router = ConversationRouter(
        client=FakeLLMClient("not json"),
        skill_registry=FakeSkillRegistry(),
    )
    with pytest.raises(RouterError):
        await router.route(text="信息产业", positions=POSITIONS)
