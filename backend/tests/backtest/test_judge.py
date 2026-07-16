from datetime import date, timedelta

from app.backtest.models import BacktestConfig, SignalBar
from app.backtest.observation.judge import OBSERVATION_DAYS, DeterministicJudge
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
        amount=None,
    )


def _cfg(**overrides):
    values = {
        "fund_code": "x",
        "fund_name": "x",
        "signal_code": "x",
        "signal_name": "x",
        "expma_window": 15,
    }
    values.update(overrides)
    return BacktestConfig(**values)


# ── buy confirmed / not confirmed ─────────────────────────────────────────


def test_buy_confirmed_when_window_holds_above_ma():
    """After a buy trigger, T+1 and T+2 both hold above EXPMA -> confirmed."""
    bars = [_bar(i, 10.0) for i in range(40)] + [_bar(i, 12.0) for i in range(40, 43)]
    trigger = TriggerPoint(kind="buy", index=40, date=bars[40].date)
    j = DeterministicJudge().judge(trigger, bars[41 : 41 + OBSERVATION_DAYS], _cfg(), all_bars=bars)
    assert j.confirmed is True
    assert j.decision == "buy"
    assert isinstance(j, ObservationJudgment)


def test_buy_not_confirmed_when_window_falls_back_below_ma():
    """T+1 falls back below EXPMA -> not confirmed, hold with gate."""
    bars = [_bar(i, 10.0) for i in range(40)] + [_bar(i, 12.0) for i in range(40, 43)]
    bars[41] = _bar(41, 8.0)
    trigger = TriggerPoint(kind="buy", index=40, date=bars[40].date)
    j = DeterministicJudge().judge(trigger, bars[41:43], _cfg(), all_bars=bars)
    assert j.confirmed is False
    assert j.decision == "hold"
    assert j.gate == "observation_not_confirmed"


# ── incomplete window ─────────────────────────────────────────────────────


def test_incomplete_window_holds():
    """Window has fewer bars than OBSERVATION_DAYS -> hold with incomplete_window gate."""
    bars = [_bar(i, 10.0) for i in range(40)] + [_bar(40, 12.0), _bar(41, 12.0)]
    trigger = TriggerPoint(kind="buy", index=40, date=bars[40].date)
    j = DeterministicJudge().judge(trigger, [_bar(41, 12.0)], _cfg(), all_bars=bars)
    assert j.decision == "hold"
    assert j.gate == "incomplete_window"


def test_empty_window_holds():
    bars = [_bar(i, 10.0) for i in range(40)] + [_bar(40, 8.0)]
    trigger = TriggerPoint(kind="sell", index=40, date=bars[40].date)
    j = DeterministicJudge().judge(trigger, [], _cfg(), all_bars=bars)
    assert j.decision == "hold"
    assert j.gate == "incomplete_window"


# ── sell confirmed / not confirmed ────────────────────────────────────────


def test_sell_confirmed_when_window_stays_below_ma():
    """After a sell trigger, T+1 and T+2 both stay below EXPMA -> confirmed."""
    bars = [_bar(i, 10.0) for i in range(40)] + [_bar(i, 8.0) for i in range(40, 43)]
    trigger = TriggerPoint(kind="sell", index=40, date=bars[40].date)
    j = DeterministicJudge().judge(trigger, bars[41:43], _cfg(), all_bars=bars)
    assert j.confirmed is True
    assert j.decision == "sell"


def test_sell_not_confirmed_when_window_reclaims_above_ma():
    """T+1 reclaims above EXPMA -> not confirmed, hold with gate."""
    bars = [_bar(i, 10.0) for i in range(40)] + [_bar(i, 8.0) for i in range(40, 43)]
    bars[41] = _bar(41, 12.0)
    trigger = TriggerPoint(kind="sell", index=40, date=bars[40].date)
    j = DeterministicJudge().judge(trigger, bars[41:43], _cfg(), all_bars=bars)
    assert j.confirmed is False
    assert j.decision == "hold"
    assert j.gate == "observation_not_confirmed"
