"""GuardianAgent — daily-scan agent for portfolio health.

Fires at 11:30 (midday) and 14:30 (close) on trading days. Each run:

  1. Snapshots portfolio + market to the Evidence Bus
  2. Runs rule-based HoldingHealthChecker to get objective alerts
  3. Asks a *single* LLM turn to write a briefing + emit a WATCH-type
     DecisionCard for the whole portfolio
  4. For each rule alert, emits a SELL_ALERT / WATCH DecisionCard so
     the frontend can render one card per triggered holding
  5. Persists a GuardianRun row and optionally pushes to Feishu

The LLM turn is deliberately NOT a tool-use loop — Guardian already knows
what data it needs and hands it in the prompt. This keeps midday/close
runs fast (~5s) and cheap.

When the LLM is unavailable, Guardian degrades to a pure-rule text
briefing and still saves cards for every alert (with a fixed template).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.feishu.bot import feishu_bot
from app.llm import LLMError, Message, get_llm_client
from app.models.evidence import GuardianRun as GuardianRunRow
from app.schemas.decision_card import (
    Action,
    ActionVerb,
    DecisionCard,
    DecisionType,
    Dimension,
    DimensionKey,
    PortfolioContext,
    PortfolioRole,
    Target,
    TargetKind,
    Urgency,
)
from app.schemas.guardian import (
    AlertSeverity,
    AlertTrigger,
    BriefingResult,
    BriefingSlot,
    HoldingAlert,
)
from app.services.agent_service import InvestmentAgent
from app.services.decision_store import DecisionCardStore
from app.services.evidence_bus import EvidenceBus
from app.services.holding_health import HoldingHealthChecker

logger = logging.getLogger(__name__)


GUARDIAN_SYSTEM_PROMPT = """你是持仓守护 Agent (Guardian)。你的职责不是聊天,是在每天两个时间点(午盘 11:30 / 尾盘 14:30)对用户组合做体检。

你收到的输入:
- 用户持仓 JSON(含每只基金的名称、代码、市值、盈亏、仓位占比)
- 当前市场 JSON(全球指数、情绪、资金流入板块)
- 规则检测出的持仓预警清单(alerts)——这些是客观触发的,已确定要提醒用户

你必须严格输出一个 JSON,内容如下 schema。不要输出其它文本,不要用 markdown 代码块,直接输出 JSON:

{
  "briefing_text": "推送给用户的简明总结(纯文本,80-200 字,首行'午盘/尾盘体检:...'开头,末行加'仅供参考,不构成投资建议')",
  "portfolio_card": {
    "headline": "一句话组合状态,如'尾盘体检:科技集中度高,前三持仓 60.7%'",
    "summary": "2-4 句核心洞察",
    "action_verb": "HOLD | REDUCE | ADD | WATCH",
    "confidence": 0.0~1.0,
    "urgency": "LOW | MEDIUM | HIGH",
    "dimensions": [
      {"key": "technical | capital | macro | news | financial | consensus", "score": 0~10, "signal": "一句话依据", "evidence_ref": "ev_xxx"}
    ],
    "portfolio_role": "COMPLEMENT | STRENGTHEN | DUPLICATE | NEW",
    "portfolio_warning": "组合层面的风险提示(如集中度过高)",
    "monitoring": ["监控条件列表,如'尾盘继续放量下跌立即通知'"]
  }
}

规则:
- 6 维只写你有数据依据的,不要凑数
- dimensions[*].evidence_ref 必须引用输入里给你的 evidence_id (如 ev_abc)
- action_verb=HOLD 只用于组合整体平稳的场景;组合有严重风险(集中度过高、重大预警)时用 REDUCE 或 WATCH
- 中文
"""


def _today_str() -> str:
    return date.today().strftime("%Y%m%d")


def _new_session_id(slot: BriefingSlot) -> str:
    slot_val = slot.value if isinstance(slot, BriefingSlot) else str(slot)
    return f"guardian_{_today_str()}_{slot_val}"


def _slot_label(slot: BriefingSlot) -> str:
    return {"midday": "午盘", "close": "尾盘", "manual": "临时"}.get(
        slot.value if isinstance(slot, BriefingSlot) else str(slot), "体检",
    )


def _severity_to_urgency(sev: AlertSeverity | str) -> Urgency:
    s = sev.value if isinstance(sev, AlertSeverity) else sev
    return {"HIGH": Urgency.HIGH, "MEDIUM": Urgency.MEDIUM}.get(s, Urgency.LOW)


def _trigger_to_verb(t: AlertTrigger | str) -> ActionVerb:
    tv = t.value if isinstance(t, AlertTrigger) else t
    return {
        "LOSS_DEEP": ActionVerb.REDUCE,
        "LOSS_EXPANDING": ActionVerb.REDUCE,
        "CONCENTRATION_HIGH": ActionVerb.REDUCE,
        "TOP3_CONCENTRATION": ActionVerb.REDUCE,
        "OVERLAP_DUPLICATE": ActionVerb.REDUCE,
        "PROFIT_TAKE": ActionVerb.REDUCE,
    }.get(tv, ActionVerb.WATCH)


class GuardianAgent:
    def __init__(
        self,
        db: AsyncSession,
        slot: BriefingSlot | str = BriefingSlot.MIDDAY,
        *,
        agent_role: str = "guardian",
    ):
        self._db = db
        self.slot = slot if isinstance(slot, BriefingSlot) else BriefingSlot(slot)
        self.agent_role = agent_role
        self.session_id = _new_session_id(self.slot)
        # We borrow InvestmentAgent's tool methods for portfolio/market fetch.
        self._toolbox = InvestmentAgent(
            db, session_id=self.session_id, agent_role=self.agent_role,
        )
        self._checker = HoldingHealthChecker()

    # ── Entry point ────────────────────────────────────────────────────

    async def run(self) -> BriefingResult:
        result = BriefingResult(session_id=self.session_id, slot=self.slot)
        bus = EvidenceBus(self._db, self.session_id, agent=self.agent_role)
        store = DecisionCardStore(self._db)

        # Step 1: fetch snapshots + write evidence
        try:
            portfolio_json = await self._toolbox._tool_portfolio_summary()
        except Exception as e:
            logger.exception("Guardian portfolio fetch failed")
            result.error = f"portfolio: {e}"
            await self._save_run(result, error=result.error)
            return result

        market_json = await self._toolbox._tool_market_overview()
        ev_portfolio = await bus.store(
            source="get_portfolio_summary", query={}, data=portfolio_json, ttl_seconds=300,
            summary="持仓快照(Guardian)",
        )
        ev_market = await bus.store(
            source="get_market_overview", query={}, data=market_json, ttl_seconds=60,
            summary="市场快照(Guardian)",
        )

        portfolio = self._safe_json(portfolio_json)
        market = self._safe_json(market_json)

        result.portfolio_snapshot = {
            "total_value": portfolio.get("total_value"),
            "total_pnl": portfolio.get("total_pnl"),
            "total_pnl_pct": portfolio.get("total_pnl_pct"),
            "position_count": portfolio.get("position_count"),
        }
        result.market_snapshot = {
            "sentiment": market.get("sentiment"),
            "top_inflow_sectors": market.get("top_inflow_sectors"),
        }

        # Step 2: rule-based alerts
        holdings = portfolio.get("holdings") or []
        alerts = self._checker.detect_alerts(holdings)
        result.alerts = alerts

        # Step 3: LLM briefing (single call, JSON-structured)
        llm_output = None
        try:
            llm_output = await self._llm_briefing(
                portfolio=portfolio, market=market, alerts=alerts,
                evidence_map={"portfolio": ev_portfolio.ev_id, "market": ev_market.ev_id},
            )
            result.llm_used = True
        except LLMError as e:
            logger.warning("Guardian LLM briefing failed, using rule fallback: %s", e)
            result.error = f"llm: {e}"
        except Exception as e:
            logger.exception("Guardian LLM briefing crashed")
            result.error = f"llm-exc: {e}"

        briefing_text: str
        portfolio_card: Optional[DecisionCard]
        if llm_output is not None:
            briefing_text, portfolio_card = self._build_from_llm_json(
                llm_output=llm_output,
                portfolio=portfolio,
                evidence_map={"portfolio": ev_portfolio.ev_id, "market": ev_market.ev_id},
            )
        else:
            briefing_text = self._fallback_briefing_text(portfolio, market, alerts)
            portfolio_card = self._fallback_portfolio_card(
                portfolio=portfolio, alerts=alerts,
                evidence_ref=ev_portfolio.ev_id,
            )

        result.briefing_text = briefing_text

        # Save the portfolio-level card
        if portfolio_card is not None:
            try:
                await store.save(portfolio_card, session_id=self.session_id)
                result.decision_ids.append(portfolio_card.decision_id)
            except Exception as e:
                logger.error("Guardian save portfolio card failed: %s", e)

        # Step 4: one card per holding alert (SELL_ALERT/WATCH)
        for alert in alerts:
            card = self._alert_to_card(alert, evidence_ref=ev_portfolio.ev_id)
            try:
                await store.save(card, session_id=self.session_id)
                result.decision_ids.append(card.decision_id)
            except Exception as e:
                logger.error("Guardian save alert card failed: %s", e)

        # Step 5: push to Feishu (best-effort — never block the run)
        if settings.guardian_push_enabled and feishu_bot.configured:
            try:
                pushed = await feishu_bot.send_guardian_briefing(result)
                result.pushed_to_feishu = bool(pushed)
            except Exception as e:
                logger.warning("Guardian Feishu push failed: %s", e)
                result.pushed_to_feishu = False

        # Step 6: persist the run row
        result.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        await self._save_run(result)
        return result

    # ── LLM step ──────────────────────────────────────────────────────

    async def _llm_briefing(
        self,
        *,
        portfolio: dict,
        market: dict,
        alerts: list[HoldingAlert],
        evidence_map: dict[str, str],
    ) -> dict:
        client = get_llm_client("guardian")
        alerts_payload = [a.model_dump(mode="json") for a in alerts]

        user_prompt = (
            f"体检时段: {_slot_label(self.slot)} ({self.slot.value if isinstance(self.slot, BriefingSlot) else self.slot})\n\n"
            f"evidence_id 映射:\n"
            f"- 持仓快照 → {evidence_map['portfolio']}\n"
            f"- 市场快照 → {evidence_map['market']}\n\n"
            f"持仓数据:\n{json.dumps(portfolio, ensure_ascii=False)}\n\n"
            f"市场数据:\n{json.dumps(market, ensure_ascii=False)}\n\n"
            f"规则预警:\n{json.dumps(alerts_payload, ensure_ascii=False)}\n\n"
            f"输出 JSON,严格按照 system prompt 的 schema。"
        )
        resp = await client.chat(
            [Message.user(user_prompt)],
            system=GUARDIAN_SYSTEM_PROMPT,
            temperature=0.2,
            max_tokens=1500,
        )
        text = (resp.text or "").strip()
        return self._extract_json(text)

    def _build_from_llm_json(
        self,
        *,
        llm_output: dict,
        portfolio: dict,
        evidence_map: dict[str, str],
    ) -> tuple[str, Optional[DecisionCard]]:
        briefing_text = str(llm_output.get("briefing_text", "")).strip()
        pc = llm_output.get("portfolio_card") or {}

        dims_in = pc.get("dimensions") or []
        dimensions: list[Dimension] = []
        for d in dims_in:
            key = d.get("key")
            if key not in {"technical", "capital", "macro", "news", "financial", "consensus"}:
                continue
            try:
                dimensions.append(Dimension(
                    key=DimensionKey(key),
                    score=float(d.get("score", 0)),
                    signal=str(d.get("signal") or "n/a"),
                    evidence_ref=d.get("evidence_ref") or evidence_map["portfolio"],
                ))
            except Exception:
                continue

        try:
            verb = ActionVerb(pc.get("action_verb", "WATCH"))
        except ValueError:
            verb = ActionVerb.WATCH
        try:
            urgency = Urgency(pc.get("urgency", "MEDIUM"))
        except ValueError:
            urgency = Urgency.MEDIUM
        try:
            role = PortfolioRole(pc.get("portfolio_role", "NEW"))
        except ValueError:
            role = PortfolioRole.NEW

        card = DecisionCard(
            decision_id=self._new_decision_id("brief"),
            agent=self.agent_role,
            session_id=self.session_id,
            type=DecisionType.WATCH,
            target=Target(kind=TargetKind.PORTFOLIO, name="用户整体组合"),
            action=Action(verb=verb, confidence=float(pc.get("confidence", 0.5)), urgency=urgency),
            headline=str(pc.get("headline") or f"{_slot_label(self.slot)}体检"),
            summary=str(pc.get("summary") or briefing_text[:200]),
            dimensions=dimensions,
            portfolio_context=PortfolioContext(
                role=role,
                warning=pc.get("portfolio_warning"),
            ),
            monitoring=[str(x) for x in (pc.get("monitoring") or []) if x],
            evidence_refs=list(dict.fromkeys(
                [evidence_map["portfolio"], evidence_map["market"]] +
                [d.evidence_ref for d in dimensions if d.evidence_ref]
            )),
        )
        return briefing_text or (card.summary or ""), card

    # ── Helpers used by fallback + alert emission ────────────────────

    # ── Rule-only fallback ────────────────────────────────────────────

    def _fallback_briefing_text(
        self, portfolio: dict, market: dict, alerts: list[HoldingAlert],
    ) -> str:
        header = f"{_slot_label(self.slot)}体检"
        total = portfolio.get("total_value", 0)
        pnl_pct = portfolio.get("total_pnl_pct", 0)
        count = portfolio.get("position_count", 0)

        lines = [
            f"{header} | 总市值 ¥{total:,.0f} · 累计 {pnl_pct:+.2f}% · {count} 只",
        ]
        if not alerts:
            lines.append("组合无触发预警,持仓结构平稳。")
        else:
            lines.append(f"发现 {len(alerts)} 条预警:")
            for a in alerts[:5]:
                lines.append(f"- {a.one_line()}")
            if len(alerts) > 5:
                lines.append(f"...(还有 {len(alerts) - 5} 条,详见前端)")
        lines.append("仅供参考,不构成投资建议。")
        return "\n".join(lines)

    def _fallback_portfolio_card(
        self, portfolio: dict, alerts: list[HoldingAlert], evidence_ref: str,
    ) -> DecisionCard:
        high_alerts = [a for a in alerts if (a.severity == AlertSeverity.HIGH.value or a.severity == "HIGH")]
        verb = ActionVerb.REDUCE if high_alerts else (
            ActionVerb.WATCH if alerts else ActionVerb.HOLD
        )
        urgency = Urgency.HIGH if high_alerts else (
            Urgency.MEDIUM if alerts else Urgency.LOW
        )
        return DecisionCard(
            decision_id=self._new_decision_id("brief"),
            agent=self.agent_role,
            session_id=self.session_id,
            type=DecisionType.WATCH,
            target=Target(kind=TargetKind.PORTFOLIO, name="用户整体组合"),
            action=Action(verb=verb, confidence=0.55, urgency=urgency),
            headline=f"{_slot_label(self.slot)}体检:{'高优先级预警' if high_alerts else '规则触发预警' if alerts else '组合平稳'}",
            summary=self._fallback_briefing_text(portfolio, {}, alerts),
            dimensions=[],
            portfolio_context=PortfolioContext(
                role=PortfolioRole.STRENGTHEN if alerts else PortfolioRole.NEW,
                warning=("触发多条持仓集中/亏损预警" if alerts else None),
            ),
            evidence_refs=[evidence_ref],
        )

    def _alert_to_card(self, alert: HoldingAlert, evidence_ref: str) -> DecisionCard:
        # Enum-values-mode on the model returns .value; be defensive.
        sev = alert.severity if isinstance(alert.severity, str) else alert.severity.value
        trig = alert.trigger if isinstance(alert.trigger, str) else alert.trigger.value

        if sev == "HIGH":
            dtype = DecisionType.SELL_ALERT
            confidence = 0.7
        elif sev == "MEDIUM":
            dtype = DecisionType.WATCH
            confidence = 0.55
        else:
            dtype = DecisionType.WATCH
            confidence = 0.4

        return DecisionCard(
            decision_id=self._new_decision_id("alert", alert.code, trig),
            agent=self.agent_role,
            session_id=self.session_id,
            type=dtype,
            target=Target(kind=TargetKind.FUND, code=alert.code, name=alert.name),
            action=Action(
                verb=_trigger_to_verb(trig),
                confidence=confidence,
                urgency=_severity_to_urgency(sev),
            ),
            headline=f"[{sev}] {alert.name} — {trig}",
            summary=alert.note,
            dimensions=[],
            portfolio_context=PortfolioContext(role=PortfolioRole.STRENGTHEN),
            evidence_refs=[evidence_ref],
        )

    # ── Persistence ───────────────────────────────────────────────────

    async def _save_run(self, result: BriefingResult, error: Optional[str] = None) -> None:
        row = GuardianRunRow(
            session_id=result.session_id,
            slot=self.slot.value if isinstance(self.slot, BriefingSlot) else str(self.slot),
            started_at=self._parse_iso(result.started_at),
            finished_at=self._parse_iso(result.finished_at) if result.finished_at else None,
            alert_count=len(result.alerts),
            decision_count=len(result.decision_ids),
            llm_used=result.llm_used,
            pushed_to_feishu=result.pushed_to_feishu,
            result_json=result.model_dump_json(),
            error=(error or result.error or None),
        )
        # Upsert: same session_id => update, since scan is idempotent per slot.
        stmt = select(GuardianRunRow).where(GuardianRunRow.session_id == result.session_id)
        existing = (await self._db.execute(stmt)).scalar_one_or_none()
        if existing is None:
            self._db.add(row)
        else:
            existing.slot = row.slot
            existing.started_at = row.started_at
            existing.finished_at = row.finished_at
            existing.alert_count = row.alert_count
            existing.decision_count = row.decision_count
            existing.llm_used = row.llm_used
            existing.pushed_to_feishu = row.pushed_to_feishu
            existing.result_json = row.result_json
            existing.error = row.error
        try:
            await self._db.flush()
        except Exception as e:
            logger.warning("Guardian save_run flush failed: %s", e)

    async def latest_runs(self, limit: int = 10) -> list[GuardianRunRow]:
        stmt = (
            select(GuardianRunRow)
            .order_by(desc(GuardianRunRow.started_at), desc(GuardianRunRow.id))
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    # ── Small helpers ─────────────────────────────────────────────────

    @staticmethod
    def _parse_iso(s: Optional[str]) -> Optional[datetime]:
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _safe_json(text: str) -> dict:
        try:
            value = json.loads(text or "{}")
            return value if isinstance(value, dict) else {"value": value}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Pull the first {...} object out of the model output.

        Some models wrap JSON in ```json fences even when told not to; strip
        those first, then find the outermost braces.
        """
        clean = text.strip()
        # strip ```json ... ``` or ``` ... ``` wrapping if present
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", clean, re.DOTALL)
        if fence:
            clean = fence.group(1).strip()
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            pass
        # Fall back to the outermost balanced-brace substring.
        start = clean.find("{")
        end = clean.rfind("}")
        if start >= 0 and end > start:
            snippet = clean[start:end + 1]
            try:
                return json.loads(snippet)
            except json.JSONDecodeError as e:
                raise LLMError(f"Guardian LLM returned unparseable JSON: {e}", provider="guardian") from e
        raise LLMError("Guardian LLM produced no JSON object", provider="guardian")

    def _new_decision_id(self, kind: str, *tags: str) -> str:
        """Deterministic id so re-runs upsert the same row.

        Guardian is idempotent per (session_id, kind, target, trigger):
        the briefing has one id per session; each alert has one id per
        (session, code, trigger). A re-run in the same slot updates the
        existing card instead of stacking duplicates.
        """
        # Session id already encodes date + slot; tags encode the specific
        # target so re-runs don't collide with each other but DO collide
        # with themselves.
        suffix = "_".join(t for t in tags if t) if tags else "main"
        # Cap length so we stay under the schema's String(48).
        return f"dec_{kind}_{self.session_id.replace('guardian_', '')}_{suffix}"[:48]
