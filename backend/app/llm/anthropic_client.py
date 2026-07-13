"""Anthropic Messages API client. Uses httpx directly (no SDK).

Converts between the unified schemas.Message model and Anthropic's native
tool_use / tool_result content blocks.
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Optional

import httpx

from app.llm.base import (
    LLMAuthError,
    LLMBadRequestError,
    LLMClient,
    LLMError,
    LLMRateLimitError,
    LLMServerError,
)
from app.llm.schemas import (
    LLMChunk,
    LLMResponse,
    LLMUsage,
    Message,
    Role,
    StopReason,
    ToolCall,
    ToolDef,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.anthropic.com"
API_VERSION = "2023-06-01"


def _msg_to_anthropic(msg: Message) -> Optional[dict[str, Any]]:
    """Convert one unified Message → Anthropic messages[] entry.

    Anthropic collapses tool_calls and tool_results into content blocks on
    assistant/user messages. System is passed as top-level `system`, not in
    messages[].
    """
    if msg.role == Role.SYSTEM:
        return None  # Handled at request level

    if msg.role == Role.ASSISTANT:
        blocks: list[dict[str, Any]] = []
        if msg.content:
            blocks.append({"type": "text", "text": msg.content})
        for tc in msg.tool_calls:
            blocks.append({
                "type": "tool_use",
                "id": tc.id,
                "name": tc.name,
                "input": tc.arguments,
            })
        return {"role": "assistant", "content": blocks}

    if msg.role == Role.TOOL:
        # Anthropic wraps tool results inside a *user* message
        blocks = [
            {
                "type": "tool_result",
                "tool_use_id": r.tool_call_id,
                "content": r.content,
                **({"is_error": True} if r.is_error else {}),
            }
            for r in msg.tool_results
        ]
        return {"role": "user", "content": blocks}

    # Plain user
    return {"role": "user", "content": msg.content or ""}


def _tools_to_anthropic(tools: Optional[list[ToolDef]]) -> Optional[list[dict[str, Any]]]:
    if not tools:
        return None
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]


def _parse_stop_reason(raw: Optional[str]) -> StopReason:
    return {
        "end_turn": StopReason.END_TURN,
        "tool_use": StopReason.TOOL_USE,
        "max_tokens": StopReason.MAX_TOKENS,
        "stop_sequence": StopReason.STOP_SEQUENCE,
    }.get(raw or "", StopReason.END_TURN)


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code < 400:
        return
    try:
        payload = resp.json()
        err_msg = payload.get("error", {}).get("message") or resp.text
    except Exception:
        err_msg = resp.text
    if resp.status_code == 401:
        raise LLMAuthError(err_msg, provider="anthropic", status=401)
    if resp.status_code == 429:
        raise LLMRateLimitError(err_msg, provider="anthropic", status=429)
    if 400 <= resp.status_code < 500:
        raise LLMBadRequestError(err_msg, provider="anthropic", status=resp.status_code)
    raise LLMServerError(err_msg, provider="anthropic", status=resp.status_code)


class AnthropicClient(LLMClient):
    """Client for api.anthropic.com/v1/messages."""

    provider_name = "anthropic"

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 60.0,
        auth_token: str = "",
    ):
        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url or DEFAULT_BASE_URL,
            timeout=timeout,
        )
        # Anthropic supports two auth headers: `x-api-key` (retail) and
        # `Authorization: Bearer <token>` (via Bedrock / proxies). Accept both.
        self._auth_token = auth_token
        self._client = httpx.AsyncClient(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            "anthropic-version": API_VERSION,
        }
        if self._auth_token:
            headers["authorization"] = f"Bearer {self._auth_token}"
        elif self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def _build_payload(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDef]],
        temperature: float,
        max_tokens: int,
        system: Optional[str],
        stream: bool,
    ) -> dict[str, Any]:
        # Extract system from either the parameter or a leading system message
        system_text = system
        for m in messages:
            if m.role == Role.SYSTEM and m.content:
                system_text = (system_text + "\n\n" + m.content) if system_text else m.content
                break

        anthropic_msgs = [x for x in (_msg_to_anthropic(m) for m in messages) if x is not None]

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": anthropic_msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_text:
            payload["system"] = system_text
        anth_tools = _tools_to_anthropic(tools)
        if anth_tools:
            payload["tools"] = anth_tools
        if stream:
            payload["stream"] = True
        return payload

    async def chat(
        self,
        messages: list[Message],
        *,
        tools: Optional[list[ToolDef]] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        system: Optional[str] = None,
        response_format: Optional[dict[str, Any]] = None,
    ) -> LLMResponse:
        payload = self._build_payload(messages, tools, temperature, max_tokens, system, stream=False)
        url = f"{self.base_url}/v1/messages"
        try:
            resp = await self._client.post(url, headers=self._headers(), json=payload)
        except httpx.HTTPError as e:
            raise LLMServerError(f"HTTP error: {e}", provider="anthropic") from e
        _raise_for_status(resp)

        data = resp.json()
        return self._parse_response(data)

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in data.get("content", []) or []:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.get("id", ""),
                        name=block.get("name", ""),
                        arguments=block.get("input", {}) or {},
                    )
                )
        usage_raw = data.get("usage", {}) or {}
        usage = LLMUsage(
            input_tokens=usage_raw.get("input_tokens", 0),
            output_tokens=usage_raw.get("output_tokens", 0),
            cache_read_tokens=usage_raw.get("cache_read_input_tokens", 0),
            cache_write_tokens=usage_raw.get("cache_creation_input_tokens", 0),
        )
        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=_parse_stop_reason(data.get("stop_reason")),
            model=data.get("model", self.model),
            usage=usage,
            raw=data,
        )

    async def stream(
        self,
        messages: list[Message],
        *,
        tools: Optional[list[ToolDef]] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        system: Optional[str] = None,
    ) -> AsyncIterator[LLMChunk]:
        payload = self._build_payload(messages, tools, temperature, max_tokens, system, stream=True)
        url = f"{self.base_url}/v1/messages"

        # Track in-flight tool_use blocks by index; finalize when input_json is complete.
        # Anthropic's SSE emits input_json_delta chunks that need to be concatenated
        # and parsed as JSON when content_block_stop fires.
        pending_tools: dict[int, dict[str, Any]] = {}

        async with self._client.stream("POST", url, headers=self._headers(), json=payload) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                fake = httpx.Response(status_code=resp.status_code, content=body, request=resp.request)
                _raise_for_status(fake)

            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str or data_str == "[DONE]":
                    continue
                try:
                    evt = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                etype = evt.get("type")
                if etype == "content_block_start":
                    block = evt.get("content_block", {})
                    if block.get("type") == "tool_use":
                        pending_tools[evt.get("index", 0)] = {
                            "id": block.get("id", ""),
                            "name": block.get("name", ""),
                            "json_buf": "",
                        }
                elif etype == "content_block_delta":
                    delta = evt.get("delta", {})
                    dtype = delta.get("type")
                    if dtype == "text_delta":
                        yield LLMChunk(text_delta=delta.get("text", ""))
                    elif dtype == "input_json_delta":
                        idx = evt.get("index", 0)
                        if idx in pending_tools:
                            pending_tools[idx]["json_buf"] += delta.get("partial_json", "")
                elif etype == "content_block_stop":
                    idx = evt.get("index", 0)
                    if idx in pending_tools:
                        buf = pending_tools[idx]
                        try:
                            args = json.loads(buf["json_buf"]) if buf["json_buf"] else {}
                        except json.JSONDecodeError:
                            args = {}
                        yield LLMChunk(tool_call_delta=ToolCall(
                            id=buf["id"], name=buf["name"], arguments=args
                        ))
                        del pending_tools[idx]
                elif etype == "message_delta":
                    delta = evt.get("delta", {})
                    stop_reason = _parse_stop_reason(delta.get("stop_reason"))
                    usage_raw = evt.get("usage", {}) or {}
                    yield LLMChunk(
                        stop_reason=stop_reason,
                        usage=LLMUsage(
                            input_tokens=usage_raw.get("input_tokens", 0),
                            output_tokens=usage_raw.get("output_tokens", 0),
                        ) if usage_raw else None,
                    )

    async def aclose(self) -> None:
        await self._client.aclose()
