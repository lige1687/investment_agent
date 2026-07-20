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


# 区间外引用金额的 fund code / 年份不应触发误报：用 [3000, 5000] 区间，
# 使 001513->1513 与 2026 都落在区间外，从而在有 bug 的正则下失败、修复后通过。
_OUT_OF_RANGE_AMOUNT = AmountSuggestion(
    action="buy", fund_code="001513",
    minimum=3000, maximum=5000, basis="缺口", caveats=[],
)


@pytest.mark.asyncio
async def test_synthesize_ignores_fund_code_in_text():
    """基金代码出现在 text 不应触发区间校验，即便其数值落在区间外。"""
    payload = {
        "text": "001513 建议加仓 3000-5000 元。",
        "data_caveats": [],
        "reference_amount_fund": "001513",
    }
    chair = ConversationChair(
        client=FakeLLMClient(json.dumps(payload, ensure_ascii=False)),
        skill_registry=FakeSkillRegistry(),
    )
    summary = await chair.synthesize(
        question="q", specialist_results=[],
        amounts=[_OUT_OF_RANGE_AMOUNT], context_meta={},
    )
    assert "001513" in summary.text  # 不该抛 ChairError


@pytest.mark.asyncio
async def test_synthesize_ignores_year_in_text():
    """年份（如 2026年）出现在 text 不应触发区间校验。"""
    payload = {
        "text": "2026年展望：建议加仓 3000-5000 元。",
        "data_caveats": [],
        "reference_amount_fund": "001513",
    }
    chair = ConversationChair(
        client=FakeLLMClient(json.dumps(payload, ensure_ascii=False)),
        skill_registry=FakeSkillRegistry(),
    )
    summary = await chair.synthesize(
        question="q", specialist_results=[],
        amounts=[_OUT_OF_RANGE_AMOUNT], context_meta={},
    )
    assert "2026" in summary.text  # 不该抛 ChairError


@pytest.mark.asyncio
async def test_synthesize_still_rejects_out_of_range_yuan_amount():
    """修复后仍须拦截：紧跟金额单位且超出区间的数字。"""
    payload = {
        "text": "建议投入 8000 元。",  # 8000 元，超出 [1000, 3000]
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
