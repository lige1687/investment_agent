from datetime import date, timedelta

from app.backtest.models import BacktestConfig, SignalBar
from app.backtest.trigger_scanner import TriggerPoint, TriggerScanner


def _bar(i, close, vol=100.0, prev_close=None):
    return SignalBar(
        date=date(2026, 1, 1) + timedelta(days=i),
        open=prev_close or close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=vol,
        amount=None,
    )


def _config(**overrides):
    values = {
        "fund_code": "x",
        "fund_name": "x",
        "signal_code": "x",
        "signal_name": "x",
        "expma_window": 15,
        "buy_volume_window": 10,
        "buy_volume_ratio": 1.2,
        "breakdown_volume_ratio": 1.5,
    }
    values.update(overrides)
    return BacktestConfig(**values)


def _flat_then_breakout(direction="up", vol=500.0):
    """40 bars flat at base=10.0, then a volume breakout up or down at index 40."""
    bars = []
    base = 10.0
    for i in range(40):
        bars.append(_bar(i, base))
    if direction == "up":
        bars.append(_bar(40, base + 2.0, vol=vol, prev_close=base))
    else:
        bars.append(_bar(40, base - 2.0, vol=vol, prev_close=base))
    return bars


# ── buy triggers ──────────────────────────────────────────────────────────


def test_buy_trigger_emitted_on_volume_breakout_above_ma():
    scanner = TriggerScanner(_config())
    triggers = scanner.scan(_flat_then_breakout("up", vol=500.0))
    buys = [t for t in triggers if t.kind == "buy"]
    assert len(buys) >= 1
    assert buys[-1].index == 40
    assert isinstance(buys[-1], TriggerPoint)


def test_no_trigger_without_volume():
    bars = _flat_then_breakout("up", vol=50.0)  # volume_ratio=0.5 < 1.2
    scanner = TriggerScanner(_config())
    triggers = scanner.scan(bars)
    assert not [t for t in triggers if t.kind == "buy" and t.index == 40]


# ── sell triggers ─────────────────────────────────────────────────────────


def test_sell_trigger_emitted_on_volume_breakdown_below_ma():
    scanner = TriggerScanner(_config())
    triggers = scanner.scan(_flat_then_breakout("down", vol=600.0))
    sells = [t for t in triggers if t.kind == "sell" and t.index == 40]
    assert len(sells) == 1


def test_no_sell_trigger_without_volume():
    bars = _flat_then_breakout("down", vol=40.0)  # volume_ratio=0.4 < 1.5
    scanner = TriggerScanner(_config())
    triggers = scanner.scan(bars)
    assert not [t for t in triggers if t.kind == "sell" and t.index == 40]


# ── edge cases ────────────────────────────────────────────────────────────


def test_no_triggers_when_data_insufficient():
    """Fewer bars than buy_volume_window -> volume_ratio all None -> no triggers."""
    bars = [_bar(i, 10.0 + i) for i in range(5)]
    scanner = TriggerScanner(_config(buy_volume_window=10))
    triggers = scanner.scan(bars)
    assert triggers == []


def test_triggers_ordered_by_index():
    """Multiple triggers in a sequence should be returned in chronological order."""
    bars = []
    base = 10.0
    for i in range(40):
        bars.append(_bar(i, base))
    # buy breakout at 40
    bars.append(_bar(40, base + 2.0, vol=500.0, prev_close=base))
    # hold above for 10 bars
    for i in range(41, 51):
        bars.append(_bar(i, base + 2.0, vol=100.0))
    # sell breakdown at 51
    bars.append(_bar(51, base - 2.0, vol=600.0, prev_close=base + 2.0))
    scanner = TriggerScanner(_config())
    triggers = scanner.scan(bars)
    # must be ordered by index
    indices = [t.index for t in triggers]
    assert indices == sorted(indices)
