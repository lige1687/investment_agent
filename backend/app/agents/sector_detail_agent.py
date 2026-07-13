"""Explain one watched sector using saved evidence plus focused skill checks."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Awaitable, Callable

from app.agents.prompt_registry import PromptRegistry
from app.services.agent_context_service import ContextSnapshot
from app.services.sector_monitor_agents import run_iwencai_skill

SkillRunner = Callable[[str, str, int, int], Awaitable[dict[str, Any]]]


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
            terms.add(canonical)
            terms.update(words)
    return terms


def _sector_match_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(key, ""))
        for key in ("name", "matched_sector", "tracking_code", "data_code", "source_code")
    ).lower()


def _fmt_pct(value: Any) -> str:
    try:
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return "涨跌幅暂无"


def _fmt_yi(value: Any) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "暂无"
    if amount <= 0:
        return "暂无"
    return f"{amount / 1e8:.0f}亿"


def _trim_sentence_end(text: str) -> str:
    return text.rstrip("。；;，, ")


def _first_field(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    extra = row.get("extra")
    if isinstance(extra, dict):
        for name in names:
            if name in extra and extra[name] not in (None, ""):
                return extra[name]
        aliases = {
            "来源": ("real_publish_source", "publish_source", "organization"),
            "机构": ("organization", "publish_source", "real_publish_source"),
            "source": ("real_publish_source", "publish_source", "organization"),
            "orgName": ("organization",),
            "publishOrg": ("organization",),
        }
        for name in names:
            for alias in aliases.get(name, ()):
                if extra.get(alias) not in (None, ""):
                    return extra[alias]
    for key, value in row.items():
        if any(name in key for name in names) and value not in (None, ""):
            return value
    return None


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    candidates = [
        payload.get("datas"),
        payload.get("data"),
        payload.get("result"),
        payload.get("results"),
        payload.get("items"),
    ]
    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
        if isinstance(candidate, dict):
            nested = _extract_rows(candidate)
            if nested:
                return nested
    return []


def _format_source_rows(rows: list[dict[str, Any]], *, source_type: str) -> list[str]:
    formatted: list[str] = []
    for row in rows[:2]:
        title = _first_field(row, "标题", "title", "reportTitle", "newsTitle") or "未命名"
        if source_type == "研报":
            source = _first_field(row, "机构", "organization", "orgName", "publishOrg", "来源", "source") or "来源未标明"
        else:
            source = _first_field(row, "来源", "source", "机构", "organization", "orgName", "publishOrg") or "来源未标明"
        date = _first_field(
            row,
            "发布时间",
            "发布日期",
            "publish_date",
            "publishDate",
            "publishTime",
            "publish_time",
            "time",
        ) or "日期未标明"
        if isinstance(date, int | float):
            date = datetime.fromtimestamp(float(date)).strftime("%Y-%m-%d")
        url = _first_field(row, "链接", "url", "link", "jumpUrl")
        url_text = str(url) if url else "链接缺失"
        formatted.append(f"- {source_type}｜{title}｜{source}｜{date}｜{url_text}")
    return formatted


class SectorDetailAgent:
    def __init__(
        self,
        *,
        run_skill: SkillRunner = run_iwencai_skill,
        prompt_registry: PromptRegistry | None = None,
    ):
        self._run_skill = run_skill
        self._prompt_registry = prompt_registry or PromptRegistry()

    def _find_sector(self, question: str, snapshot: ContextSnapshot) -> dict[str, Any] | None:
        evidence = snapshot.context.get("sector_evidence") or []
        terms = _question_terms(question)
        if terms:
            for item in evidence:
                text = _sector_match_text(item)
                if any(term.lower() in text for term in terms):
                    return item
        return evidence[0] if evidence else None

    async def _fetch_extra_evidence(self, sector: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        name = sector.get("matched_sector") or sector.get("name") or ""
        tracking_code = sector.get("tracking_code") or sector.get("data_code") or ""
        calls = [
            ("hithink-industry-query", f"{name} 今日涨跌幅、成交额、主力资金净流入、行业排名"),
            ("hithink-zhishu-query", f"{tracking_code} {name} 今日涨跌幅、成交额、K线趋势"),
            ("news-search", f"{name} 半导体设备 国产替代 最新新闻 政策 产业链"),
            ("report-search", f"{name} 半导体设备 行业研报 投资逻辑 资本开支"),
        ]
        extra: dict[str, Any] = {}
        used: list[str] = []
        for skill, query in calls:
            result = await self._run_skill(skill, query, 8, 30)
            used.append(skill)
            extra[skill] = {
                "query": query,
                "rows": _extract_rows(result)[:3],
            }
        return extra, used

    async def explain(self, *, question: str, snapshot: ContextSnapshot | None) -> dict[str, Any]:
        if snapshot is None:
            return {
                "intent": "sector_detail",
                "answer": "结论：我还没有上一张版块卡片的证据快照，暂时不能解释这个机会来源。请先生成一次版块监控卡片。仅供参考，不构成投资建议。",
                "used_skills": [],
                "fallback": True,
            }

        sector = self._find_sector(question, snapshot)
        if not sector:
            return {
                "intent": "sector_detail",
                "answer": "结论：最近快照里没有找到对应版块证据，不能硬解释机会。请先确认关注版块或重新生成监控卡片。仅供参考，不构成投资建议。",
                "used_skills": [],
                "fallback": True,
            }

        extra, used_skills = await self._fetch_extra_evidence(sector)
        market = snapshot.context.get("market_mood") or {}
        tracking_code = sector.get("tracking_code") or "-"
        data_code = sector.get("data_code") or sector.get("source_code") or "-"
        main_flow = sector.get("main_flow", sector.get("net_inflow"))
        flow_text = "主力数据缺失" if main_flow is None else f"主力资金 {main_flow}"
        turnover_text = _fmt_yi(sector.get("turnover"))
        code_note = (
            f"跟踪代码和数据代码一致，都是 {tracking_code}。"
            if tracking_code == data_code
            else f"跟踪代码是 {tracking_code}，本次实际数据代码是 {data_code}，需要留意口径差异。"
        )
        level = sector.get("opportunity_level") or "观察"
        action = "只适合观察，不是追涨机会"
        if str(level) in {"强机会", "修复机会"}:
            action = "有观察价值，但不是追涨机会，仍应等回踩和量能确认"
        elif str(level) == "回避":
            action = "当前更偏风险，先等止跌和资金回流"

        context_json = json.dumps({
            "question": question,
            "sector": sector,
            "market": market,
            "extra_skill_evidence": extra,
        }, ensure_ascii=False, separators=(",", ":"))
        prompt = self._prompt_registry.get("sector_detail")
        source_lines = []
        source_lines.extend(_format_source_rows(extra.get("news-search", {}).get("rows", []), source_type="新闻"))
        source_lines.extend(_format_source_rows(extra.get("report-search", {}).get("rows", []), source_type="研报"))
        if not source_lines:
            source_lines.append("- 新闻/研报｜本次 skill 未返回可核验来源｜来源缺失｜日期缺失｜链接缺失")
        source_text = "\n".join(source_lines)

        market_text = _trim_sentence_end(str(market.get("summary") or market.get("state") or "大盘情绪暂无"))
        answer = (
            f"结论：{sector.get('name')}当前是“{level}”，{action}。\n\n"
            f"1. 大盘环境：{market_text}，这决定了它更适合做观察确认，而不是直接放大仓位。\n"
            f"2. 版块证据：{sector.get('matched_sector')} 今日 {_fmt_pct(sector.get('change_pct'))}，成交额 {turnover_text}，{flow_text}；{code_note}\n"
            f"3. 技术/量能：{sector.get('technical') or '技术信号暂无'}；{sector.get('volume') or '量能信号暂无'}。如果后续回踩 5 日线不破、量能不明显萎缩，机会质量才会提高。\n"
            f"4. 权威信息源：\n{source_text}\n"
            f"5. 持仓影响：主要影响 {sector.get('related_holdings') or '相关持仓暂无'}。如果这个方向只是单日拉升但资金字段缺失，就不要把它理解成确定买点。\n\n"
            f"下一步：继续看同花顺 skill 返回的成交额、主力资金和指数口径是否连续确认；若数据仍缺失，只把它放进观察榜。仅供参考，不构成投资建议。"
        )
        return {
            "intent": "sector_detail",
            "sector": {
                "name": sector.get("name"),
                "matched_sector": sector.get("matched_sector"),
                "tracking_code": tracking_code,
                "data_code": data_code,
            },
            "answer": answer,
            "used_skills": used_skills,
            "extra_evidence": extra,
            "prompt_meta": {
                "name": prompt.name,
                "version": prompt.version,
                "template": prompt.content,
                "context_json": context_json,
            },
            "fallback": False,
        }
