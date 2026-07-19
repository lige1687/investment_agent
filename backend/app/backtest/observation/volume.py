"""VolumeThresholdProvider: externalized volume breakout threshold via skill.

The provider determines the volume threshold multiplier for buy/sell triggers.
Currently hardcoded at 1.8x MA20 volume; this module externalizes via the
``batch-trading-volume-threshold`` skill for per-fund, per-date customization.

If the skill is unavailable, falls back to config defaults (buy_volume_ratio,
breakdown_volume_ratio).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.backtest.models import BacktestConfig
from app.backtest.observation.cache import ObservationCache

logger = logging.getLogger(__name__)

_VOLUME_SKILL_NAME = "batch-trading-volume-threshold"


class VolumeThresholdProvider:
    """Provides volume threshold multipliers via skill or config defaults."""

    def __init__(
        self,
        skill_bridge: Any | None = None,
        cache: ObservationCache | None = None,
    ):
        """
        Parameters
        ----------
        skill_bridge : optional
            Object with an async ``invoke_simple(skill_name, params, cache_ttl)``
            method. If ``None``, lazily imported from ``app.skills.bridge``.
        cache : optional
            An ``ObservationCache`` for reproducibility. Results cached by
            (symbol, date, "volume_threshold", skill_version).
        """
        self._skill_bridge = skill_bridge
        self._cache = cache

    async def get_threshold(
        self,
        symbol: str,
        side: str,  # "buy" or "sell"
        as_of_date: date,
        config: BacktestConfig,
    ) -> float:
        """Get volume threshold multiplier for the given side and date.

        Parameters
        ----------
        symbol : str
            Signal ETF / sector code
        side : str
            "buy" or "sell"
        as_of_date : date
            Date to evaluate
        config : BacktestConfig
            Config with fallback defaults (buy_volume_ratio, breakdown_volume_ratio)

        Returns
        -------
        float
            Volume threshold multiplier (e.g., 1.8 = 1.8x MA20 volume).
            On skill failure, returns config defaults.
        """
        cache_key = None
        if self._cache is not None:
            # Cache key: symbol + date + side + skill name
            cache_key = f"volume_threshold:{symbol}:{as_of_date.isoformat()}:{side}"
            cached = await self._cache.get(cache_key)
            if cached is not None:
                # We store the threshold as a simple float in cache
                # Extract it from the cached judgment (or store separately)
                # For now, we'll skip caching structured judgments and just
                # cache the float threshold directly by storing in a separate field
                return float(cached.get("threshold", self._fallback(side, config)))

        threshold = await self._try_skill(symbol, side, as_of_date, config)
        if threshold is None:
            threshold = self._fallback(side, config)

        # Store in cache (as a simple dict for now)
        if self._cache is not None and cache_key is not None:
            await self._cache.set(cache_key, {"threshold": threshold})

        return threshold

    async def _try_skill(
        self,
        symbol: str,
        side: str,
        as_of_date: date,
        config: BacktestConfig,
    ) -> float | None:
        """Call the volume-threshold skill; return None on failure."""
        params = {
            "symbol": symbol,
            "side": side,
            "as_of_date": as_of_date.isoformat(),
        }
        try:
            result = await self._get_bridge().invoke_simple(
                _VOLUME_SKILL_NAME,
                params=params,
                cache_ttl=0,  # Use our own cache for reproducibility
            )
        except Exception as exc:
            logger.warning("VolumeThresholdProvider: skill call failed: %s", exc)
            return None

        if not result.success or not result.data:
            logger.warning(
                "VolumeThresholdProvider: skill returned failure: %s",
                getattr(result, "error", "unknown"),
            )
            return None

        # Expect result.data to have a "threshold" field
        threshold = result.data.get("threshold")
        if threshold is not None:
            try:
                return float(threshold)
            except (TypeError, ValueError):
                logger.warning(
                    "VolumeThresholdProvider: skill returned non-numeric threshold: %s",
                    threshold,
                )
                return None

        return None

    def _get_bridge(self):
        """Lazily resolve the global SkillBridge."""
        if self._skill_bridge is None:
            from app.skills.bridge import bridge

            self._skill_bridge = bridge
        return self._skill_bridge

    @staticmethod
    def _fallback(side: str, config: BacktestConfig) -> float:
        """Return config default for the given side."""
        if side == "buy":
            return config.buy_volume_ratio
        elif side == "sell":
            return config.breakdown_volume_ratio
        else:
            return 1.8  # Conservative default
