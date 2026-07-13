"""Provider-agnostic LLM layer.

Agents only depend on `LLMClient` + `schemas`, never on a specific provider.
Concrete providers live in `anthropic_client.py`, `openai_compat.py`, etc.
"""
from app.llm.schemas import (
    Role,
    Message,
    ToolDef,
    ToolCall,
    ToolResult,
    StopReason,
    LLMResponse,
    LLMChunk,
    LLMUsage,
)
from app.llm.base import LLMClient, LLMError, LLMRateLimitError, LLMAuthError
from app.llm.registry import get_llm_client, LLMRegistry

__all__ = [
    "Role",
    "Message",
    "ToolDef",
    "ToolCall",
    "ToolResult",
    "StopReason",
    "LLMResponse",
    "LLMChunk",
    "LLMUsage",
    "LLMClient",
    "LLMError",
    "LLMRateLimitError",
    "LLMAuthError",
    "get_llm_client",
    "LLMRegistry",
]
