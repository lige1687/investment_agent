"""Tests for ObservationCache - persistent judgment cache.

Tests use a temp file so they don't interfere with each other or the real
data directory. No real LLM calls are made.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.backtest.models import SignalBar
from app.backtest.observation.cache import ObservationCache, compute_cache_key
from app.backtest.observation.schemas import ObservationJudgment
from app.backtest.trigger_scanner import TriggerPoint


def _bar(i, close, vol=100.0):
    return SignalBar(
        date=date(2026, 1, 1) + timedelta(days=i),
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=vol,
        amount=close * vol,
    )


def _judgment(**overrides):
    defaults = {
        "decision": "buy",
        "confirmed": True,
        "reason": "test judgment",
        "gate": None,
    }
    defaults.update(overrides)
    return ObservationJudgment(**defaults)


# ── round-trip ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_then_get_round_trips(tmp_path):
    cache = ObservationCache(path=str(tmp_path / "cache.json"))
    bars = [_bar(41, 12.0), _bar(42, 12.0)]
    trigger = TriggerPoint(kind="buy", index=40, date=date(2026, 2, 10))
    key = compute_cache_key("sh510300", trigger, bars, "v1")

    await cache.set(key, _judgment())
    result = await cache.get(key)
    assert result is not None
    assert result.decision == "buy"
    assert result.confirmed is True
    assert result.reason == "test judgment"
    assert result.gate is None


@pytest.mark.asyncio
async def test_get_returns_none_for_unknown_key(tmp_path):
    cache = ObservationCache(path=str(tmp_path / "cache.json"))
    result = await cache.get("nonexistent-key")
    assert result is None


# ── different window bars -> miss ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_different_window_bars_produces_different_key(tmp_path):
    trigger = TriggerPoint(kind="buy", index=40, date=date(2026, 2, 10))
    bars_a = [_bar(41, 12.0), _bar(42, 12.0)]
    bars_b = [_bar(41, 11.0), _bar(42, 12.0)]  # different close

    key_a = compute_cache_key("sh510300", trigger, bars_a, "v1")
    key_b = compute_cache_key("sh510300", trigger, bars_b, "v1")
    assert key_a != key_b

    cache = ObservationCache(path=str(tmp_path / "cache.json"))
    await cache.set(key_a, _judgment())
    # key_b should miss even though trigger/symbol/version are the same
    assert await cache.get(key_b) is None
    assert (await cache.get(key_a)) is not None


# ── version bump -> miss ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_version_bump_produces_miss(tmp_path):
    trigger = TriggerPoint(kind="buy", index=40, date=date(2026, 2, 10))
    bars = [_bar(41, 12.0), _bar(42, 12.0)]

    key_v1 = compute_cache_key("sh510300", trigger, bars, "v1")
    key_v2 = compute_cache_key("sh510300", trigger, bars, "v2")
    assert key_v1 != key_v2

    cache = ObservationCache(path=str(tmp_path / "cache.json"))
    await cache.set(key_v1, _judgment())
    assert await cache.get(key_v2) is None


# ── different trigger kind/index -> miss ──────────────────────────────────


@pytest.mark.asyncio
async def test_different_trigger_kind_produces_different_key():
    bars = [_bar(41, 12.0), _bar(42, 12.0)]
    buy_trigger = TriggerPoint(kind="buy", index=40, date=date(2026, 2, 10))
    sell_trigger = TriggerPoint(kind="sell", index=40, date=date(2026, 2, 10))
    key_buy = compute_cache_key("sh510300", buy_trigger, bars, "v1")
    key_sell = compute_cache_key("sh510300", sell_trigger, bars, "v1")
    assert key_buy != key_sell


# ── different symbol -> miss ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_different_symbol_produces_different_key():
    bars = [_bar(41, 12.0), _bar(42, 12.0)]
    trigger = TriggerPoint(kind="buy", index=40, date=date(2026, 2, 10))
    key_a = compute_cache_key("sh510300", trigger, bars, "v1")
    key_b = compute_cache_key("sh512100", trigger, bars, "v1")
    assert key_a != key_b


# ── persistence across instances ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_persists_across_instances(tmp_path):
    path = str(tmp_path / "cache.json")
    bars = [_bar(41, 12.0), _bar(42, 12.0)]
    trigger = TriggerPoint(kind="buy", index=40, date=date(2026, 2, 10))
    key = compute_cache_key("sh510300", trigger, bars, "v1")

    cache1 = ObservationCache(path=path)
    await cache1.set(key, _judgment(reason="persistent"))

    cache2 = ObservationCache(path=path)
    result = await cache2.get(key)
    assert result is not None
    assert result.reason == "persistent"


# ── hold judgment with gate round-trips ───────────────────────────────────


@pytest.mark.asyncio
async def test_hold_judgment_with_gate_round_trips(tmp_path):
    cache = ObservationCache(path=str(tmp_path / "cache.json"))
    bars = [_bar(41, 12.0), _bar(42, 12.0)]
    trigger = TriggerPoint(kind="sell", index=40, date=date(2026, 2, 10))
    key = compute_cache_key("sh510300", trigger, bars, "v1")

    judgment = _judgment(
        decision="hold",
        confirmed=False,
        reason="not confirmed",
        gate="observation_not_confirmed",
    )
    await cache.set(key, judgment)
    result = await cache.get(key)
    assert result is not None
    assert result.decision == "hold"
    assert result.confirmed is False
    assert result.gate == "observation_not_confirmed"
