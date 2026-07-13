"""Verify InvestmentAgent injects `recent_context` into the LLM system prompt.

Under the old subprocess-CLI architecture this was tested against
`_build_cli_prompt`. In the new tool-use-loop architecture, recent context is
appended to SYSTEM_PROMPT and passed via `LLMClient.chat(..., system=...)`,
so this test now stubs the LLM client and inspects the `system` argument.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.llm.schemas import LLMResponse, StopReason
from app.services import agent_service
from app.services.agent_service import InvestmentAgent, SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_chat_appends_recent_context_to_system_prompt():
    fake_ctx_block = (
        "## 最近证据快照\n"
        "- 半导体/芯片:跟踪代码 931743,数据代码 H30184.CSI,主力数据缺失"
    )

    fake_client = AsyncMock()
    fake_client.provider_name = "fake"
    # Model finishes without any tool calls — one round through the loop
    fake_client.chat.return_value = LLMResponse(
        text="ok", stop_reason=StopReason.END_TURN, model="fake",
    )

    fake_db = object()  # never actually queried — AgentContextService is patched
    agent = InvestmentAgent(db=fake_db)  # type: ignore[arg-type]

    with patch.object(agent_service, "get_llm_client", return_value=fake_client), \
         patch.object(agent_service, "AgentContextService") as mock_svc_cls:
        mock_svc_cls.return_value.build_recent_context_block = AsyncMock(
            return_value=fake_ctx_block
        )
        result = await agent.chat("为什么半导体有机会?", history=None)

    fake_client.chat.assert_awaited_once()
    system_arg = fake_client.chat.await_args.kwargs["system"]

    # Base persona and rules survive
    first_line_of_prompt = SYSTEM_PROMPT.strip().split("\n", 1)[0]
    assert first_line_of_prompt in system_arg
    # Recent context is preserved verbatim
    assert "最近证据快照" in system_arg
    assert "跟踪代码 931743" in system_arg
    assert "数据代码 H30184.CSI" in system_arg
    assert "主力数据缺失" in system_arg

    assert result["fallback"] is False
    assert result["answer"] == "ok"


@pytest.mark.asyncio
async def test_chat_without_recent_context_uses_base_system_prompt_only():
    fake_client = AsyncMock()
    fake_client.provider_name = "fake"
    fake_client.chat.return_value = LLMResponse(
        text="ok", stop_reason=StopReason.END_TURN, model="fake",
    )

    fake_db = object()
    agent = InvestmentAgent(db=fake_db)  # type: ignore[arg-type]

    with patch.object(agent_service, "get_llm_client", return_value=fake_client), \
         patch.object(agent_service, "AgentContextService") as mock_svc_cls:
        mock_svc_cls.return_value.build_recent_context_block = AsyncMock(return_value="")
        await agent.chat("我持仓怎么样?", history=None)

    system_arg = fake_client.chat.await_args.kwargs["system"]
    # No evidence block appended
    assert "最近证据快照" not in system_arg
    # Base prompt intact
    assert SYSTEM_PROMPT.strip() in system_arg
