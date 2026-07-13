"""Small agent modules for sector monitoring evidence and decisions.

The split is intentional: data agents normalize skill output, while the
decision agent only reads normalized evidence unless a caller explicitly asks
for more data elsewhere.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any


SKILL_ROOT = Path.home() / ".openclaw" / "workspace" / "skills"


SKILL_CLI_BY_NAME = {
    "hithink-market-query": SKILL_ROOT / "hithink-market-query" / "scripts" / "cli.py",
    "hithink-zhishu-query": SKILL_ROOT / "hithink-zhishu-query" / "scripts" / "cli.py",
    "hithink-sector-selector": SKILL_ROOT / "hithink-sector-selector" / "scripts" / "cli.py",
    "hithink-industry-query": SKILL_ROOT / "hithink-industry-query" / "scripts" / "cli.py",
    "news-search": SKILL_ROOT / "news-search" / "scripts" / "news_search.py",
    "report-search": SKILL_ROOT / "report-search" / "scripts" / "report_search.py",
}


def _load_iwencai_env() -> dict[str, str]:
    env = os.environ.copy()
    if env.get("IWENCAI_API_KEY"):
        return env

    profiles = (
        Path.home() / ".zshrc",
        Path.home() / ".zprofile",
        Path.home() / ".bash_profile",
        Path.home() / ".profile",
    )
    for profile in profiles:
        if not profile.exists():
            continue
        for line in profile.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line.startswith("export IWENCAI_") or "=" not in line:
                continue
            key, value = line.removeprefix("export ").split("=", 1)
            env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env


async def run_iwencai_skill(skill_name: str, query: str, limit: int = 10, timeout: int = 30) -> dict[str, Any]:
    """Run one official Iwencai SkillHub CLI and return parsed JSON.

    This is deliberately one skill per call. Callers should split broad
    questions into focused queries so the returned rows stay reliable.
    """
    cli = SKILL_CLI_BY_NAME.get(skill_name)
    if not cli or not cli.exists():
        return {}

    env = _load_iwencai_env()
    if not env.get("IWENCAI_API_KEY"):
        return {}

    try:
        if skill_name in {"news-search", "report-search"}:
            args = ["python3", str(cli), query, "--size", str(limit), "--timeout", str(timeout)]
        else:
            args = [
                "python3",
                str(cli),
                "--query",
                query,
                "--limit",
                str(limit),
                "--timeout",
                str(timeout),
            ]
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 5)
    except Exception:
        return {}

    if proc.returncode != 0:
        return {}

    try:
        data = json.loads(stdout.decode("utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    if data.get("success") or data.get("status_code") == 0:
        return data
    return {}


def _first_numeric(row: dict[str, Any], *fragments: str) -> float | None:
    for key, value in row.items():
        if all(fragment in key for fragment in fragments):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def _amount_yi(value: float | None) -> str:
    if value is None or value <= 0:
        return "暂无"
    return f"{value / 1e8:.0f}亿"


def build_market_mood_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize market breadth and turnover into one user-facing diagnosis."""
    turnover = _first_numeric(row, "成交额[202")
    previous_turnover = _first_numeric(row, "昨日成交额") or _first_numeric(row, "成交额[20260629]")
    turnover_change = None
    if turnover is not None and previous_turnover:
        turnover_change = round((turnover - previous_turnover) / previous_turnover * 100, 2)

    up_count = _first_numeric(row, "上涨家数") or 0
    down_count = _first_numeric(row, "下跌家数") or 0
    limit_up = _first_numeric(row, "涨停家数") or 0
    limit_down = _first_numeric(row, "跌停家数") or 0
    index_pct = _first_numeric(row, "最新涨跌幅") or _first_numeric(row, "涨跌幅") or 0

    if turnover_change is not None and turnover_change >= 3 and up_count >= down_count:
        state = "放量进攻"
    elif turnover_change is not None and turnover_change < 0 and up_count >= down_count:
        state = "缩量修复"
    elif turnover_change is not None and turnover_change >= 3 and up_count < down_count:
        state = "放量分歧"
    elif turnover_change is not None and turnover_change < 0 and up_count < down_count:
        state = "缩量退潮"
    else:
        state = "震荡观察"

    volume_word = "放量" if turnover_change is not None and turnover_change >= 0 else "缩量"
    change_text = f"较昨日{volume_word}{abs(turnover_change):.2f}%" if turnover_change is not None else "较昨日量能暂无"
    summary = (
        f"{state}：全A成交额{_amount_yi(turnover)}，{change_text}；"
        f"上涨{up_count:.0f}/下跌{down_count:.0f}，涨停{limit_up:.0f}/跌停{limit_down:.0f}。"
    )

    return {
        "state": state,
        "turnover": turnover,
        "previous_turnover": previous_turnover,
        "turnover_change_pct": turnover_change,
        "up_count": int(up_count),
        "down_count": int(down_count),
        "limit_up": int(limit_up),
        "limit_down": int(limit_down),
        "index_pct": index_pct,
        "summary": summary,
        "source_skill": "hithink-market-query",
    }


async def fetch_market_mood_snapshot() -> dict[str, Any]:
    """Fetch the main market mood snapshot from Iwencai."""
    result = await run_iwencai_skill(
        "hithink-market-query",
        "今日A股总成交额、昨日A股总成交额、成交额环比增长率、上涨家数、下跌家数、涨停家数、跌停家数",
        limit=3,
    )
    rows = result.get("datas") or []
    if not rows:
        return {
            "state": "数据不足",
            "summary": "同花顺问财暂未返回全A成交额和情绪数据。",
            "source_skill": "hithink-market-query",
        }
    return build_market_mood_snapshot(rows[0])


def _flow_yi(value: float | None) -> str:
    if value is None:
        return "主力数据缺失"
    return f"主力净流入{value / 1e8:.1f}亿" if value >= 0 else f"主力净流出{abs(value) / 1e8:.1f}亿"


def decide_sector_opportunities(
    rows: list[dict[str, Any]],
    market_snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    """Decision agent: score normalized rows without performing new skill calls."""
    decisions: list[dict[str, Any]] = []
    market_state = str(market_snapshot.get("state") or "未知")

    for row in rows:
        change_pct = float(row.get("change_pct_value") or 0)
        raw_net_inflow = row.get("net_inflow")
        net_inflow = float(raw_net_inflow) if raw_net_inflow is not None else 0.0
        turnover = float(row.get("turnover") or 0)
        technical = str(row.get("technical") or "")
        score = change_pct + net_inflow / 1e10
        if "站上" in technical:
            score += 1.0
        if "跌破" in technical:
            score -= 1.5
        if market_state == "缩量退潮":
            score -= 1.0
        elif market_state == "放量进攻":
            score += 0.8

        if score >= 8:
            level = "强机会"
            action = "已有仓位可持有，新增只等回踩不破，不追急拉"
        elif score >= 4:
            level = "修复机会"
            action = "可观察低吸条件，等资金和均线确认"
        elif score >= 1:
            level = "观察"
            action = "只看不动，等信号更清楚"
        else:
            level = "回避"
            action = "不主动加仓，先等止跌或资金回流"

        one_liner = (
            f"{level}：{row.get('matched_sector') or row.get('name')} {change_pct:+.2f}%，"
            f"{_flow_yi(raw_net_inflow)}，成交额{_amount_yi(turnover)}；"
            f"大盘为{market_state}，{action}。"
        )
        detail_action = "有机会" if level in ("强机会", "修复机会") else "要观察" if level == "观察" else "要回避"
        decisions.append({
            **row,
            "opportunity_level": level,
            "opportunity": one_liner,
            "one_liner": one_liner,
            "action": action,
            "decision_score": round(score, 2),
            "detail_prompt": f"为什么{row.get('name')}{detail_action}？",
        })

    return sorted(decisions, key=lambda item: item["decision_score"], reverse=True)
