"""Role → LLMClient resolver.

Agents call `get_llm_client("advisor")` and don't know or care whether the
underlying provider is Anthropic, DeepSeek, or Qwen. Reads config from
`app.config.settings` and caches one client per (provider, model, base_url, key)
tuple so we don't spawn a new httpx.AsyncClient per request.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Optional

from app.config import settings
from app.llm.anthropic_client import AnthropicClient
from app.llm.base import LLMClient, LLMError
from app.llm.openai_compat import OpenAICompatClient

logger = logging.getLogger(__name__)


TRADING_ROOM_ROLES = {
    "market_regime", "theme_fund", "portfolio_risk", "buy",
    "sell_protection", "skeptic", "recorder", "chair",
}
VALID_ROLES = {"intent_router", "advisor", "scout", "guardian"} | TRADING_ROOM_ROLES
DEPRECATED_DEEPSEEK_MODELS = {"deepseek-chat", "deepseek-reasoner"}

# Providers that route to OpenAICompatClient. Anything else falls back to
# the default llm_provider setting.
OPENAI_COMPAT_PROVIDERS = {"openai", "deepseek", "qwen", "moonshot", "kimi", "zhipu"}


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    api_key: str
    base_url: str
    timeout: float


def _resolve_config(role: Optional[str]) -> LLMConfig:
    """Resolve the effective config for a role, layering role → default."""
    def pick(role_val: str, default_val: str) -> str:
        return role_val or default_val

    default_provider = settings.llm_provider
    default_model = settings.llm_model
    default_key = settings.llm_api_key
    default_base = settings.llm_base_url

    if role in TRADING_ROOM_ROLES:
        provider = settings.trading_room_llm_provider
        model = settings.trading_room_llm_model
        api_key = settings.trading_room_llm_api_key or default_key
        base_url = settings.trading_room_llm_base_url or default_base
    elif role and role in VALID_ROLES:
        role_prefix = f"llm_{role}_"
        provider = pick(getattr(settings, role_prefix + "provider"), default_provider)
        model = pick(getattr(settings, role_prefix + "model"), default_model)
        api_key = pick(getattr(settings, role_prefix + "api_key"), default_key)
        base_url = pick(getattr(settings, role_prefix + "base_url"), default_base)
    else:
        provider = default_provider
        model = default_model
        api_key = default_key
        base_url = default_base

    # Anthropic legacy fields — populate empty defaults from the older config keys
    if provider.lower() == "anthropic":
        if not api_key:
            api_key = settings.anthropic_api_key
        if not model:
            model = settings.anthropic_model
        if not base_url:
            base_url = settings.anthropic_base_url

    if provider.lower() == "deepseek" and model in DEPRECATED_DEEPSEEK_MODELS:
        raise LLMError(
            f"Deprecated DeepSeek model configured for role {role!r}", provider="deepseek"
        )

    return LLMConfig(
        provider=provider.lower(),
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=settings.llm_timeout_seconds,
    )


class LLMRegistry:
    """Process-wide cache of LLMClient instances, keyed by resolved config."""

    def __init__(self) -> None:
        self._clients: dict[tuple, LLMClient] = {}
        self._lock = threading.Lock()

    def _key(self, cfg: LLMConfig) -> tuple:
        return (cfg.provider, cfg.model, cfg.base_url, cfg.api_key)

    def get(self, role: Optional[str] = None) -> LLMClient:
        cfg = _resolve_config(role)
        key = self._key(cfg)
        with self._lock:
            client = self._clients.get(key)
            if client is not None:
                return client
            client = self._build(cfg)
            self._clients[key] = client
            logger.info(
                "LLMRegistry: created %s client for role=%s model=%s",
                cfg.provider, role or "default", cfg.model,
            )
            return client

    def _build(self, cfg: LLMConfig) -> LLMClient:
        p = cfg.provider
        if p == "anthropic":
            return AnthropicClient(
                model=cfg.model,
                api_key=cfg.api_key,
                base_url=cfg.base_url,
                timeout=cfg.timeout,
                auth_token=settings.anthropic_auth_token,
            )
        if p in OPENAI_COMPAT_PROVIDERS:
            return OpenAICompatClient(
                model=cfg.model,
                api_key=cfg.api_key,
                base_url=cfg.base_url,
                timeout=cfg.timeout,
                provider_hint=p,
            )
        raise LLMError(f"Unknown LLM provider: {cfg.provider!r}", provider=cfg.provider)

    async def aclose(self) -> None:
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for c in clients:
            try:
                await c.aclose()
            except Exception as e:
                logger.warning("LLMRegistry: aclose failed for %s: %s", c.provider_name, e)


# Module-level singleton — agents just call get_llm_client("advisor")
_registry = LLMRegistry()


def llm_credentials_configured(role: Optional[str] = None) -> bool:
    """Return True when the resolved config for `role` has a non-empty api_key."""
    return bool(_resolve_config(role).api_key.strip())


def get_llm_client(role: Optional[str] = None) -> LLMClient:
    """Return the LLMClient configured for `role` (or default if role is None).

    Valid roles: intent_router, advisor, scout, guardian. Unknown roles
    silently fall back to the default provider — useful for one-off scripts.
    """
    return _registry.get(role)
