"""Observation judge: decides whether a trigger's observation window confirms the signal.

Phase 0 uses DeterministicJudge (pure function):
  - buy confirmed: every window bar close >= EXPMA (stood above)
  - sell confirmed: every window bar close <= EXPMA (stayed below)
  - incomplete window: fewer bars than OBSERVATION_DAYS -> hold

Phase 1 will add LLMObserverJudge implementing the same Protocol.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.backtest.indicators import expma
from app.backtest.models import BacktestConfig, SignalBar
from app.backtest.observation.schemas import ObservationJudgment
from app.backtest.trigger_scanner import TriggerPoint

OBSERVATION_DAYS = 2


@runtime_checkable
class ObservationJudge(Protocol):
    """Protocol for observation-window judges.

    Phase 0: DeterministicJudge
    Phase 1: LLMObserverJudge (swaps in, engine zero-change)
    """

    def judge(
        self,
        trigger: TriggerPoint,
        window_bars: list[SignalBar],
        config: BacktestConfig,
        *,
        all_bars: list[SignalBar] | None = None,
    ) -> ObservationJudgment: ...


class DeterministicJudge:
    """Phase 0 placeholder: confirms based on mechanical MA-standing rules.

    buy:  window bars all have close >= EXPMA -> confirmed
    sell: window bars all have close <= EXPMA -> confirmed
    """

    def judge(
        self,
        trigger: TriggerPoint,
        window_bars: list[SignalBar],
        config: BacktestConfig,
        *,
        all_bars: list[SignalBar] | None = None,
    ) -> ObservationJudgment:
        # Incomplete window check
        if len(window_bars) < OBSERVATION_DAYS:
            return ObservationJudgment(
                decision="hold",
                confirmed=False,
                reason=(
                    f"观察窗口不完整：需要{OBSERVATION_DAYS}天，实际{len(window_bars)}天"
                ),
                gate="incomplete_window",
            )

        # Compute EXPMA over the full bar history (if provided) so window-bar
        # EXPMA values reflect prior context. Fall back to window_bars only.
        source_bars = all_bars if all_bars is not None else window_bars
        closes = [bar.close for bar in source_bars]
        expma_values = expma(closes, config.expma_window)

        # Window bars start at trigger.index + 1 (T+1 .. T+OBSERVATION_DAYS).
        # When all_bars is provided, indices map directly into the full series.
        # Otherwise, they index into the window_bars slice.
        if all_bars is not None:
            start = trigger.index + 1
        else:
            start = 0
        window_indices = list(range(start, start + len(window_bars)))

        if trigger.kind == "buy":
            for bar, idx in zip(window_bars, window_indices):
                if idx >= len(expma_values) or bar.close < expma_values[idx]:
                    return ObservationJudgment(
                        decision="hold",
                        confirmed=False,
                        reason=(
                            f"买入观察期内第{idx - trigger.index}天收盘{bar.close:.2f}"
                            f"跌破EXPMA{expma_values[idx]:.2f}，未确认站稳"
                        ),
                        gate="observation_not_confirmed",
                    )
            return ObservationJudgment(
                decision="buy",
                confirmed=True,
                reason="买入观察期内连续站稳EXPMA上方，确认建仓",
            )

        if trigger.kind == "sell":
            for bar, idx in zip(window_bars, window_indices):
                if idx >= len(expma_values) or bar.close > expma_values[idx]:
                    return ObservationJudgment(
                        decision="hold",
                        confirmed=False,
                        reason=(
                            f"卖出观察期内第{idx - trigger.index}天收盘{bar.close:.2f}"
                            f"站回EXPMA{expma_values[idx]:.2f}上方，未确认稳定跌破"
                        ),
                        gate="observation_not_confirmed",
                    )
            return ObservationJudgment(
                decision="sell",
                confirmed=True,
                reason="卖出观察期内连续稳定跌破EXPMA，确认卖出",
            )

        return ObservationJudgment(
            decision="hold",
            confirmed=False,
            reason=f"未知触发类型: {trigger.kind}",
            gate="observation_not_confirmed",
        )
