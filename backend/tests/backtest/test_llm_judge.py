"""Tests for LLMObserverJudge - LLM-backed observation window judge.

All tests inject a fake LLM client so no real network call is made.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import pytest

from app.backtest.models import BacktestConfig, SignalBar
from app.backtest.observation.llm_judge import LLMObserverJudge
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


def _cfg(**overrides):
    values = {
        "fund_code": "001513",
        "fund_name": "test",
        "signal_code": "sh510300",
        "signal_name": "test",
        "expma_window": 15,
    }
    values.update(overrides)
    return BacktestConfig(**values)


class FakeLLMClient:
    """Minimal fake that records calls and returns a canned LLMResponse."""

    def __init__(self, response_text: str = "", raise_exc: Exception | None = None):
        self._response_text = response_text
        self._raise = raise_exc
        self.call_count = 0
        self.last_messages: list[Any] = []
        self.last_temperature: float | None = None
        self.last_response_format: dict | None = None

    async def chat(
        self,
        messages,
        *,
        temperature=0.3,
        max_tokens=4096,
        system=None,
        response_format=None,
        tools=None,
    ):
        self.call_count += 1
        self.last_messages = messages
        self.last_temperature = temperature
        self.last_response_format = response_format
        if self._raise:
            raise self._raise

        # Return an object with .text attribute like LLMResponse
        class _Resp:
            text = self._response_text

        return _Resp()


def _buy_trigger(bars):
    return TriggerPoint(kind="buy", index=40, date=bars[40].date)


def _sell_trigger(bars):
    return TriggerPoint(kind="sell", index=40, date=bars[40].date)


def _window_bars(bars):
    return bars[41:43]


# ── confirmed buy ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_confirmed_buy_maps_to_buy_judgment():
    """LLM returns confirmed=true, decision=buy -> ObservationJudgment(decision=buy, confirmed=True)."""
    bars = [_bar(i, 10.0) for i in range(40)] + [_bar(i, 12.0) for i in range(40, 43)]
    canned = json.dumps(
        {
            "decision": "buy",
            "confirmed": True,
            "dimensions": [
                {
                    "name": "趋势修复",
                    "passed": True,
                    "reason": "站稳EXPMA",
                    "data_status": "real",
                },
                {
                    "name": "量能健康",
                    "passed": True,
                    "reason": "量能充足",
                    "data_status": "real",
                },
                {
                    "name": "资金回流",
                    "passed": None,
                    "reason": "代理数据",
                    "data_status": "proxy",
                },
                {
                    "name": "组合允许",
                    "passed": None,
                    "reason": "单标的",
                    "data_status": "proxy",
                },
                {
                    "name": "逻辑/催化",
                    "passed": None,
                    "reason": "无数据",
                    "data_status": "missing",
                },
            ],
            "reasons": ["趋势修复确认，量能健康"],
            "confidence": "high",
        }
    )
    fake = FakeLLMClient(canned)
    judge = LLMObserverJudge(client=fake)
    j = await judge.judge(_buy_trigger(bars), _window_bars(bars), _cfg(), all_bars=bars)
    assert j.decision == "buy"
    assert j.confirmed is True
    assert j.gate is None
    assert isinstance(j, ObservationJudgment)


# ── not confirmed -> hold ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_not_confirmed_maps_to_hold_with_gate():
    """LLM returns confirmed=false -> hold with observation_not_confirmed gate."""
    bars = [_bar(i, 10.0) for i in range(40)] + [_bar(i, 12.0) for i in range(40, 43)]
    canned = json.dumps(
        {
            "decision": "hold",
            "confirmed": False,
            "dimensions": [
                {
                    "name": "趋势修复",
                    "passed": False,
                    "reason": "T+1跌破",
                    "data_status": "real",
                },
            ],
            "reasons": ["趋势未修复"],
            "confidence": "medium",
        }
    )
    fake = FakeLLMClient(canned)
    judge = LLMObserverJudge(client=fake)
    j = await judge.judge(_buy_trigger(bars), _window_bars(bars), _cfg(), all_bars=bars)
    assert j.decision == "hold"
    assert j.confirmed is False
    assert j.gate == "observation_not_confirmed"


# ── unavailable dims don't fail-closed ────────────────────────────────────


@pytest.mark.asyncio
async def test_unavailable_dims_do_not_fail_closed():
    """Missing/proxy dims with passed=null must not cause the judge to fail-closed.

    The LLM can still confirm based on real dims (趋势修复 + 量能健康).
    """
    bars = [_bar(i, 10.0) for i in range(40)] + [_bar(i, 12.0) for i in range(40, 43)]
    canned = json.dumps(
        {
            "decision": "sell",
            "confirmed": True,
            "dimensions": [
                {
                    "name": "趋势修复",
                    "passed": True,
                    "reason": "稳定跌破",
                    "data_status": "real",
                },
                {
                    "name": "量能健康",
                    "passed": True,
                    "reason": "放量确认",
                    "data_status": "real",
                },
                {
                    "name": "资金回流",
                    "passed": None,
                    "reason": "代理不足",
                    "data_status": "proxy",
                },
                {
                    "name": "组合允许",
                    "passed": None,
                    "reason": "单标的",
                    "data_status": "proxy",
                },
                {
                    "name": "逻辑/催化",
                    "passed": None,
                    "reason": "无数据",
                    "data_status": "missing",
                },
            ],
            "reasons": ["基于真实维度确认"],
            "confidence": "medium",
        }
    )
    fake = FakeLLMClient(canned)
    judge = LLMObserverJudge(client=fake)
    j = await judge.judge(
        _sell_trigger(bars), _window_bars(bars), _cfg(), all_bars=bars
    )
    assert j.confirmed is True
    assert j.decision == "sell"
    assert j.gate is None


# ── LLM call failure -> safe hold ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_exception_returns_unavailable_gate():
    """When the LLM call raises, judge returns hold with gate=llm_unavailable, never raises."""
    bars = [_bar(i, 10.0) for i in range(40)] + [_bar(i, 12.0) for i in range(40, 43)]
    fake = FakeLLMClient(raise_exc=RuntimeError("network down"))
    judge = LLMObserverJudge(client=fake)
    j = await judge.judge(_buy_trigger(bars), _window_bars(bars), _cfg(), all_bars=bars)
    assert j.decision == "hold"
    assert j.confirmed is False
    assert j.gate == "llm_unavailable"


# ── unparseable output -> safe hold ───────────────────────────────────────


@pytest.mark.asyncio
async def test_unparseable_output_returns_unavailable_gate():
    """When the LLM returns non-JSON, judge returns hold with gate=llm_unavailable."""
    bars = [_bar(i, 10.0) for i in range(40)] + [_bar(i, 12.0) for i in range(40, 43)]
    fake = FakeLLMClient("this is not json at all")
    judge = LLMObserverJudge(client=fake)
    j = await judge.judge(_buy_trigger(bars), _window_bars(bars), _cfg(), all_bars=bars)
    assert j.decision == "hold"
    assert j.confirmed is False
    assert j.gate == "llm_unavailable"


# ── temperature is 0 and JSON mode is used ────────────────────────────────


@pytest.mark.asyncio
async def test_uses_temperature_zero_and_json_mode():
    """The judge must call the client with temperature=0 and response_format json_object."""
    bars = [_bar(i, 10.0) for i in range(40)] + [_bar(i, 12.0) for i in range(40, 43)]
    canned = json.dumps(
        {"decision": "buy", "confirmed": True, "reasons": ["ok"], "confidence": "high"}
    )
    fake = FakeLLMClient(canned)
    judge = LLMObserverJudge(client=fake)
    await judge.judge(_buy_trigger(bars), _window_bars(bars), _cfg(), all_bars=bars)
    assert fake.last_temperature == 0
    assert fake.last_response_format == {"type": "json_object"}


# ── injected client means no registry touch ───────────────────────────────


@pytest.mark.asyncio
async def test_injected_client_never_touches_registry():
    """When a client is injected, the registry/credentials are never accessed."""
    bars = [_bar(i, 10.0) for i in range(40)] + [_bar(i, 12.0) for i in range(40, 43)]
    canned = json.dumps(
        {"decision": "buy", "confirmed": True, "reasons": ["ok"], "confidence": "high"}
    )
    fake = FakeLLMClient(canned)
    judge = LLMObserverJudge(client=fake)
    # If this tried to call get_llm_client it would fail (no credentials in test env)
    await judge.judge(_buy_trigger(bars), _window_bars(bars), _cfg(), all_bars=bars)
    assert fake.call_count == 1


# ── sell confirmed ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_confirmed_sell_maps_to_sell_judgment():
    """LLM returns confirmed=true, decision=sell -> ObservationJudgment(decision=sell, confirmed=True)."""
    bars = [_bar(i, 10.0) for i in range(40)] + [_bar(i, 8.0) for i in range(40, 43)]
    canned = json.dumps(
        {
            "decision": "sell",
            "confirmed": True,
            "dimensions": [
                {
                    "name": "趋势修复",
                    "passed": True,
                    "reason": "稳定跌破",
                    "data_status": "real",
                },
            ],
            "reasons": ["稳定跌破EXPMA"],
            "confidence": "high",
        }
    )
    fake = FakeLLMClient(canned)
    judge = LLMObserverJudge(client=fake)
    j = await judge.judge(
        _sell_trigger(bars), _window_bars(bars), _cfg(), all_bars=bars
    )
    assert j.decision == "sell"
    assert j.confirmed is True
    assert j.gate is None


# ── contradicting decision/confirmed is sanitized ─────────────────────────


@pytest.mark.asyncio
async def test_contradicting_decision_confirmed_sanitized_to_hold():
    """If LLM says decision=buy but confirmed=false, sanitize to hold."""
    bars = [_bar(i, 10.0) for i in range(40)] + [_bar(i, 12.0) for i in range(40, 43)]
    canned = json.dumps(
        {
            "decision": "buy",
            "confirmed": False,
            "reasons": ["contradiction"],
            "confidence": "low",
        }
    )
    fake = FakeLLMClient(canned)
    judge = LLMObserverJudge(client=fake)
    j = await judge.judge(_buy_trigger(bars), _window_bars(bars), _cfg(), all_bars=bars)
    assert j.decision == "hold"
    assert j.confirmed is False
