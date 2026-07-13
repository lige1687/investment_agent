"""OpenAI-compatible client. Works with DeepSeek, Qwen (DashScope compat mode),
Moonshot / Kimi, Zhipu, and any other endpoint that speaks
POST /v1/chat/completions with the OpenAI schema.

Converts between the unified schemas.Message model and OpenAI's
tool_calls / tool role.
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


# Well-known base URLs. `base_url` in config always wins if set.
KNOWN_BASE_URLS = {
    "openai":   "https://api.openai.com",
    "deepseek": "https://api.deepseek.com",
    "qwen":     "https://dashscope.aliyuncs.com/compatible-mode",
    "moonshot": "https://api.moonshot.cn",
    "kimi":     "https://api.moonshot.cn",
    "zhipu":    "https://open.bigmodel.cn/api/paas/v4",
}


def _msg_to_openai(msg: Message) -> Optional[dict[str, Any]]:
    """Convert one unified Message → one OpenAI messages[] entry.

    OpenAI puts tool results on their own `tool` role (one per result),
    so a TOOL Message may expand into multiple entries — the caller handles
    that path.
    """
    if msg.role == Role.SYSTEM:
        return {"role": "system", "content": msg.content or ""}

    if msg.role == Role.USER:
        return {"role": "user", "content": msg.content or ""}

    if msg.role == Role.ASSISTANT:
        entry: dict[str, Any] = {"role": "assistant"}
        # OpenAI requires content=null when tool_calls present and content empty
        entry["content"] = msg.content if msg.content else None
        if msg.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in msg.tool_calls
            ]
        return entry

    # TOOL: OpenAI wants one entry per result — return None here, handled below
    return None


def _expand_tool_message(msg: Message) -> list[dict[str, Any]]:
    """A single TOOL message with N results expands to N `tool` entries."""
    if msg.role != Role.TOOL:
        return []
    return [
        {
            "role": "tool",
            "tool_call_id": r.tool_call_id,
            "content": r.content,
        }
        for r in msg.tool_results
    ]


def _messages_to_openai(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == Role.TOOL:
            out.extend(_expand_tool_message(m))
        else:
            entry = _msg_to_openai(m)
            if entry is not None:
                out.append(entry)
    return out


def _tools_to_openai(tools: Optional[list[ToolDef]]) -> Optional[list[dict[str, Any]]]:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]


def _parse_stop_reason(raw: Optional[str]) -> StopReason:
    return {
        "stop":          StopReason.END_TURN,
        "tool_calls":    StopReason.TOOL_USE,
        "function_call": StopReason.TOOL_USE,  # legacy
        "length":        StopReason.MAX_TOKENS,
    }.get(raw or "", StopReason.END_TURN)


def _raise_for_status(resp: httpx.Response, provider: str) -> None:
    if resp.status_code < 400:
        return
    try:
        payload = resp.json()
        err_msg = payload.get("error", {}).get("message") or resp.text
    except Exception:
        err_msg = resp.text
    if resp.status_code == 401:
        raise LLMAuthError(err_msg, provider=provider, status=401)
    if resp.status_code == 429:
        raise LLMRateLimitError(err_msg, provider=provider, status=429)
    if 400 <= resp.status_code < 500:
        raise LLMBadRequestError(err_msg, provider=provider, status=resp.status_code)
    raise LLMServerError(err_msg, provider=provider, status=resp.status_code)


class OpenAICompatClient(LLMClient):
    """POST /v1/chat/completions client.

    provider_hint is used only for logging + choosing a default base_url;
    the wire protocol is identical for every OpenAI-compatible service.
    """

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str = "",
        timeout: float = 60.0,
        provider_hint: str = "openai-compat",
    ):
        resolved_base = base_url or KNOWN_BASE_URLS.get(provider_hint.lower(), KNOWN_BASE_URLS["openai"])
        super().__init__(model=model, api_key=api_key, base_url=resolved_base, timeout=timeout)
        self.provider_name = provider_hint
        self._client = httpx.AsyncClient(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        return {
            "content-type": "application/json",
            "authorization": f"Bearer {self.api_key}",
        }

    def _build_payload(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDef]],
        temperature: float,
        max_tokens: int,
        system: Optional[str],
        stream: bool,
        response_format: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        # Prepend a system message if the caller passed one AND no leading system exists
        msgs = list(messages)
        if system and not (msgs and msgs[0].role == Role.SYSTEM):
            msgs.insert(0, Message.system(system))

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": _messages_to_openai(msgs),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        oai_tools = _tools_to_openai(tools)
        if oai_tools:
            payload["tools"] = oai_tools
            payload["tool_choice"] = "auto"
        if response_format:
            payload["response_format"] = response_format
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
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
        url = f"{self.base_url}/v1/chat/completions"
        payload = self._build_payload(
            messages,
            tools,
            temperature,
            max_tokens,
            system,
            stream=False,
            response_format=response_format,
        )
        try:
            resp = await self._client.post(url, headers=self._headers(), json=payload)
        except httpx.HTTPError as e:
            raise LLMServerError(f"HTTP error: {e}", provider=self.provider_name) from e
        _raise_for_status(resp, self.provider_name)

        data = resp.json()
        return self._parse_response(data)

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        choices = data.get("choices") or []
        if not choices:
            return LLMResponse(text="", model=data.get("model", self.model), raw=data)

        choice = choices[0]
        msg = choice.get("message", {}) or {}
        text = msg.get("content") or ""

        tool_calls: list[ToolCall] = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {}) or {}
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except json.JSONDecodeError:
                logger.warning("openai-compat: bad tool_call arguments JSON: %r", raw_args)
                args = {}
            tool_calls.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=args))

        usage_raw = data.get("usage", {}) or {}
        usage = LLMUsage(
            input_tokens=usage_raw.get("prompt_tokens", 0),
            output_tokens=usage_raw.get("completion_tokens", 0),
        )
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason=_parse_stop_reason(choice.get("finish_reason")),
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
        url = f"{self.base_url}/v1/chat/completions"
        payload = self._build_payload(messages, tools, temperature, max_tokens, system, stream=True)

        # OpenAI streams tool_calls incrementally by index; we accumulate then
        # emit a single ToolCall chunk at [DONE] time.
        pending: dict[int, dict[str, Any]] = {}
        finish_reason: Optional[str] = None
        final_usage: Optional[dict[str, Any]] = None

        async with self._client.stream("POST", url, headers=self._headers(), json=payload) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                fake = httpx.Response(status_code=resp.status_code, content=body, request=resp.request)
                _raise_for_status(fake, self.provider_name)

            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                if not data_str:
                    continue
                try:
                    evt = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                if "usage" in evt and evt.get("usage"):
                    final_usage = evt["usage"]

                choices = evt.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get("delta") or {}

                if isinstance(delta.get("content"), str) and delta["content"]:
                    yield LLMChunk(text_delta=delta["content"])

                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    slot = pending.setdefault(idx, {"id": "", "name": "", "args_buf": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["args_buf"] += fn["arguments"]

                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]

        # Flush accumulated tool_calls
        for slot in pending.values():
            try:
                args = json.loads(slot["args_buf"]) if slot["args_buf"] else {}
            except json.JSONDecodeError:
                args = {}
            yield LLMChunk(tool_call_delta=ToolCall(
                id=slot["id"], name=slot["name"], arguments=args,
            ))

        usage = None
        if final_usage:
            usage = LLMUsage(
                input_tokens=final_usage.get("prompt_tokens", 0),
                output_tokens=final_usage.get("completion_tokens", 0),
            )
        yield LLMChunk(stop_reason=_parse_stop_reason(finish_reason), usage=usage)

    async def aclose(self) -> None:
        await self._client.aclose()
