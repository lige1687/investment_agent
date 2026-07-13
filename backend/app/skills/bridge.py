"""SkillBridge orchestrator - routes requests to the optimal strategy."""
import logging
import time
from typing import Optional
from app.skills.base import SkillRequest, SkillResult, SkillStrategy
from app.skills.cache import SkillCache

logger = logging.getLogger(__name__)


class SkillBridge:
    """Master orchestrator for skill invocation.

    Routes each request to the best available strategy:
      1. Direct API  (fast + free, for real-time market data)
      2. Claude API  (medium cost, for analysis)
      3. Claude CLI  (highest cost, for proprietary skills like fund screening)

    Includes TTL caching to minimize redundant expensive calls.
    """

    def __init__(self):
        self._strategies: list[SkillStrategy] = []
        self._cache = SkillCache()

    def register(self, strategy: SkillStrategy):
        """Register a strategy. Strategies are tried in registration order."""
        self._strategies.append(strategy)
        logger.info(f"SkillBridge: registered {strategy.__class__.__name__}")

    async def invoke(self, request: SkillRequest) -> SkillResult:
        """Invoke a skill, trying strategies in priority order.

        Flow:
        1. Check cache → return if hit
        2. Find first strategy that can_handle() → execute
        3. Cache successful result
        4. Return result
        """
        # 1. Check cache
        if request.cache_ttl_seconds is not None:
            cached = await self._cache.get(request)
            if cached:
                logger.debug(f"Cache hit: {request.skill_name}")
                return cached

        # 2. Find and execute
        for strategy in self._strategies:
            if not strategy.can_handle(request.skill_name):
                continue

            logger.info(f"SkillBridge: {request.skill_name} → {strategy.__class__.__name__}")
            start = time.monotonic()
            try:
                result = await strategy.execute(request)
            except Exception as e:
                logger.error(f"Strategy {strategy.__class__.__name__} failed: {e}")
                continue  # Try next strategy

            result.latency_ms = (time.monotonic() - start) * 1000

            if result.success:
                # 3. Cache
                ttl = request.cache_ttl_seconds
                if ttl is None:
                    ttl = strategy.get_default_ttl(request.skill_name) or 0
                if ttl > 0:
                    await self._cache.set(request, result, ttl)
                return result

            logger.warning(f"Strategy {strategy.__class__.__name__} returned failure: {result.error}")

        # No strategy succeeded
        return SkillResult(
            success=False,
            error=f"No strategy available for '{request.skill_name}'",
        )

    async def invoke_simple(
        self,
        skill_name: str,
        params: Optional[dict] = None,
        cache_ttl: Optional[int] = None,
    ) -> SkillResult:
        """Convenience method for simple invocations."""
        return await self.invoke(SkillRequest(
            skill_name=skill_name,
            params=params or {},
            cache_ttl_seconds=cache_ttl,
        ))

    def cache_size(self) -> int:
        return self._cache.size()


# Global singleton
bridge = SkillBridge()
