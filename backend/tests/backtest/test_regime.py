"""Tests for SectorRegimeProvider - per-sector regime via skill + fallback.

All tests inject a fake skill bridge so no real SkillBridge/CLI/network
call is made.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from app.backtest.models import BacktestConfig, SignalBar
from app.backtest.observation.regime import (
    RegimeCache,
    SectorRegimeProvider,
)
from app.skills.base import SkillResult


def _bar(i: int, close: float, vol: float = 100.0) -> SignalBar:
    return SignalBar(
        date=date(2026, 1, 1) + timedelta(days=i),
        open=close,
        high=close + 0.5,
        low=close - 0.5,
        close=close,
        volume=vol,
        amount=close * vol,
    )


def _cfg(**overrides: Any) -> BacktestConfig:
    values: dict[str, Any] = {
        "fund_code": "001513",
        "fund_name": "test",
        "signal_code": "sh515880",
        "signal_name": "通信ETF",
        "expma_window": 15,
        "buy_volume_window": 10,
    }
    values.update(overrides)
    return BacktestConfig(**values)


class FakeSkillBridge:
    """Minimal fake SkillBridge that records calls and returns canned results."""

    def __init__(
        self,
        result: SkillResult | None = None,
        raise_exc: Exception | None = None,
    ):
        self._result = result
        self._raise = raise_exc
        self.call_count = 0
        self.last_params: dict | None = None

    async def invoke_simple(
        self,
        skill_name: str,
        params: dict | None = None,
        cache_ttl: int | None = None,
    ) -> SkillResult:
        self.call_count += 1
        self.last_params = params
        if self._raise:
            raise self._raise
        return self._result or SkillResult(success=False, error="no result")


_BULL_SKILL_OUTPUT = """\
Market Regime Assessment:
- Total score: 85
- Market state: Bull market / strong trend
- Domestic index trend: most indices above 60-day and 120-day moving averages
- External market environment: Nasdaq strong trend
- Macro rates / liquidity: domestic and global liquidity loose
- Market sentiment / money-making effect: turnover expands, main themes persist
- Sector structure and style: offensive assets clearly stronger than defensive

Account-Level Constraints:
- Total position cap: 80%-90%
- Buy-score threshold: 65+
- Take-profit tightness: Loose take-profit for core batches; let profits run
- High-volatility asset permission: allowed
- Cash / defensive / short-duration bond bias: minimal

Decision Boundary:
- This is only a market environment judgment, not an individual security buy/sell decision.
- Missing information: none
- Confidence: high
"""

_BEAR_SKILL_OUTPUT = """\
Market Regime Assessment:
- Total score: 25
- Market state: Weak market / bear market
- Domestic index trend: most indices below 60-day and 120-day moving averages
- External market environment: Nasdaq weak, US rates up
- Macro rates / liquidity: rates up, FX pressured
- Market sentiment / money-making effect: broad decline, low volume
- Sector structure and style: defensive stronger than growth

Account-Level Constraints:
- Total position cap: 30%-50%
- Buy-score threshold: 85+
- Take-profit tightness: Tighten trailing take-profit
- High-volatility asset permission: not allowed
- Cash / defensive / short-duration bond bias: high

Decision Boundary:
- Confidence: medium
"""


# ── skill returns bull/loose ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_returns_bull_loose():
    """Fake skill returns bull market -> SectorRegime(state=bull, tightness=loose)."""
    bridge = FakeSkillBridge(SkillResult(success=True, data=_BULL_SKILL_OUTPUT))
    provider = SectorRegimeProvider(skill_bridge=bridge)
    bars = [_bar(i, 10.0 + i * 0.1) for i in range(70)]
    regime = await provider.assess("sh515880", bars, 65, _cfg())
    assert regime.state == "bull"
    assert regime.take_profit_tightness == "loose"
    assert regime.source == "skill"
    assert len(regime.skill_versions) > 0
    assert bridge.call_count == 1
    # sector context is passed to the skill
    assert bridge.last_params is not None
    assert "sector_context" in bridge.last_params


@pytest.mark.asyncio
async def test_skill_returns_bear_tight():
    """Fake skill returns bear market -> SectorRegime(state=bear, tightness=tight)."""
    bridge = FakeSkillBridge(SkillResult(success=True, data=_BEAR_SKILL_OUTPUT))
    provider = SectorRegimeProvider(skill_bridge=bridge)
    bars = [_bar(i, 10.0 + i * 0.1) for i in range(70)]
    regime = await provider.assess("sh515880", bars, 65, _cfg())
    assert regime.state == "bear"
    assert regime.take_profit_tightness == "tight"
    assert regime.source == "skill"


# ── skill raises -> fallback_trend ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_raises_fallback_trend_bull():
    """When the skill raises, fallback_trend is used (deterministic, never raises)."""
    bridge = FakeSkillBridge(raise_exc=RuntimeError("skill unavailable"))
    provider = SectorRegimeProvider(skill_bridge=bridge)
    bars = [_bar(i, 10.0 + i * 0.1) for i in range(70)]  # rising -> bull
    regime = await provider.assess("sh515880", bars, 65, _cfg())
    assert regime.source == "fallback_trend"
    assert regime.state == "bull"
    assert regime.take_profit_tightness == "loose"
    assert len(regime.skill_versions) > 0
    assert bridge.call_count == 1


@pytest.mark.asyncio
async def test_skill_raises_fallback_trend_bear():
    """Falling trend -> fallback bear."""
    bridge = FakeSkillBridge(raise_exc=RuntimeError("skill unavailable"))
    provider = SectorRegimeProvider(skill_bridge=bridge)
    bars = [_bar(i, 20.0 - i * 0.1) for i in range(70)]  # falling -> bear
    regime = await provider.assess("sh515880", bars, 65, _cfg())
    assert regime.source == "fallback_trend"
    assert regime.state == "bear"
    assert regime.take_profit_tightness == "tight"


@pytest.mark.asyncio
async def test_skill_unavailable_fallback_trend():
    """When the skill returns success=False (no strategy), fallback_trend is used."""
    bridge = FakeSkillBridge(SkillResult(success=False, error="no strategy"))
    provider = SectorRegimeProvider(skill_bridge=bridge)
    bars = [_bar(i, 10.0 + i * 0.1) for i in range(70)]
    regime = await provider.assess("sh515880", bars, 65, _cfg())
    assert regime.source == "fallback_trend"
    assert regime.state == "bull"


# ── cache hit skips skill ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_hit_skips_skill(tmp_path):
    """Second call with same symbol+date+version hits cache, skill not called again."""
    bridge = FakeSkillBridge(SkillResult(success=True, data=_BULL_SKILL_OUTPUT))
    cache = RegimeCache(path=str(tmp_path / "regime.json"))
    provider = SectorRegimeProvider(skill_bridge=bridge, cache=cache)
    bars = [_bar(i, 10.0 + i * 0.1) for i in range(70)]

    r1 = await provider.assess("sh515880", bars, 65, _cfg())
    assert bridge.call_count == 1
    assert r1.source == "skill"
    assert r1.state == "bull"

    r2 = await provider.assess("sh515880", bars, 65, _cfg())
    assert bridge.call_count == 1  # still 1 — cache hit
    assert r2.state == r1.state
    assert r2.source == r1.source


@pytest.mark.asyncio
async def test_cache_persists_across_instances(tmp_path):
    """Cache persists to disk across provider instances."""
    path = str(tmp_path / "regime.json")
    bridge1 = FakeSkillBridge(SkillResult(success=True, data=_BULL_SKILL_OUTPUT))
    provider1 = SectorRegimeProvider(skill_bridge=bridge1, cache=RegimeCache(path=path))
    bars = [_bar(i, 10.0 + i * 0.1) for i in range(70)]

    await provider1.assess("sh515880", bars, 65, _cfg())
    assert bridge1.call_count == 1

    bridge2 = FakeSkillBridge(SkillResult(success=True, data=_BEAR_SKILL_OUTPUT))
    provider2 = SectorRegimeProvider(skill_bridge=bridge2, cache=RegimeCache(path=path))
    r = await provider2.assess("sh515880", bars, 65, _cfg())
    assert bridge2.call_count == 0  # cache hit — skill never called
    assert r.state == "bull"  # cached bull, not the bear from bridge2


# ── different date -> cache miss ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_different_date_produces_cache_miss(tmp_path):
    """Different as_of_date -> different cache key -> skill called again."""
    bridge = FakeSkillBridge(SkillResult(success=True, data=_BULL_SKILL_OUTPUT))
    cache = RegimeCache(path=str(tmp_path / "regime.json"))
    provider = SectorRegimeProvider(skill_bridge=bridge, cache=cache)
    bars = [_bar(i, 10.0 + i * 0.1) for i in range(70)]

    await provider.assess("sh515880", bars, 60, _cfg())
    await provider.assess("sh515880", bars, 65, _cfg())
    assert bridge.call_count == 2  # different dates -> two calls
