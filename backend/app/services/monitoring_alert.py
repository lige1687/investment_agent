"""Turn a DecisionCard's `monitoring[]` bullets into PriceAlert rows.

The LLM writes conditions in Chinese prose:
  "001513 净值跌破 5.5"
  "华夏恒生互联网若继续下跌至 -40%"
  "尾盘科技板块放量下跌立即通知"

We turn those into structured `PriceAlert` rows so the existing anomaly
scanner (or a future watcher job) can trigger and push to Feishu without
the user re-authoring them by hand.

Design: rule-based parser first. Pattern coverage is deliberately narrow
— common cases only. Unrecognized bullets fall back to a `technical`
alert with the raw text preserved in `note`, so nothing is silently
dropped and the user can still see & manage them via API.

Alerts spawned by one decision card all share `source_ref = decision_id`,
so re-sync is a clean delete + insert.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import PriceAlert
from app.schemas.decision_card import DecisionCard

logger = logging.getLogger(__name__)

# `\b` doesn't help here — Python 3 treats CJK chars as word chars, so
# "001513净值" has no word boundary between the two. We just require the
# 6-digit run itself to not be part of a longer digit run.
FUND_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")

# Numeric with optional decimals, followed by optional unit hints. We
# capture the sign because "-40%" and "40%" mean different things.
NUM_RE = r"([+\-]?\d+(?:\.\d+)?)"

# Direction verbs (跌/涨/破/穿/回落/上冲) mapped to price direction.
DOWN_VERBS = ("跌破", "跌至", "跌到", "回落至", "回落到", "下跌至", "下跌到", "破位")
UP_VERBS = ("涨破", "涨至", "涨到", "突破", "上冲至", "上冲到", "冲高至")

# Change-pct verbs.
DOWN_PCT_VERBS = ("跌超", "跌至", "跌破", "下跌", "亏损", "浮亏", "回撤", "跌", "回落")
UP_PCT_VERBS = ("涨超", "涨至", "涨破", "上涨", "浮盈", "涨")


@dataclass
class ParsedAlert:
    """Intermediate shape between parser and PriceAlert row."""
    symbol: str
    alert_type: str      # price_above / price_below / change_pct / consecutive_down / technical
    threshold: float
    direction: Optional[str]
    note: str            # original bullet, preserved for UI
    cooldown_min: int = 240   # default 4h cooldown for LLM-generated conditions

    def to_row_kwargs(self, *, source_ref: str, source: str) -> dict:
        return dict(
            symbol=self.symbol,
            alert_type=self.alert_type,
            threshold=self.threshold,
            direction=self.direction,
            enabled=True,
            cooldown_min=self.cooldown_min,
            source=source,
            source_ref=source_ref,
            note=self.note,
        )


class MonitoringAlertParser:
    """Rule-based parser. Emits zero or more ParsedAlert per bullet.

    We try patterns in order of specificity. First match wins; unrecognized
    bullets produce a `technical` fallback with threshold=0 so downstream
    can still list + surface them.
    """

    def __init__(self, *, default_symbol_from_target: Optional[str] = None):
        # If the bullet mentions no fund code AND target is a specific fund,
        # inherit the target's code.
        self.default_symbol = default_symbol_from_target

    def parse_bullet(self, text: str) -> list[ParsedAlert]:
        text = (text or "").strip()
        if not text:
            return []

        symbols = self._extract_symbols(text)
        if not symbols and self.default_symbol:
            symbols = [self.default_symbol]

        # Try each pattern in priority order. Percent tests come BEFORE
        # bare-number price tests so "跌破 5.5%" is read as change_pct,
        # not price_below(5.5).
        for parser in (
            self._parse_pct_threshold,
            self._parse_price_threshold,
            self._parse_consecutive,
        ):
            alerts = parser(text, symbols)
            if alerts:
                return alerts

        # Fallback: something to remember but not actionable
        return [ParsedAlert(
            symbol=symbols[0] if symbols else "_portfolio_",
            alert_type="technical",
            threshold=0.0,
            direction=None,
            note=text,
        )]

    # ── Individual pattern matchers ──────────────────────────────────

    def _parse_price_threshold(self, text: str, symbols: list[str]) -> list[ParsedAlert]:
        """Match "净值跌破 5.5" / "涨至 6.8 元"-type conditions.

        Requires a price-verb + a bare number (NOT followed by %).
        """
        results: list[ParsedAlert] = []
        for verb in DOWN_VERBS + UP_VERBS:
            # Number must NOT be followed by a percent sign (with optional
            # whitespace between) — that case is handled by pct parser.
            pattern = re.compile(rf"{verb}\s*{NUM_RE}(?!\s*%)")
            for m in pattern.finditer(text):
                value = float(m.group(1))
                direction = "below" if verb in DOWN_VERBS else "above"
                atype = "price_below" if direction == "below" else "price_above"
                for sym in symbols or [self.default_symbol or "_portfolio_"]:
                    results.append(ParsedAlert(
                        symbol=sym,
                        alert_type=atype,
                        threshold=value,
                        direction=direction,
                        note=text,
                    ))
        return results

    def _parse_pct_threshold(self, text: str, symbols: list[str]) -> list[ParsedAlert]:
        """Match "跌超 5%" / "浮盈达 50%" / "回撤 10% 以上"."""
        results: list[ParsedAlert] = []
        # Prefer the signed-percent form (-40% / +15%) — always change_pct
        for m in re.finditer(rf"([+\-])\s*(\d+(?:\.\d+)?)\s*%", text):
            sign = m.group(1)
            value = float(m.group(2)) * (-1 if sign == "-" else 1)
            direction = "below" if value < 0 else "above"
            for sym in symbols or [self.default_symbol or "_portfolio_"]:
                results.append(ParsedAlert(
                    symbol=sym,
                    alert_type="change_pct",
                    threshold=value,
                    direction=direction,
                    note=text,
                ))
        if results:
            return results

        # Unsigned percent with a verb — infer direction from verb
        for verb in DOWN_PCT_VERBS + UP_PCT_VERBS:
            for m in re.finditer(rf"{verb}\s*(\d+(?:\.\d+)?)\s*%", text):
                value = float(m.group(1))
                if verb in DOWN_PCT_VERBS:
                    value = -abs(value)
                    direction = "below"
                else:
                    direction = "above"
                for sym in symbols or [self.default_symbol or "_portfolio_"]:
                    results.append(ParsedAlert(
                        symbol=sym,
                        alert_type="change_pct",
                        threshold=value,
                        direction=direction,
                        note=text,
                    ))
        return results

    def _parse_consecutive(self, text: str, symbols: list[str]) -> list[ParsedAlert]:
        """Match "连续 3 日下跌" / "连续 3 天上涨"."""
        results: list[ParsedAlert] = []
        for m in re.finditer(r"连续\s*(\d+)\s*[日天]\s*(下跌|上涨|阴线|阳线)", text):
            days = int(m.group(1))
            verb = m.group(2)
            atype = "consecutive_down" if verb in ("下跌", "阴线") else "consecutive_up"
            direction = "below" if verb in ("下跌", "阴线") else "above"
            for sym in symbols or [self.default_symbol or "_portfolio_"]:
                results.append(ParsedAlert(
                    symbol=sym,
                    alert_type=atype,
                    threshold=float(days),
                    direction=direction,
                    note=text,
                ))
        return results

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _extract_symbols(text: str) -> list[str]:
        """Pull any 6-digit fund codes out of the bullet text."""
        return list(dict.fromkeys(FUND_CODE_RE.findall(text)))


class MonitoringAlertSynthesizer:
    """Sync a DecisionCard's monitoring[] to PriceAlert rows.

    Idempotent — calling twice with the same card deletes then re-inserts.
    """

    def __init__(self, db: AsyncSession):
        self._db = db

    async def sync_from_card(self, card: DecisionCard) -> list[PriceAlert]:
        """Persist alerts for `card`, replacing any prior batch tied to it.
        Returns the newly-written rows."""
        if not card.monitoring:
            # Nothing to do, but still clear any stale rows from a prior emission
            await self._delete_batch(card.decision_id)
            return []

        # Determine default symbol from card target if the target is a fund
        target = card.target
        kind = getattr(target.kind, "value", target.kind)
        default_symbol = target.code if kind == "fund" and target.code else None

        parser = MonitoringAlertParser(default_symbol_from_target=default_symbol)
        parsed: list[ParsedAlert] = []
        for bullet in card.monitoring:
            parsed.extend(parser.parse_bullet(bullet))

        # Clean old batch, then insert fresh
        await self._delete_batch(card.decision_id)

        source = self._source_from_agent(card.agent)
        rows: list[PriceAlert] = []
        for pa in parsed:
            row = PriceAlert(
                **pa.to_row_kwargs(source_ref=card.decision_id, source=source),
                updated_at=datetime.utcnow(),
            )
            self._db.add(row)
            rows.append(row)

        try:
            await self._db.flush()
        except Exception as e:
            logger.warning(
                "MonitoringAlertSynthesizer flush failed for %s: %s",
                card.decision_id, e,
            )
        return rows

    async def list_for_decision(self, decision_id: str) -> list[PriceAlert]:
        stmt = select(PriceAlert).where(PriceAlert.source_ref == decision_id)
        return list((await self._db.execute(stmt)).scalars().all())

    async def disable_batch(self, decision_id: str) -> int:
        """Set enabled=False on all alerts for this decision_id. Returns count."""
        rows = await self.list_for_decision(decision_id)
        for r in rows:
            r.enabled = False
            r.updated_at = datetime.utcnow()
        try:
            await self._db.flush()
        except Exception as e:
            logger.warning("disable_batch flush failed: %s", e)
        return len(rows)

    async def _delete_batch(self, decision_id: str) -> None:
        rows = await self.list_for_decision(decision_id)
        for r in rows:
            await self._db.delete(r)
        if rows:
            try:
                await self._db.flush()
            except Exception as e:
                logger.warning("_delete_batch flush failed: %s", e)

    @staticmethod
    def _source_from_agent(agent: str) -> str:
        agent = (agent or "").lower()
        return {"guardian": "guardian", "scout": "scout"}.get(agent, "decision")
