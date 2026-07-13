"""End-to-end-ish test for the InvestmentAgent decision-card flow.

We stub the LLM to script a two-turn conversation:
  Turn 1: model calls `get_portfolio_summary`
  Turn 2: model calls `emit_decision_card` referencing turn-1 evidence
Then verify:
  - Turn-1 tool result was written to the evidence bus with an ev_id
  - Turn-2 message stack contained an `[evidence_id: ev_...]` marker
  - The emitted card was validated + persisted
  - The chat response echoes decision_card + evidence_refs + session_id
"""
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.llm.schemas import (
    LLMResponse,
    LLMUsage,
    Message,
    Role,
    StopReason,
    ToolCall,
)
from app.services import agent_service
from app.services.agent_service import (
    EMIT_DECISION_CARD_TOOL_NAME,
    InvestmentAgent,
)


@pytest_asyncio.fixture
async def db_session():
    import app.models  # noqa: F401 — register all models
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


class _ScriptedLLM:
    """A fake LLM that returns a preset list of responses in order.

    Each call captures the messages+system it was invoked with so tests can
    assert on the tool-result plumbing.
    """
    provider_name = "fake"

    def __init__(self, responses: list[LLMResponse]):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def chat(self, messages, *, tools=None, system=None, temperature=0.3, max_tokens=2048):
        self.calls.append({
            "messages": [self._msg_snapshot(m) for m in messages],
            "system": system,
            "tools": [t.name for t in (tools or [])],
        })
        if not self.responses:
            raise AssertionError("scripted LLM ran out of responses")
        return self.responses.pop(0)

    @staticmethod
    def _msg_snapshot(m: Message) -> dict[str, Any]:
        return {
            "role": m.role.value,
            "content": m.content,
            "tool_calls": [{"name": tc.name, "id": tc.id} for tc in m.tool_calls],
            "tool_results": [
                {"tool_call_id": r.tool_call_id, "content": r.content}
                for r in m.tool_results
            ],
        }


@pytest.mark.asyncio
async def test_agent_writes_evidence_and_persists_decision_card(db_session):
    """Full flow: data tool → evidence stored → decision card emitted."""

    # Preload one holding so get_portfolio_summary returns real data
    from app.models.position import Position
    db_session.add(Position(
        symbol="006503",
        source="yangjibao",
        position_type="fund",
        shares=100.0,
        avg_cost=1.5,
        current_price=1.7,
        market_value=170.0,
        cost_basis=150.0,
        unrealized_pnl=20.0,
        unrealized_pnl_pct=13.33,
    ))
    await db_session.flush()

    # Turn 1: model requests portfolio data
    turn1 = LLMResponse(
        text="Let me check your holdings.",
        tool_calls=[ToolCall(
            id="toolu_1", name="get_portfolio_summary", arguments={},
        )],
        stop_reason=StopReason.TOOL_USE,
        model="fake", usage=LLMUsage(input_tokens=100, output_tokens=20),
    )

    # Turn 2: model emits a decision card citing evidence
    decision_args = {
        "type": "BUY_CANDIDATE",
        "target": {"kind": "fund", "code": "006503", "name": "财通集成电路"},
        "action": {"verb": "HOLD", "confidence": 0.65, "urgency": "MEDIUM"},
        "summary": "已持有,建议观察",
        "dimensions": [
            {
                "key": "technical",
                "score": 7.5,
                "signal": "持仓盈利13%",
                # Filled in after we know the real ev_id
                "evidence_ref": "PLACEHOLDER",
            },
        ],
    }
    turn2 = LLMResponse(
        text="",
        tool_calls=[ToolCall(
            id="toolu_2", name=EMIT_DECISION_CARD_TOOL_NAME, arguments=decision_args,
        )],
        stop_reason=StopReason.TOOL_USE,
        model="fake", usage=LLMUsage(input_tokens=80, output_tokens=40),
    )

    # Turn 3: model wraps up with a short text summary
    turn3 = LLMResponse(
        text="持仓中,盈利13%,建议继续观察。仅供参考,不构成投资建议。",
        stop_reason=StopReason.END_TURN,
        model="fake", usage=LLMUsage(input_tokens=60, output_tokens=25),
    )

    # We can't fill evidence_ref until we see the actual ev_id chosen at
    # runtime, so we patch it in via a wrapper client that mutates turn2
    # right before returning it.
    real_llm = _ScriptedLLM([turn1, turn2, turn3])

    async def wrapped_chat(messages, **kwargs):
        # If we're at turn 2 (after tool result came back), rewrite the
        # evidence_ref placeholder using the actual ev_id from the last
        # tool message.
        if real_llm.responses and real_llm.responses[0] is turn2:
            for m in reversed(messages):
                if m.role == Role.TOOL and m.tool_results:
                    content = m.tool_results[0].content
                    if content.startswith("[evidence_id: "):
                        ev_id = content.split("]", 1)[0].removeprefix("[evidence_id: ").strip()
                        turn2.tool_calls[0].arguments["dimensions"][0]["evidence_ref"] = ev_id
                        break
        return await real_llm.chat(messages, **kwargs)

    fake_client = AsyncMock()
    fake_client.provider_name = "fake"
    fake_client.chat.side_effect = wrapped_chat

    agent = InvestmentAgent(db_session, session_id="sess_it_test")

    with patch.object(agent_service, "get_llm_client", return_value=fake_client), \
         patch.object(agent_service, "AgentContextService") as mock_ctx:
        mock_ctx.return_value.build_recent_context_block = AsyncMock(return_value="")
        result = await agent.chat("我持仓怎么样,该怎么处理?", history=None)

    # Response envelope
    assert result["fallback"] is False
    assert result["session_id"] == "sess_it_test"
    assert result["decision_card"] is not None
    assert result["stored_card_id"] is not None
    assert result["decision_card"]["target"]["code"] == "006503"
    assert result["decision_card"]["action"]["verb"] == "HOLD"

    # Tool-call log records both the data tool AND the emit call
    logged_names = [c["name"] for c in result["tool_calls"]]
    assert "get_portfolio_summary" in logged_names
    assert EMIT_DECISION_CARD_TOOL_NAME in logged_names

    # The data tool entry carries an evidence_id
    data_tool_entry = next(c for c in result["tool_calls"] if c["name"] == "get_portfolio_summary")
    assert data_tool_entry["evidence_id"].startswith("ev_")

    # evidence_refs on the response include the ev_id from turn 1
    assert data_tool_entry["evidence_id"] in result["evidence_refs"]

    # The decision card was persisted with the same session id
    from app.services.decision_store import DecisionCardStore
    stored = await DecisionCardStore(db_session).list_session("sess_it_test")
    assert len(stored) == 1
    assert stored[0].decision_id == result["decision_card"]["decision_id"]


@pytest.mark.asyncio
async def test_agent_returns_error_when_decision_card_validation_fails(db_session):
    """A malformed emit_decision_card call feeds an error back to the model,
    which then produces a text-only fallback."""

    bad_args = {"type": "BUY_CANDIDATE"}  # missing target + action → invalid
    turn1 = LLMResponse(
        text="",
        tool_calls=[ToolCall(
            id="toolu_1", name=EMIT_DECISION_CARD_TOOL_NAME, arguments=bad_args,
        )],
        stop_reason=StopReason.TOOL_USE,
        model="fake", usage=LLMUsage(),
    )
    turn2 = LLMResponse(
        text="抱歉,决策卡组装失败,直接文本回复。仅供参考,不构成投资建议。",
        stop_reason=StopReason.END_TURN,
        model="fake", usage=LLMUsage(),
    )

    fake_client = AsyncMock()
    fake_client.provider_name = "fake"
    scripted = _ScriptedLLM([turn1, turn2])
    fake_client.chat.side_effect = scripted.chat

    agent = InvestmentAgent(db_session, session_id="sess_bad")

    with patch.object(agent_service, "get_llm_client", return_value=fake_client), \
         patch.object(agent_service, "AgentContextService") as mock_ctx:
        mock_ctx.return_value.build_recent_context_block = AsyncMock(return_value="")
        result = await agent.chat("推荐个基金", history=None)

    # No card should have been persisted
    assert result["decision_card"] is None
    assert result["stored_card_id"] is None
    # But the second turn's text answer flowed through
    assert "文本回复" in result["answer"]

    # The scripted LLM should have seen the validation error content in its
    # second-turn messages
    turn2_messages = scripted.calls[1]["messages"]
    tool_msg = [m for m in turn2_messages if m["role"] == Role.TOOL.value][-1]
    payload = json.loads(tool_msg["tool_results"][0]["content"])
    assert payload["ok"] is False
    assert "validation" in payload["error"].lower()


@pytest.mark.asyncio
async def test_pure_text_answer_flows_without_tool_calls(db_session):
    """When the model answers immediately with text and no tool calls, the
    result is returned as-is with no decision_card and no evidence."""

    turn1 = LLMResponse(
        text="你好,我可以帮你分析持仓。",
        stop_reason=StopReason.END_TURN,
        model="fake", usage=LLMUsage(),
    )
    fake_client = AsyncMock()
    fake_client.provider_name = "fake"
    fake_client.chat.side_effect = _ScriptedLLM([turn1]).chat

    agent = InvestmentAgent(db_session, session_id="sess_greet")

    with patch.object(agent_service, "get_llm_client", return_value=fake_client), \
         patch.object(agent_service, "AgentContextService") as mock_ctx:
        mock_ctx.return_value.build_recent_context_block = AsyncMock(return_value="")
        result = await agent.chat("你好", history=None)

    assert result["decision_card"] is None
    assert result["evidence_refs"] == []
    assert result["tool_calls"] == []
    assert "你好" in result["answer"]
