"""Local Feishu Q&A advice engine for portfolio-aware daily actions."""
from __future__ import annotations

import asyncio
from typing import Any

from app.services.sector_card_service import (
    _fetch_eastmoney_all_sectors,
    _load_focus_holdings,
    build_focus_watch_rows,
)
from app.skills.bridge import bridge


def _market_mood(watch_rows: list[dict[str, Any]]) -> str:
    core_rows = [row for row in watch_rows if row.get("priority") == "core"]
    strong = [row for row in core_rows if row.get("status") == "强"]
    weak = [row for row in core_rows if row.get("status") in {"弱", "流"}]
    if strong and weak:
        return "分化：有局部机会，但核心持仓方向没有全面转强。"
    if strong:
        return "偏强：核心方向有资金承接，可以观察回踩确认。"
    if len(weak) >= max(len(core_rows) - 1, 1):
        return "偏弱：核心方向多数走弱，先防守。"
    return "中性：资金方向不够连续，适合观察。"


def _overall_judgement(watch_rows: list[dict[str, Any]]) -> str:
    core_rows = [row for row in watch_rows if row.get("priority") == "core"]
    strong = [row for row in core_rows if row.get("status") == "强"]
    weak = [row for row in core_rows if row.get("status") in {"弱", "流"}]
    if strong and weak:
        names = "、".join(row["name"] for row in strong[:2])
        return f"今天是结构性机会，不是全面进攻；{names}可小仓观察，其余弱势方向先不补。"
    if strong:
        return "今天核心方向偏强，但仍以回踩确认后的低吸观察为主，不追涨。"
    if weak:
        return "今天以防守为主，核心持仓相关板块还没给出加仓信号。"
    return "今天只看不动，等资金方向更清楚。"


def _action_for_row(row: dict[str, Any]) -> str:
    status = row.get("status")
    technical = row.get("technical", "")
    volume = row.get("volume", "")
    if status == "强":
        return "小仓观察；只等回踩不破5日线或放量延续，不追分时急拉。"
    if status == "吸":
        return "观察低吸；先等价格站回短均线，资金继续流入再考虑。"
    if status == "弱":
        return "不补仓；等止跌、缩量或重新站回5日线。"
    if status == "流":
        return "先回避主动加仓；资金流出没收敛前只做跟踪。"
    if "主力净流出" in volume or "跌破" in technical:
        return "只观察；趋势和资金至少修复一个再说。"
    return "只看不动；等更明确的方向。"


def _format_row_advice(row: dict[str, Any]) -> str:
    return (
        f"**{row.get('name')}（{row.get('matched_sector')}）**\n"
        f"- 机会：{row.get('opportunity')}\n"
        f"- 技术：{row.get('technical')}；{row.get('volume')}\n"
        f"- 动作：{_action_for_row(row)}\n"
        f"- 原因：{row.get('change_pct')}，资金 {row.get('flow')}；影响持仓：{row.get('holding')}"
    )


def compose_portfolio_advice(
    *,
    message: str,
    watch_rows: list[dict[str, Any]],
    portfolio: dict[str, Any],
    skill_notes: list[str],
    recent_context: str = "",
) -> str:
    """Compose the local answer used by Feishu dev-ask and future @ replies."""
    matched_rows = [
        row for row in watch_rows
        if row.get("matched_sector") and row.get("matched_sector") != "暂无匹配"
    ]
    rows_source = matched_rows or ([] if recent_context else watch_rows)
    core_rows = [row for row in rows_source if row.get("priority") == "core"]
    rows = core_rows or rows_source
    rows = sorted(rows, key=lambda row: row.get("score", 0), reverse=True)

    lines = [
        f"**总判断**：{_overall_judgement(watch_rows)}",
        f"**大盘情绪**：{_market_mood(watch_rows)}",
    ]
    if portfolio:
        lines.append(
            f"**账户背景**：总市值约 ¥{portfolio.get('total_value', 0):,.0f}，累计盈亏 {portfolio.get('total_pnl_pct', 0):+.2f}%。"
        )
    if recent_context:
        lines.append(f"**最近证据**：\n{recent_context}")

    lines.append("\n**分板块建议**")
    if rows:
        for row in rows[:5]:
            lines.append(_format_row_advice(row))
    else:
        lines.append("最近问题优先看上方证据快照；当前实时兜底源没有拿到可审计的匹配行，先不输出伪实时分板块结论。")

    lines.append("\n**财经Skill要点**")
    if skill_notes:
        for note in skill_notes[:3]:
            lines.append(f"- {note}")
    elif recent_context:
        lines.append("- 暂未拿到新的可用skill结果，本次追问优先基于最近证据快照和你的持仓映射回答。")
    else:
        lines.append("- 暂未拿到可用skill结果，以上先基于实时板块、K线、量能和你的持仓映射生成。")

    lines.append("\n**今天动作清单**")
    if any(row.get("status") == "强" for row in rows):
        lines.append("- 强势方向只做“小仓观察”，等待回踩确认，不追涨。")
    if any(row.get("status") in {"弱", "流"} for row in rows):
        lines.append("- 弱势方向不补仓，等止跌、缩量或资金回流。")
    lines.append("- 14:35 前后再看一次量能和主力流向，决定是否继续观察到明天。")
    lines.append("\n仅供参考，不构成投资建议。")
    return "\n".join(lines)


async def _skill_note(skill_name: str, params: dict[str, Any]) -> str:
    try:
        result = await asyncio.wait_for(
            bridge.invoke_simple(skill_name, params=params, cache_ttl=600),
            timeout=10,
        )
    except Exception:
        return ""
    if not result.success or not result.data:
        return ""
    data = result.data
    if isinstance(data, dict):
        text = data.get("summary") or data.get("conclusion") or data.get("raw_output") or str(data)
    elif isinstance(data, list):
        text = str(data[:2])
    else:
        text = str(data)
    return text.replace("\n", " ").strip()[:140]


async def build_portfolio_advice_answer(
    message: str,
    use_skill: bool = True,
    recent_context: str = "",
) -> dict[str, Any]:
    """Build a local answer for Feishu @-style portfolio questions."""
    holdings = _load_focus_holdings()
    sectors = _fetch_eastmoney_all_sectors()
    watch_rows = build_focus_watch_rows(sectors, holdings, include_kline=True)

    total_value = sum((row.get("market_value") or 0) for row in holdings.values())
    total_cost = sum(
        (row.get("market_value") or 0) / (1 + (row.get("unrealized_pnl_pct") or 0) / 100)
        for row in holdings.values()
        if row.get("unrealized_pnl_pct") is not None and (1 + (row.get("unrealized_pnl_pct") or 0) / 100) != 0
    )
    portfolio = {
        "total_value": total_value,
        "total_pnl_pct": ((total_value - total_cost) / total_cost * 100) if total_cost else 0,
    }

    skill_notes: list[str] = []
    used_skills: list[str] = []
    if use_skill:
        skill_requests = [
            ("sentiment_analysis", {"focus": "A股市场情绪，结合涨跌家数、主线资金和风险偏好，输出一句中文结论"}),
            ("sector_rotation_analysis", {"sectors": [row["name"] for row in watch_rows], "focus": "行业轮动和持仓相关板块机会"}),
            ("sector_monitor", {"sectors": [row["name"] for row in watch_rows[:6]], "focus": "技术面、量能、机会和动作建议"}),
        ]
        for skill_name, params in skill_requests:
            note = await _skill_note(skill_name, params)
            if note:
                skill_notes.append(note)
                used_skills.append(skill_name)

    return {
        "answer": compose_portfolio_advice(
            message=message,
            watch_rows=watch_rows,
            portfolio=portfolio,
            skill_notes=skill_notes,
            recent_context=recent_context,
        ),
        "watch_rows": watch_rows,
        "used_skills": used_skills,
        "fallback": not bool(skill_notes),
    }
