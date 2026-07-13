"""LLM layer conversion tests.

Focus: verifying the two format converters (Anthropic ↔ unified,
OpenAI ↔ unified) round-trip without losing information. No network I/O
— we only exercise the payload-building and response-parsing paths.
"""
import json

import pytest

from app.llm.anthropic_client import (
    AnthropicClient,
    _msg_to_anthropic,
    _tools_to_anthropic,
    _parse_stop_reason as _anthropic_parse_stop,
)
from app.llm.openai_compat import (
    OpenAICompatClient,
    _messages_to_openai,
    _tools_to_openai,
    _parse_stop_reason as _openai_parse_stop,
)
from app.llm.schemas import (
    Message,
    Role,
    StopReason,
    ToolCall,
    ToolDef,
    ToolResult,
)


# ── Shared fixtures ──

def _sample_tool() -> ToolDef:
    return ToolDef(
        name="get_portfolio_summary",
        description="Fetch user portfolio",
        input_schema={
            "type": "object",
            "properties": {"detail": {"type": "boolean"}},
            "required": [],
        },
    )


def _sample_tool_call() -> ToolCall:
    return ToolCall(
        id="toolu_01ABC",
        name="get_portfolio_summary",
        arguments={"detail": True},
    )


# ── Message → Anthropic ──

def test_anthropic_system_message_not_in_body():
    """System messages must not be emitted as messages[] entries — Anthropic
    takes them at the top level."""
    entry = _msg_to_anthropic(Message.system("You are helpful"))
    assert entry is None


def test_anthropic_user_message_plain_text():
    entry = _msg_to_anthropic(Message.user("Hello"))
    assert entry == {"role": "user", "content": "Hello"}


def test_anthropic_assistant_with_text_and_tool_calls():
    msg = Message.assistant(text="Let me check.", tool_calls=[_sample_tool_call()])
    entry = _msg_to_anthropic(msg)
    assert entry["role"] == "assistant"
    blocks = entry["content"]
    assert blocks[0] == {"type": "text", "text": "Let me check."}
    assert blocks[1] == {
        "type": "tool_use",
        "id": "toolu_01ABC",
        "name": "get_portfolio_summary",
        "input": {"detail": True},
    }


def test_anthropic_tool_message_wraps_in_user_role():
    """Anthropic requires tool_result blocks to arrive under a user role."""
    msg = Message.tool([
        ToolResult(tool_call_id="toolu_01ABC", content='{"total": 100}'),
    ])
    entry = _msg_to_anthropic(msg)
    assert entry["role"] == "user"
    assert entry["content"] == [{
        "type": "tool_result",
        "tool_use_id": "toolu_01ABC",
        "content": '{"total": 100}',
    }]


def test_anthropic_tool_result_error_flag_survives():
    msg = Message.tool([
        ToolResult(tool_call_id="toolu_X", content="boom", is_error=True),
    ])
    entry = _msg_to_anthropic(msg)
    assert entry["content"][0]["is_error"] is True


def test_anthropic_tools_conversion():
    out = _tools_to_anthropic([_sample_tool()])
    assert out == [{
        "name": "get_portfolio_summary",
        "description": "Fetch user portfolio",
        "input_schema": _sample_tool().input_schema,
    }]


def test_anthropic_stop_reason_mapping():
    assert _anthropic_parse_stop("tool_use") == StopReason.TOOL_USE
    assert _anthropic_parse_stop("end_turn") == StopReason.END_TURN
    assert _anthropic_parse_stop("max_tokens") == StopReason.MAX_TOKENS
    assert _anthropic_parse_stop(None) == StopReason.END_TURN
    assert _anthropic_parse_stop("mystery") == StopReason.END_TURN


# ── Anthropic response → unified ──

def test_anthropic_response_parses_text_and_tool_use():
    client = AnthropicClient(model="claude-sonnet-4", api_key="sk-fake")
    raw = {
        "id": "msg_01",
        "model": "claude-sonnet-4",
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 42, "output_tokens": 7},
        "content": [
            {"type": "text", "text": "I will check your portfolio."},
            {
                "type": "tool_use",
                "id": "toolu_XYZ",
                "name": "get_portfolio_summary",
                "input": {"detail": True},
            },
        ],
    }
    resp = client._parse_response(raw)
    assert resp.text == "I will check your portfolio."
    assert resp.stop_reason == StopReason.TOOL_USE
    assert resp.has_tool_calls
    assert len(resp.tool_calls) == 1
    tc = resp.tool_calls[0]
    assert tc.id == "toolu_XYZ"
    assert tc.name == "get_portfolio_summary"
    assert tc.arguments == {"detail": True}
    assert resp.usage.input_tokens == 42
    assert resp.usage.output_tokens == 7


def test_anthropic_response_pure_text():
    client = AnthropicClient(model="claude-sonnet-4", api_key="sk-fake")
    raw = {
        "id": "msg_02",
        "model": "claude-sonnet-4",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 12, "output_tokens": 34},
        "content": [{"type": "text", "text": "Hello there."}],
    }
    resp = client._parse_response(raw)
    assert resp.text == "Hello there."
    assert not resp.has_tool_calls
    assert resp.stop_reason == StopReason.END_TURN


# ── OpenAI-compat: messages ──

def test_openai_system_stays_in_messages_array():
    """Unlike Anthropic, OpenAI keeps system in messages[]."""
    out = _messages_to_openai([Message.system("SYS"), Message.user("hi")])
    assert out[0] == {"role": "system", "content": "SYS"}
    assert out[1] == {"role": "user", "content": "hi"}


def test_openai_assistant_with_tool_calls_serializes_args_as_json_string():
    """OpenAI requires function.arguments to be a JSON string, not an object."""
    msg = Message.assistant(text="", tool_calls=[_sample_tool_call()])
    out = _messages_to_openai([msg])
    assert out[0]["role"] == "assistant"
    assert out[0]["content"] is None  # empty text → null
    tc = out[0]["tool_calls"][0]
    assert tc["id"] == "toolu_01ABC"
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "get_portfolio_summary"
    assert json.loads(tc["function"]["arguments"]) == {"detail": True}


def test_openai_tool_message_expands_to_multiple_tool_entries():
    """A single unified TOOL message with N results = N `tool` entries in OpenAI."""
    msg = Message.tool([
        ToolResult(tool_call_id="c1", content='{"a": 1}'),
        ToolResult(tool_call_id="c2", content='{"b": 2}'),
    ])
    out = _messages_to_openai([msg])
    assert len(out) == 2
    assert out[0] == {"role": "tool", "tool_call_id": "c1", "content": '{"a": 1}'}
    assert out[1] == {"role": "tool", "tool_call_id": "c2", "content": '{"b": 2}'}


def test_openai_tools_conversion_wraps_in_function_type():
    out = _tools_to_openai([_sample_tool()])
    assert out == [{
        "type": "function",
        "function": {
            "name": "get_portfolio_summary",
            "description": "Fetch user portfolio",
            "parameters": _sample_tool().input_schema,
        },
    }]


def test_openai_stop_reason_mapping():
    assert _openai_parse_stop("tool_calls") == StopReason.TOOL_USE
    assert _openai_parse_stop("function_call") == StopReason.TOOL_USE  # legacy
    assert _openai_parse_stop("stop") == StopReason.END_TURN
    assert _openai_parse_stop("length") == StopReason.MAX_TOKENS
    assert _openai_parse_stop(None) == StopReason.END_TURN


# ── OpenAI response → unified ──

def test_openai_response_parses_text_and_tool_calls():
    client = OpenAICompatClient(
        model="deepseek-chat", api_key="sk-fake", provider_hint="deepseek",
    )
    raw = {
        "id": "chatcmpl-1",
        "model": "deepseek-chat",
        "usage": {"prompt_tokens": 50, "completion_tokens": 8},
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": "checking",
                "tool_calls": [{
                    "id": "call_abc",
                    "type": "function",
                    "function": {
                        "name": "get_portfolio_summary",
                        "arguments": '{"detail": true}',
                    },
                }],
            },
        }],
    }
    resp = client._parse_response(raw)
    assert resp.text == "checking"
    assert resp.stop_reason == StopReason.TOOL_USE
    assert resp.has_tool_calls
    tc = resp.tool_calls[0]
    assert tc.id == "call_abc"
    assert tc.name == "get_portfolio_summary"
    assert tc.arguments == {"detail": True}
    assert resp.usage.input_tokens == 50
    assert resp.usage.output_tokens == 8


def test_openai_response_survives_bad_tool_arguments_json():
    """If the model returns malformed arguments JSON, we must not crash —
    fall back to empty dict and let the caller decide."""
    client = OpenAICompatClient(
        model="deepseek-chat", api_key="sk-fake", provider_hint="deepseek",
    )
    raw = {
        "model": "deepseek-chat",
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_bad",
                    "type": "function",
                    "function": {"name": "foo", "arguments": "not-json{"},
                }],
            },
        }],
    }
    resp = client._parse_response(raw)
    assert resp.has_tool_calls
    assert resp.tool_calls[0].arguments == {}


def test_openai_response_no_choices_returns_empty():
    client = OpenAICompatClient(
        model="deepseek-chat", api_key="sk-fake", provider_hint="deepseek",
    )
    resp = client._parse_response({"choices": [], "model": "deepseek-chat"})
    assert resp.text == ""
    assert not resp.has_tool_calls


# ── Round-trip: unified → provider format → back to unified ──

def test_anthropic_tool_call_round_trip():
    """A ToolCall serialized to Anthropic wire format and parsed back
    must equal the original."""
    original = _sample_tool_call()
    # Serialize as assistant tool_use block
    entry = _msg_to_anthropic(Message.assistant(text="", tool_calls=[original]))
    block = entry["content"][0]

    # Parse back as if it came from the API
    client = AnthropicClient(model="claude-sonnet-4", api_key="sk-fake")
    resp = client._parse_response({
        "content": [block],
        "model": "claude-sonnet-4",
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 0, "output_tokens": 0},
    })
    assert resp.tool_calls == [original]


def test_openai_tool_call_round_trip():
    original = _sample_tool_call()
    entry = _messages_to_openai([Message.assistant(text="", tool_calls=[original])])[0]
    tc_wire = entry["tool_calls"][0]

    client = OpenAICompatClient(
        model="deepseek-chat", api_key="sk-fake", provider_hint="deepseek",
    )
    resp = client._parse_response({
        "model": "deepseek-chat",
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {"role": "assistant", "content": None, "tool_calls": [tc_wire]},
        }],
    })
    assert resp.tool_calls == [original]


# ── Registry ──

def test_registry_resolves_default_role():
    from app.llm.registry import _resolve_config
    cfg = _resolve_config(None)
    # Provider name is normalized to lowercase
    assert cfg.provider == cfg.provider.lower()


def test_registry_unknown_role_falls_back_to_default():
    from app.llm.registry import _resolve_config
    default = _resolve_config(None)
    unknown = _resolve_config("does_not_exist")
    assert unknown == default


# ── Payload build (integration between messages + tools) ──

def test_anthropic_payload_moves_system_out_of_messages():
    """A system message inside the list must end up in the top-level
    `system` field, not in messages[]."""
    client = AnthropicClient(model="claude-sonnet-4", api_key="sk-fake")
    msgs = [Message.system("Be terse"), Message.user("Hi")]
    payload = client._build_payload(
        msgs, tools=None, temperature=0.2, max_tokens=100, system=None, stream=False,
    )
    assert payload["system"] == "Be terse"
    assert len(payload["messages"]) == 1
    assert payload["messages"][0] == {"role": "user", "content": "Hi"}


def test_anthropic_payload_merges_param_and_inline_system():
    """Both `system` param and a system Message in the list should be combined."""
    client = AnthropicClient(model="claude-sonnet-4", api_key="sk-fake")
    msgs = [Message.system("Inline"), Message.user("Hi")]
    payload = client._build_payload(
        msgs, tools=None, temperature=0.2, max_tokens=100, system="Param", stream=False,
    )
    assert "Param" in payload["system"]
    assert "Inline" in payload["system"]


def test_openai_payload_injects_system_when_missing():
    client = OpenAICompatClient(
        model="deepseek-chat", api_key="sk-fake", provider_hint="deepseek",
    )
    msgs = [Message.user("Hi")]
    payload = client._build_payload(
        msgs, tools=None, temperature=0.2, max_tokens=100, system="You are terse", stream=False,
    )
    assert payload["messages"][0] == {"role": "system", "content": "You are terse"}


def test_openai_payload_preserves_leading_system_and_ignores_param():
    """If caller already put a system message in the list, don't double it."""
    client = OpenAICompatClient(
        model="deepseek-chat", api_key="sk-fake", provider_hint="deepseek",
    )
    msgs = [Message.system("Inline"), Message.user("Hi")]
    payload = client._build_payload(
        msgs, tools=None, temperature=0.2, max_tokens=100, system="Param", stream=False,
    )
    # Only one system entry, and it's the inline one
    system_entries = [m for m in payload["messages"] if m["role"] == "system"]
    assert len(system_entries) == 1
    assert system_entries[0]["content"] == "Inline"


def test_openai_tool_choice_auto_when_tools_present():
    client = OpenAICompatClient(
        model="deepseek-chat", api_key="sk-fake", provider_hint="deepseek",
    )
    payload = client._build_payload(
        [Message.user("Hi")], tools=[_sample_tool()],
        temperature=0.2, max_tokens=100, system=None, stream=False,
    )
    assert payload["tool_choice"] == "auto"
    assert len(payload["tools"]) == 1
