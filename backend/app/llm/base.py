"""LLMClient interface — every provider implements this.

Agent code only imports from here, never from a specific provider module.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Optional

from app.llm.schemas import LLMChunk, LLMResponse, Message, ToolDef


class LLMError(Exception):
    """Base for LLM failures. Providers raise subclasses."""

    def __init__(self, message: str, provider: str = "", status: Optional[int] = None):
        super().__init__(message)
        self.provider = provider
        self.status = status


class LLMAuthError(LLMError):
    """Missing / invalid API key, 401."""


class LLMRateLimitError(LLMError):
    """Rate limited by the provider, 429."""


class LLMBadRequestError(LLMError):
    """Malformed request, 400."""


class LLMServerError(LLMError):
    """5xx from the provider."""


class LLMClient(ABC):
    """Interface every provider must implement.

    The agent layer never constructs these directly — it goes through
    `registry.get_llm_client(role)` so provider swaps are config-driven.
    """

    provider_name: str = "base"

    def __init__(self, *, model: str, api_key: str, base_url: str = "", timeout: float = 60.0):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @abstractmethod
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
        """One non-streaming completion."""
        ...

    @abstractmethod
    def stream(
        self,
        messages: list[Message],
        *,
        tools: Optional[list[ToolDef]] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        system: Optional[str] = None,
    ) -> AsyncIterator[LLMChunk]:
        """Async iterator over streaming deltas."""
        ...

    async def aclose(self) -> None:
        """Close underlying HTTP connections. Override in subclass if needed."""
        return None
