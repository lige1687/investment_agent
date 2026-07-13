"""Feishu interactive card builders.

The card format intentionally keeps content short and decision-oriented for
mobile reading: conclusion first, compact tables, then actions.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def _md(text: str) -> dict[str, Any]:
    return {"tag": "lark_md", "content": text}


def _note(text: str) -> dict[str, Any]:
    return {"tag": "note", "elements": [_md(text)]}


def _hr() -> dict[str, str]:
    return {"tag": "hr"}


def _field(label: str, value: str, *, short: bool = True) -> dict[str, Any]:
    return {
        "is_short": short,
        "text": _md(f"**{label}**\n{value}"),
    }


def _fields(fields: list[dict[str, Any]]) -> dict[str, Any]:
    return {"tag": "div", "fields": fields}


def _truncate(items: list[Any], limit: int) -> list[Any]:
    return items[:limit] if items else []


def _watch_row_text(row: dict[str, Any]) -> str:
    status = row.get("status", "观察")
    source_code = row.get("source_code", row.get("matched_sector", "-"))
    tracking_code = row.get("tracking_code")
    if tracking_code and tracking_code != source_code:
        source_text = f"跟踪：{tracking_code}｜数据：{source_code}"
    else:
        source_text = f"源代码：{source_code}"
    return (
        f"**[{status}] {row.get('name', '-')}**  {row.get('change_pct', '-')}  "
        f"{row.get('bar', '')}  {row.get('flow', '-')}\n"
        f"参考：{row.get('matched_sector', '-')}｜{source_text}"
    )


def build_sector_summary_card(
    *,
    title: str,
    conclusion: str,
    drivers: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    actions: list[str],
    watch_rows: list[dict[str, Any]] | None = None,
    tone: str = "blue",
    decision: str = "观察",
    risk_level: str = "中",
    skill_note: str = "",
    market_diagnosis: str = "",
    source_note: str = "",
) -> dict[str, Any]:
    """Build a compact sector summary card for Feishu.

    Args:
        title: Card title.
        conclusion: One-sentence decision.
        drivers: Up to 3 rows with name/value/judgement.
        holdings: Up to 4 rows with name/code/exposure/impact.
        actions: Up to 2 next-step observations.
        watch_rows: Focused sector rows with visual bars and ETF mapping.
        tone: Feishu header color template.
        decision: One short action label.
        risk_level: One short risk label.
        skill_note: Optional short diagnostic from SkillBridge.
        market_diagnosis: One market-wide diagnosis rendered once before sector details.
        source_note: Small footer about data source.
    """
    action_rows = _truncate(actions, 2)
    watch_rows = _truncate(watch_rows or [], 8)
    evidence_rows = [row for row in watch_rows if row.get("matched_sector") and row.get("matched_sector") != "暂无匹配"]
    opportunity_rows = _truncate(evidence_rows, 8)
    technical_rows = _truncate(evidence_rows, 8)

    elements: list[dict[str, Any]] = [
        {"tag": "div", "text": _md(f"**结论**\n{conclusion}")},
        _fields([
            _field("今日动作", decision),
            _field("风险等级", risk_level),
        ]),
        _hr(),
        {"tag": "div", "text": _md("**关注板块强弱**")},
    ]

    if market_diagnosis:
        elements.extend([
            {"tag": "div", "text": _md(f"**大盘诊断**\n{market_diagnosis}")},
            _hr(),
        ])

    if watch_rows:
        core_rows = [row for row in watch_rows if row.get("priority") == "core"]
        satellite_rows = [row for row in watch_rows if row.get("priority") != "core"]
        if core_rows:
            elements.append({"tag": "div", "text": _md("**核心监控**")})
            elements.append({"tag": "div", "text": _md("\n".join(_watch_row_text(row) for row in core_rows))})
        if satellite_rows:
            elements.append({"tag": "div", "text": _md("**扩展观察**")})
            elements.append({"tag": "div", "text": _md("\n".join(_watch_row_text(row) for row in satellite_rows))})
    else:
        elements.append({"tag": "div", "text": _md("暂无关注板块数据")})

    if skill_note:
        elements.append({"tag": "div", "text": _md(f"**财经Skill要点**\n{skill_note}")})

    opportunity_title = "机会榜" if any(row.get("opportunity_level") for row in opportunity_rows) else "机会评价"
    elements.extend([
        _hr(),
        {"tag": "div", "text": _md(f"**{opportunity_title}**")},
    ])

    if opportunity_rows:
        elements.append({"tag": "div", "text": _md("\n".join(
            (
                f"**{row.get('opportunity_level', row.get('status', '观察'))}｜{row.get('name', '-')}**\n"
                f"{row.get('opportunity', '等待信号更清楚')}\n"
                f"详情：@机器人 {row.get('detail_prompt', '为什么这个方向有机会？')}"
            )
            for row in opportunity_rows
        ))})
    else:
        elements.append({"tag": "div", "text": _md("暂无明确机会，先观察。")})

    elements.extend([_hr(), {"tag": "div", "text": _md("**技术面/量能**")}])
    if technical_rows:
        elements.append({"tag": "div", "text": _md("\n".join(
            f"**{row.get('name', '-')}**：{row.get('expert_analysis') or (str(row.get('technical', '-')) + '；' + str(row.get('volume', '-')))}"
            for row in technical_rows
        ))})
    else:
        elements.append({"tag": "div", "text": _md("暂无技术面数据。")})

    elements.extend([_hr(), {"tag": "div", "text": _md("**下一步**")}])
    elements.append({
        "tag": "div",
        "text": _md("\n".join(f"- {item}" for item in action_rows) or "- 暂无动作"),
    })

    if source_note:
        elements.append(_note(source_note))

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": tone,
            "title": {"tag": "plain_text", "content": title},
            "subtitle": {"tag": "plain_text", "content": datetime.now().strftime("%Y-%m-%d %H:%M")},
        },
        "elements": elements,
    }
