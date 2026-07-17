"""LLM-backed observation judge for the two-layer observation model.

Phase 1: replaces DeterministicJudge with a real LLM call through the
registry.  The judge builds a structured prompt describing the trigger,
the 2-day observation window, and the 5 verification dimensions (spec §4),
then maps the LLM's JSON response to an ObservationJudgment.

Design constraints:
- Every LLM call goes through ``get_llm_client("backtest_observer")``.
- temperature=0 for determinism; the ObservationCache (Task 2) makes results
  reproducible across runs.
- Unavailable dimensions (逻辑/催化, 资金回流 proxy, 组合允许 single-asset)
  are marked ``data_status=missing/proxy`` and must NOT cause fail-closed;
  the model bases its decision on the available (real) evidence only.
- If the LLM call fails or returns unparseable output, the judge returns a
  safe ``ObservationJudgment(decision="hold", confirmed=False,
  gate="llm_unavailable")`` -- it never raises.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.backtest.indicators import expma
from app.backtest.models import BacktestConfig, SignalBar
from app.backtest.observation.schemas import ObservationJudgment
from app.backtest.trigger_scanner import TriggerPoint

logger = logging.getLogger(__name__)

#: Bump this when the prompt or output schema changes to bust the cache.
PROMPT_VERSION = "llm-observer-v1"

_SYSTEM_PROMPT = """\
你是一个回测观察期裁判（backtest observer）。你的任务是根据 2 天观察窗口内的数据，\
判断一个机械触发信号（买入/卖出）是否在观察期内得到确认。

你将收到：
- 触发类型（买入/卖出）
- 触发日 T 的数据（日期、收盘价、成交量、EXPMA 值）
- 观察窗口 [T+1, T+2] 的 K 线数据（OHLCV + EXPMA）
- 参考标的代码

你需要从以下 5 个维度判断（注意每维的数据真实性标注）：

1. 趋势修复（data_status: real）—— 可从 K 线完全计算。
   买入：窗口内每日收盘价 >= EXPMA（站稳均线）。
   卖出：窗口内每日收盘价 <= EXPMA（稳定跌破均线）。
2. 量能健康（data_status: real）—— 可从成交量计算。观察窗口内无明显异常缩量。
3. 资金回流（data_status: proxy）—— 成交额是资金流向的弱代理。真实主力净流入数据在回测中不可用。
4. 组合允许（data_status: proxy）—— 回测为单标的，无真实组合约束。此维度为半真。
5. 逻辑/催化（data_status: missing）—— 新闻、公告、催化剂等数据在回测中不可用。

重要规则：
- 对于 data_status 为 missing 或 proxy 的维度，将 passed 设为 null（unknown），\
不要因为数据缺失而判定不通过（不 fail-closed）。
- 基于可用证据（真实维度：趋势修复 + 量能健康）做出决策。
- confirmed=true 表示观察窗口内条件持续成立（站稳 / 稳定跌破）。
- confirmed=false 表示条件未持续成立。
- 不要编造任何不存在的数据。

返回严格的 JSON 格式（不要包含其他文本）：
{
  "decision": "buy" | "sell" | "hold",
  "confirmed": true | false,
  "dimensions": [
    {"name": "趋势修复", "passed": true, "reason": "...", "data_status": "real"},
    {"name": "量能健康", "passed": true, "reason": "...", "data_status": "real"},
    {"name": "资金回流", "passed": null, "reason": "成交额代理，不足以下结论", "data_status": "proxy"},
    {"name": "组合允许", "passed": null, "reason": "单标的回测无组合约束", "data_status": "proxy"},
    {"name": "逻辑/催化", "passed": null, "reason": "回测中无新闻/催化剂数据", "data_status": "missing"}
  ],
  "reasons": ["原因1", "原因2"],
  "confidence": "high" | "medium" | "low"
}
"""


class LLMObserverJudge:
    """Observation judge backed by an LLM registry client.

    Parameters
    ----------
    client : optional
        An object with an async ``chat`` method (the LLMClient interface).
        If ``None``, the client is lazily resolved via
        ``get_llm_client("backtest_observer")`` on the first ``judge`` call.
        Tests inject a fake so the registry / credentials are never touched.
    config : optional
        Reserved for future per-judge configuration (unused in Phase 1a).
    """

    PROMPT_VERSION = PROMPT_VERSION

    def __init__(
        self,
        client: Any | None = None,
        config: Any | None = None,
    ):
        self._client = client
        self._config = config

    # ------------------------------------------------------------------
    # Public API (implements the ObservationJudge Protocol)
    # ------------------------------------------------------------------

    async def judge(
        self,
        trigger: TriggerPoint,
        window_bars: list[SignalBar],
        config: BacktestConfig,
        *,
        all_bars: list[SignalBar] | None = None,
    ) -> ObservationJudgment:
        prompt = self._build_prompt(trigger, window_bars, config, all_bars)
        try:
            response = await self._get_client().chat(
                messages=[_user_message(prompt)],
                temperature=0,
                max_tokens=1024,
                system=_SYSTEM_PROMPT,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            logger.warning("LLMObserverJudge: LLM call failed: %s", exc)
            return _unavailable(f"LLM 调用失败：{exc}")

        text = getattr(response, "text", "") or ""
        return self._parse_response(text, trigger)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_client(self):
        """Lazily resolve the registry client (never called when injected)."""
        if self._client is None:
            from app.llm.registry import get_llm_client

            self._client = get_llm_client("backtest_observer")
        return self._client

    @staticmethod
    def _build_prompt(
        trigger: TriggerPoint,
        window_bars: list[SignalBar],
        config: BacktestConfig,
        all_bars: list[SignalBar] | None,
    ) -> str:
        source_bars = all_bars if all_bars is not None else window_bars
        closes = [bar.close for bar in source_bars]
        expma_values = expma(closes, config.expma_window)

        # Trigger point data
        trigger_bar = (
            all_bars[trigger.index]
            if all_bars is not None and trigger.index < len(all_bars)
            else (window_bars[0] if window_bars else None)
        )
        trigger_expma = (
            expma_values[trigger.index] if trigger.index < len(expma_values) else None
        )

        lines: list[str] = []
        lines.append(f"参考标的：{config.signal_code}（{config.signal_name}）")
        lines.append(f"触发类型：{'买入' if trigger.kind == 'buy' else '卖出'}")
        lines.append(f"触发日 T：{trigger.date.isoformat()}（index={trigger.index}）")
        if trigger_bar is not None:
            lines.append(
                f"触发日数据：收盘={trigger_bar.close:.4f}，"
                f"成交量={trigger_bar.volume:.2f}，"
                f"EXPMA{config.expma_window}={trigger_expma:.4f}"
                if trigger_expma is not None
                else f"触发日数据：收盘={trigger_bar.close:.4f}，成交量={trigger_bar.volume:.2f}"
            )

        # Window bars
        lines.append(f"\n观察窗口（{len(window_bars)} 天）：")
        if all_bars is not None:
            start = trigger.index + 1
        else:
            start = 0
        for i, bar in enumerate(window_bars):
            idx = start + i
            ema = expma_values[idx] if idx < len(expma_values) else None
            ema_str = f"，EXPMA={ema:.4f}" if ema is not None else ""
            lines.append(
                f"  T+{i + 1} ({bar.date.isoformat()}): "
                f"开={bar.open:.4f} 高={bar.high:.4f} 低={bar.low:.4f} "
                f"收={bar.close:.4f} 量={bar.volume:.2f}"
                f"{' 额=' + format(bar.amount, '.2f') if bar.amount is not None else ''}"
                f"{ema_str}"
            )

        lines.append(
            "\n请根据以上数据，判断观察窗口内触发信号是否得到确认。" "返回严格的 JSON。"
        )
        return "\n".join(lines)

    @staticmethod
    def _parse_response(text: str, trigger: TriggerPoint) -> ObservationJudgment:
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            logger.warning("LLMObserverJudge: unparseable LLM output: %.200s", text)
            return _unavailable("LLM 返回无法解析的输出")

        if not isinstance(data, dict):
            return _unavailable("LLM 返回非对象 JSON")

        raw_decision = str(data.get("decision", "hold")).lower().strip()
        confirmed = bool(data.get("confirmed", False))

        # Sanitize decision
        if raw_decision in ("buy", "sell"):
            decision = raw_decision
        else:
            # reject, hold, unknown -> hold
            decision = "hold"

        # If confirmed=False but decision is buy/sell, that's contradictory -> hold
        if not confirmed and decision in ("buy", "sell"):
            decision = "hold"

        # Build reason
        reasons = data.get("reasons")
        if isinstance(reasons, list) and reasons:
            reason = "; ".join(str(r) for r in reasons)
        elif isinstance(reasons, str):
            reason = reasons
        else:
            reason = f"LLM 判定 decision={decision}, confirmed={confirmed}"

        if confirmed and decision in ("buy", "sell"):
            gate: Optional[str] = None
        else:
            gate = "observation_not_confirmed"

        return ObservationJudgment(
            decision=decision,  # type: ignore[arg-type]
            confirmed=confirmed,
            reason=reason,
            gate=gate,
        )


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _user_message(text: str):
    """Build a user Message without importing at module level (lazy)."""
    from app.llm.schemas import Message

    return Message.user(text)


def _unavailable(reason: str) -> ObservationJudgment:
    """Safe fallback when the LLM is unavailable or unparseable."""
    return ObservationJudgment(
        decision="hold",
        confirmed=False,
        reason=reason,
        gate="llm_unavailable",
    )
