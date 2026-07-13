"""Rule-based holding health checker.

Runs BEFORE the LLM step. Every alert here is a hard, objective trigger
(loss %, concentration %, etc.) so the LLM starts with concrete reasons
to analyze rather than being asked "find something wrong" from scratch.

Thresholds are conservative defaults — the calling code can override
them per-user in the future via a UserRiskProfile row.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.schemas.guardian import AlertSeverity, AlertTrigger, HoldingAlert


@dataclass(frozen=True)
class HealthThresholds:
    # Loss depth — trigger + severity ladder
    loss_medium_pct: float = -15.0        # deeper losses get MEDIUM
    loss_high_pct: float = -25.0          # deeper get HIGH
    loss_min_allocation_pct: float = 2.0  # don't alarm on positions too tiny to matter

    # Concentration
    single_position_medium: float = 20.0  # any one holding > 20% of portfolio
    single_position_high: float = 30.0    # > 30% = HIGH
    top3_medium: float = 55.0             # top-3 combined > 55%
    top3_high: float = 65.0

    # Profit take — pure signal, no severity above MEDIUM
    profit_take_pct: float = 40.0         # +40% floating profit → consider batching out


class HoldingSummary:
    """Minimal dict shape we need from the portfolio.

    Kept as a duck-typed access wrapper so tests don't need real Position rows.
    Attributes come straight from `get_portfolio_summary` tool output:
      code, name, market_value, pnl_pct, allocation_pct
    """

    __slots__ = ("code", "name", "market_value", "pnl_pct", "allocation_pct")

    def __init__(
        self,
        code: str,
        name: str,
        market_value: float,
        pnl_pct: float,
        allocation_pct: float,
    ):
        self.code = code
        self.name = name
        self.market_value = float(market_value or 0.0)
        self.pnl_pct = float(pnl_pct or 0.0)
        self.allocation_pct = float(allocation_pct or 0.0)


class HoldingHealthChecker:
    def __init__(self, thresholds: HealthThresholds | None = None):
        self.t = thresholds or HealthThresholds()

    # ── Public API ────────────────────────────────────────────────────

    def detect_alerts(self, holdings: Iterable[dict | HoldingSummary]) -> list[HoldingAlert]:
        """Emit one HoldingAlert per matching rule. Rules stack — one holding
        can trigger multiple alerts (deep loss + high concentration)."""
        summaries = [self._normalize(h) for h in holdings]
        alerts: list[HoldingAlert] = []

        for h in summaries:
            alerts.extend(self._check_loss(h))
            alerts.extend(self._check_single_concentration(h))
            alerts.extend(self._check_profit_take(h))

        alerts.extend(self._check_top3_concentration(summaries))
        alerts.extend(self._check_duplicates(summaries))

        return alerts

    # ── Individual rules ──────────────────────────────────────────────

    def _check_loss(self, h: HoldingSummary) -> list[HoldingAlert]:
        if h.allocation_pct < self.t.loss_min_allocation_pct:
            return []
        if h.pnl_pct >= self.t.loss_medium_pct:
            return []

        if h.pnl_pct <= self.t.loss_high_pct:
            severity = AlertSeverity.HIGH
        else:
            severity = AlertSeverity.MEDIUM

        return [HoldingAlert(
            code=h.code, name=h.name,
            trigger=AlertTrigger.LOSS_DEEP,
            severity=severity,
            note=f"浮亏 {h.pnl_pct:.1f}%,仓位 {h.allocation_pct:.1f}%",
            metric_value=h.pnl_pct,
            threshold=self.t.loss_high_pct if severity == AlertSeverity.HIGH else self.t.loss_medium_pct,
        )]

    def _check_single_concentration(self, h: HoldingSummary) -> list[HoldingAlert]:
        if h.allocation_pct >= self.t.single_position_high:
            return [HoldingAlert(
                code=h.code, name=h.name,
                trigger=AlertTrigger.CONCENTRATION_HIGH,
                severity=AlertSeverity.HIGH,
                note=f"单只持仓占 {h.allocation_pct:.1f}%,风险过度集中",
                metric_value=h.allocation_pct,
                threshold=self.t.single_position_high,
            )]
        if h.allocation_pct >= self.t.single_position_medium:
            return [HoldingAlert(
                code=h.code, name=h.name,
                trigger=AlertTrigger.CONCENTRATION_HIGH,
                severity=AlertSeverity.MEDIUM,
                note=f"单只持仓占 {h.allocation_pct:.1f}%,偏集中",
                metric_value=h.allocation_pct,
                threshold=self.t.single_position_medium,
            )]
        return []

    def _check_profit_take(self, h: HoldingSummary) -> list[HoldingAlert]:
        if h.pnl_pct >= self.t.profit_take_pct and h.allocation_pct >= self.t.loss_min_allocation_pct:
            return [HoldingAlert(
                code=h.code, name=h.name,
                trigger=AlertTrigger.PROFIT_TAKE,
                severity=AlertSeverity.MEDIUM,
                note=f"浮盈 {h.pnl_pct:.1f}%,可考虑分批止盈锁定利润",
                metric_value=h.pnl_pct,
                threshold=self.t.profit_take_pct,
            )]
        return []

    def _check_top3_concentration(self, holdings: list[HoldingSummary]) -> list[HoldingAlert]:
        if not holdings:
            return []
        top3 = sorted(holdings, key=lambda x: x.allocation_pct, reverse=True)[:3]
        combined = sum(h.allocation_pct for h in top3)
        if combined >= self.t.top3_high:
            severity = AlertSeverity.HIGH
            threshold = self.t.top3_high
        elif combined >= self.t.top3_medium:
            severity = AlertSeverity.MEDIUM
            threshold = self.t.top3_medium
        else:
            return []

        names = " / ".join(f"{h.name}({h.code})" for h in top3)
        # We anchor the alert to the biggest holding so it groups with any
        # per-holding alerts on that name in the UI.
        anchor = top3[0]
        return [HoldingAlert(
            code=anchor.code, name=anchor.name,
            trigger=AlertTrigger.TOP3_CONCENTRATION,
            severity=severity,
            note=f"前三持仓合计 {combined:.1f}%(阈值 {threshold:.0f}%):{names}",
            metric_value=combined,
            threshold=threshold,
        )]

    def _check_duplicates(self, holdings: list[HoldingSummary]) -> list[HoldingAlert]:
        """Detect same fund held in A + C shares (or two share classes of the
        same product). Heuristic: name minus 'A'/'C' suffix must match.
        """
        by_stem: dict[str, list[HoldingSummary]] = {}
        for h in holdings:
            stem = self._name_stem(h.name)
            if not stem:
                continue
            by_stem.setdefault(stem, []).append(h)

        alerts: list[HoldingAlert] = []
        for stem, group in by_stem.items():
            if len(group) < 2:
                continue
            combined = sum(g.allocation_pct for g in group)
            if combined < 5.0:  # too small to bother flagging
                continue
            codes = " + ".join(g.code for g in group)
            # anchor to largest of the group
            anchor = max(group, key=lambda g: g.allocation_pct)
            alerts.append(HoldingAlert(
                code=anchor.code, name=stem,
                trigger=AlertTrigger.OVERLAP_DUPLICATE,
                severity=AlertSeverity.MEDIUM,
                note=f"{stem} 存在多份额同产品({codes}),合计 {combined:.1f}%",
                metric_value=combined,
                threshold=None,
            ))
        return alerts

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _normalize(h: dict | HoldingSummary) -> HoldingSummary:
        if isinstance(h, HoldingSummary):
            return h
        return HoldingSummary(
            code=str(h.get("code", "")),
            name=str(h.get("name", h.get("code", ""))),
            market_value=h.get("market_value") or 0.0,
            pnl_pct=h.get("pnl_pct") or 0.0,
            allocation_pct=h.get("allocation_pct") or 0.0,
        )

    @staticmethod
    def _name_stem(name: str) -> str:
        """Strip A/C share suffixes commonly used in Chinese fund names.

        Examples:
          '富国全球科技互联网股票(QDII)C' → '富国全球科技互联网股票(QDII)'
          '易方达全球成长精选(QDII)A'    → '易方达全球成长精选(QDII)'
        """
        stem = name.strip()
        if not stem:
            return ""
        # Strip trailing single-letter share class markers if preceded by a
        # non-alpha character (parenthesis, hanzi, digit, etc.) so we don't
        # eat the 'A' of a genuine word.
        if len(stem) > 1 and stem[-1] in "ACEBDR" and not stem[-2].isascii():
            return stem[:-1]
        return stem
