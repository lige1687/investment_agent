"""Technical indicator helpers used by the backtest engine."""
from __future__ import annotations


def moving_average(values: list[float], window: int) -> list[float | None]:
    """Return a simple moving average aligned to the input values."""
    if window <= 0:
        raise ValueError("window must be positive")

    result: list[float | None] = []
    running_sum = 0.0
    for index, value in enumerate(values):
        running_sum += value
        if index >= window:
            running_sum -= values[index - window]
        if index + 1 < window:
            result.append(None)
        else:
            result.append(running_sum / window)
    return result


def expma(values: list[float], window: int) -> list[float]:
    """Return an exponential moving average seeded from the first value."""
    if window <= 0:
        raise ValueError("window must be positive")
    if not values:
        return []

    alpha = 2 / (window + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(value * alpha + result[-1] * (1 - alpha))
    return result


def volume_ratio(volumes: list[float], window: int) -> list[float | None]:
    """Compare each volume to the prior window average.

    The current bar is excluded from the average so a breakout day can be
    measured against the already-known baseline.
    """
    if window <= 0:
        raise ValueError("window must be positive")

    result: list[float | None] = []
    for index, volume in enumerate(volumes):
        if index < window:
            result.append(None)
            continue
        baseline = sum(volumes[index - window:index]) / window
        result.append(None if baseline == 0 else volume / baseline)
    return result

