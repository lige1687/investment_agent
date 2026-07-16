import json
import pytest

from app.trading_room.conversation.chair import ChairError, ConversationChair
from app.trading_room.conversation.schemas import AmountSuggestion


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
                           content=f"skill {name}", sha256=f"hash-{name}")


AMOUNT = AmountSuggestion(
    action="buy", fund_code="001513",
    minimum=1000, maximum=3000, basis="缺口 30%", caveats=["示例"],
)


@pytest.mark.asyncio
async def test_synthesize_returns_text_and_references_amount():
    payload = {
        "text": "综合专家意见，可小幅加仓，建议区间 1000-3000 元。",
        "data_caveats": ["持仓数据同步于今早 9:31"],
        "reference_amount_fund": "001513",
    }
    chair = ConversationChair(
        client=FakeLLMClient(json.dumps(payload, ensure_ascii=False)),
        skill_registry=FakeSkillRegistry(),
    )
    summary = await chair.synthesize(
        question="信息产业能不能加点",
        specialist_results=[],
        amounts=[AMOUNT],
        context_meta={"data_mode": "live"},
    )
    assert "1000" in summary.text
    assert summary.referenced_amount is AMOUNT
    assert summary.data_caveats


@pytest.mark.asyncio
async def test_synthesize_rejects_amount_outside_range():
    payload = {
        "text": "建议投入 8000 元。",  # 区间外
        "data_caveats": [],
        "reference_amount_fund": "001513",
    }
    chair = ConversationChair(
        client=FakeLLMClient(json.dumps(payload, ensure_ascii=False)),
        skill_registry=FakeSkillRegistry(),
    )
    with pytest.raises(ChairError):
        await chair.synthesize(
            question="q", specialist_results=[],
            amounts=[AMOUNT], context_meta={},
        )


@pytest.mark.asyncio
async def test_synthesize_no_amount_still_works():
    payload = {"text": "综合意见：建议观察。", "data_caveats": [], "reference_amount_fund": None}
    chair = ConversationChair(
        client=FakeLLMClient(json.dumps(payload, ensure_ascii=False)),
        skill_registry=FakeSkillRegistry(),
    )
    summary = await chair.synthesize(
        question="q", specialist_results=[], amounts=[], context_meta={},
    )
    assert summary.referenced_amount is None
