"""Abstract base classes for SkillBridge strategies."""
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SkillRequest:
    """Standardized request for any skill invocation."""
    skill_name: str
    params: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 60
    cache_ttl_seconds: Optional[int] = None  # None = use strategy default


@dataclass
class SkillResult:
    """Standardized result from skill invocation."""
    success: bool
    data: Any = None
    strategy_used: str = ""
    cached: bool = False
    latency_ms: float = 0.0
    error: Optional[str] = None


class SkillStrategy(ABC):
    """Base class for skill invocation strategies."""

    # Default TTLs per skill type
    DEFAULT_TTLS: dict[str, int] = {
        "market_quote": 30,
        "kline_daily": 300,
        "kline_intraday": 60,
        "index_quote": 30,
        "sector_data": 300,
        "fund_screen": 3600,
        "sector_screen": 3600,
        "etf_screen": 3600,
        "fund_nav": 3600,
        "pattern_recognition": 0,  # No cache - always recompute
        "technical_analysis": 0,
        "signal_generation": 0,
    }

    @abstractmethod
    async def execute(self, request: SkillRequest) -> SkillResult:
        """Execute the skill invocation."""
        ...

    @abstractmethod
    def can_handle(self, skill_name: str) -> bool:
        """Check if this strategy can handle the given skill."""
        ...

    def get_default_ttl(self, skill_name: str) -> Optional[int]:
        """Get default cache TTL for a skill type."""
        return self.DEFAULT_TTLS.get(skill_name)
