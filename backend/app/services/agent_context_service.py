"""Context snapshot storage and retrieval for Agent follow-up questions."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_context import AgentContextSnapshot


@dataclass(frozen=True)
class ContextSnapshot:
    id: int
    source: str
    intent: str
    question: str
    context: dict[str, Any]
    decision: dict[str, Any]
    skill_calls: list[dict[str, Any]]


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads_dict(value: str) -> dict[str, Any]:
    data = json.loads(value or "{}")
    return data if isinstance(data, dict) else {}


def _json_loads_list(value: str) -> list[dict[str, Any]]:
    data = json.loads(value or "[]")
    return data if isinstance(data, list) else []


def _snapshot_to_dto(row: AgentContextSnapshot) -> ContextSnapshot:
    return ContextSnapshot(
        id=row.id,
        source=row.source,
        intent=row.intent,
        question=row.question or "",
        context=_json_loads_dict(row.context_json),
        decision=_json_loads_dict(row.decision_json),
        skill_calls=_json_loads_list(row.skill_calls_json),
    )


def _question_terms(question: str) -> set[str]:
    aliases = {
        "半导体": {"半导体", "芯片", "集成电路"},
        "通信": {"通信", "光模块", "cpo", "算力"},
        "有色": {"有色", "金属", "黄金"},
        "电池": {"电池", "锂电", "新能源"},
        "消费": {"消费", "食品饮料", "白酒"},
        "港股": {"港股", "恒生", "互联网"},
        "美股": {"美股", "纳斯达克", "纳指", "标普"},
    }
    lowered = question.lower()
    terms: set[str] = set()
    for canonical, words in aliases.items():
        if any(word.lower() in lowered for word in words):
            terms.update(words)
            terms.add(canonical)
    for raw in question.replace("？", " ").replace("?", " ").split():
        if raw.strip():
            terms.add(raw.strip())
    return terms


def _sector_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(key, ""))
        for key in ("name", "matched_sector", "tracking_code", "data_code", "source_code")
    ).lower()


class AgentContextService:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def save_snapshot(
        self,
        *,
        source: str,
        intent: str,
        question: str = "",
        context: dict[str, Any],
        decision: dict[str, Any] | None = None,
        skill_calls: list[dict[str, Any]] | None = None,
    ) -> int:
        row = AgentContextSnapshot(
            source=source,
            intent=intent,
            question=question,
            context_json=_json_dumps(context),
            decision_json=_json_dumps(decision or {}),
            skill_calls_json=_json_dumps(skill_calls or []),
        )
        self._db.add(row)
        await self._db.flush()
        return row.id

    async def find_recent_relevant_snapshot(self, question: str, limit: int = 10) -> ContextSnapshot | None:
        result = await self._db.execute(
            select(AgentContextSnapshot)
            .order_by(desc(AgentContextSnapshot.created_at), desc(AgentContextSnapshot.id))
            .limit(limit)
        )
        snapshots = [_snapshot_to_dto(row) for row in result.scalars().all()]
        if not snapshots:
            return None

        terms = _question_terms(question)
        if not terms:
            return snapshots[0]

        for snapshot in snapshots:
            evidence = snapshot.context.get("sector_evidence") or []
            if any(any(term.lower() in _sector_text(item) for term in terms) for item in evidence):
                return snapshot
        return snapshots[0]

    async def build_recent_context_block(self, question: str) -> str:
        snapshot = await self.find_recent_relevant_snapshot(question)
        if not snapshot:
            return ""

        context = snapshot.context
        market = context.get("market_mood") or {}
        evidence = context.get("sector_evidence") or []
        lines = [
            "## 最近证据快照",
            f"- 来源：{snapshot.source} / {snapshot.intent} / #{snapshot.id}",
        ]
        market_summary = market.get("summary") or market.get("state")
        if market_summary:
            lines.append(f"- 大盘：{market_summary}")
        if snapshot.decision.get("summary"):
            lines.append(f"- 上次结论：{snapshot.decision['summary']}")

        for item in evidence[:6]:
            main_flow = item.get("main_flow", item.get("net_inflow"))
            flow_text = "主力数据缺失" if main_flow is None else f"主力 {main_flow}"
            tracking = item.get("tracking_code") or item.get("source_code") or "-"
            data_code = item.get("data_code") or item.get("source_code") or "-"
            lines.append(
                f"- {item.get('name')}：{item.get('matched_sector', '-')}"
                f"，涨跌 {item.get('change_pct', item.get('change_pct_value', '-'))}"
                f"，跟踪代码 {tracking}，数据代码 {data_code}，{flow_text}"
            )

        skills = [str(item.get("skill") or item.get("source_skill") or "") for item in snapshot.skill_calls]
        skills = [item for item in skills if item]
        if skills:
            lines.append("- 已用 skill：" + " / ".join(skills[:6]))
        lines.append("使用这份快照回答追问；如果数据代码与跟踪代码不同，必须明确说明。")
        return "\n".join(lines)
