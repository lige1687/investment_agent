"""Skill-backed Feishu market summary tasks."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from textwrap import dedent
from typing import Any

from app.database import async_session
from app.feishu.bot import feishu_bot
from app.services.market_data_provider import MarketDataProvider
from app.services.yangjibao_service import YangjibaoService
from app.tasks.scheduler import is_trading_day

logger = logging.getLogger(__name__)


SUMMARY_MIN_CHARS = 180


async def _run_claude_skill_summary(prompt: str, timeout_seconds: int = 180) -> str:
    """Run Claude CLI and explicitly ask it to use relevant THS SkillHub skills.

    The prompt itself names the skills that must be used. If Claude CLI or a
    skill is unavailable, the caller falls back to a local but clearly labelled
    summary instead of silently pretending a skill result exists.
    """
    proc = await asyncio.create_subprocess_exec(
        "claude",
        "-p",
        prompt,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"Claude CLI failed ({proc.returncode}): {err}")
    text = stdout.decode("utf-8", errors="replace").strip()
    if not text:
        raise RuntimeError("Claude CLI returned empty summary")
    return text


async def _portfolio_context() -> dict:
    """Load local Yangjibao portfolio with readable fund names."""
    try:
        async with async_session() as db:
            service = YangjibaoService(db)
            portfolio = await service.get_local_portfolio()
            positions = portfolio.get("positions", [])
            positions = sorted(positions, key=lambda p: p.get("market_value") or 0, reverse=True)
            return {
                "total_value": round(portfolio.get("total_value", 0), 2),
                "total_cost": round(portfolio.get("total_cost", 0), 2),
                "total_pnl": round(portfolio.get("total_pnl", 0), 2),
                "total_pnl_pct": round(portfolio.get("total_pnl_pct", 0), 2),
                "positions": [
                    {
                        "code": p.get("symbol"),
                        "name": p.get("name") or p.get("fund_name") or p.get("symbol"),
                        "market_value": round(p.get("market_value") or 0, 2),
                        "pnl_pct": round(p.get("unrealized_pnl_pct") or 0, 2),
                    }
                    for p in positions[:12]
                ],
            }
    except Exception as exc:
        logger.warning("Could not load portfolio context for skill summary: %s", exc)
        return {"error": str(exc), "positions": []}


async def _local_market_snapshot() -> dict:
    """Small local snapshot used only as extra context/fallback."""
    provider = MarketDataProvider()
    return {
        "indices": provider.get_global_indices(),
        "sentiment": provider.get_sentiment(),
        "capital_flow": provider.get_capital_flow(),
        "sector_rotation": provider.get_sector_rotation(),
    }


def _compact_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _top_positions_text(portfolio: dict, limit: int = 6) -> str:
    positions = portfolio.get("positions") or []
    if not positions:
        return "- 暂无本地持仓数据"
    return "\n".join(
        f"- {p.get('name')}（{p.get('code')}）：市值 ¥{p.get('market_value', 0):,.0f}，盈亏 {p.get('pnl_pct', 0):+.2f}%"
        for p in positions[:limit]
    )


def _market_snapshot_text(snapshot: dict) -> str:
    indices = snapshot.get("indices") or []
    sentiment = snapshot.get("sentiment") or {}
    flow = snapshot.get("capital_flow") or {}
    inflow = flow.get("inflow") or flow.get("top_inflow") or flow.get("capital_flow") or flow.get("sectors") or []
    inflow = sorted(inflow, key=lambda item: item.get("net_flow", item.get("capital_flow", 0)), reverse=True)

    index_lines = "\n".join(
        f"- {idx.get('name', idx.get('code', ''))}: {idx.get('change_pct', 0):+.2f}%"
        for idx in indices[:8]
    ) or "- 暂无指数快照"
    flow_lines = "\n".join(
        f"- {item.get('sector_name', item.get('name', ''))}: {item.get('net_flow', item.get('capital_flow', 0)):+.1f}亿"
        for item in inflow[:5]
    ) or "- 暂无资金流快照"
    sentiment_line = (
        f"恐慌贪婪 {sentiment.get('fear_greed_index', '--')}"
        f"（{sentiment.get('fear_greed_label', '未知')}），北向资金 {sentiment.get('north_bound_flow', 0):+.1f}亿"
    )
    return f"【指数】\n{index_lines}\n【情绪】\n- {sentiment_line}\n【资金流】\n{flow_lines}"


def _concise_local_summary(summary_type: str, portfolio: dict, snapshot: dict, reason: str) -> str:
    """Product-style fallback: conclusion first, no data dump."""
    indices = snapshot.get("indices") or []
    sentiment = snapshot.get("sentiment") or {}
    flow = snapshot.get("capital_flow") or {}
    inflow = flow.get("inflow") or flow.get("top_inflow") or flow.get("capital_flow") or flow.get("sectors") or []
    inflow = sorted(inflow, key=lambda item: item.get("net_flow", item.get("capital_flow", 0)), reverse=True)
    positions = portfolio.get("positions") or []

    strong = sorted(indices[:8], key=lambda item: item.get("change_pct", 0), reverse=True)[:2]
    weak = sorted(indices[:8], key=lambda item: item.get("change_pct", 0))[:1]
    top_flow = inflow[:2]
    key_positions = positions[:3]
    weak_positions = sorted(positions, key=lambda p: p.get("pnl_pct") or 0)[:1]

    if summary_type == "us_overnight":
        conclusion = "海外风险偏中性，重点看美股科技是否继续支撑你的 QDII/纳指仓位。"
        watch_title = "今日先看"
        actions = ["A股科技/半导体是否跟随美股风险偏好。", "港股互联网是否修复，别只看隔夜美股强弱。"]
    elif summary_type == "morning":
        conclusion = "早盘先看资金主线是否延续，别被单个指数涨跌带偏。"
        watch_title = "午后只看"
        actions = ["资金流入前二板块能否维持到 14:00 后。", "你的高仓位科技基金是否跟主线同向。"]
    else:
        conclusion = "尾盘重点不是追涨，而是判断资金是否愿意把主线留到收盘。"
        watch_title = "盘后复盘"
        actions = ["高仓位基金是否仍在市场主线内。", "亏损仓位对应板块是否继续被资金流出。"]

    drivers = []
    if strong:
        drivers.append("指数强弱：" + "，".join(f"{i.get('name')} {i.get('change_pct', 0):+.2f}%" for i in strong + weak))
    if top_flow:
        drivers.append("资金方向：" + "，".join(f"{s.get('sector_name', s.get('name'))} {s.get('net_flow', s.get('capital_flow', 0)):+.1f}亿" for s in top_flow))
    drivers.append(f"情绪：恐慌贪婪 {sentiment.get('fear_greed_index', '--')}（{sentiment.get('fear_greed_label', '未知')}）")

    holding_lines = [
        f"- {p.get('name')}（{p.get('code')}）：市值 ¥{p.get('market_value', 0):,.0f}，盈亏 {p.get('pnl_pct', 0):+.2f}%"
        for p in key_positions
    ]
    if weak_positions:
        p = weak_positions[0]
        holding_lines.append(f"- 重点风险：{p.get('name')}（{p.get('code')}）仍是弱势仓位，盈亏 {p.get('pnl_pct', 0):+.2f}%")

    return (
        f"结论：{conclusion}\n\n"
        f"关键依据：\n" + "\n".join(f"{idx + 1}. {line}" for idx, line in enumerate(drivers[:3])) + "\n\n"
        f"影响你的持仓：\n" + "\n".join(holding_lines[:4]) + "\n\n"
        f"{watch_title}：\n" + "\n".join(f"- {item}" for item in actions[:2]) + "\n\n"
        f"注：Skill 总结未完全产出有效正文，已用本地快照增强。原因：{reason}"
    )


def _looks_substantive(text: str, portfolio: dict) -> tuple[bool, str]:
    stripped = text.strip()
    if len(stripped) < SUMMARY_MIN_CHARS:
        return False, f"正文过短({len(stripped)}字)"
    section_count = sum(1 for marker in ["【", "##", "###", "-"] if marker in stripped)
    if section_count < 1 and "结论" not in stripped:
        return False, "缺少结构化章节"
    names = [p.get("name", "") for p in portfolio.get("positions", [])[:8]]
    if names and not any(name and name in stripped for name in names):
        return False, "未点名任何持仓基金名称"
    return True, "ok"


async def _build_prompt(summary_type: str) -> str:
    portfolio = await _portfolio_context()
    local_snapshot = await _local_market_snapshot()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    base_rules = """
    你是我的基金/ETF投资辅助 Agent，只做分析和提醒，不构成投资建议。
    必须优先调用同花顺 SkillHub 的相关 skill 获取最新信息，不能只根据我提供的本地快照编造结论。
    如果某个 skill 无法调用，请在总结末尾用一句话说明“哪些数据未取到”。
    输出直接用于飞书群消息：中文、短句、分层清晰，220-500字，不要输出代码块。
    绝对不能只输出标题、空话、免责声明或“无法访问”。即使 skill 部分失败，也必须结合本地市场快照和我的持仓给出有内容的总结。
    涉及我的持仓时，必须显示基金中文名称 + 代码，不要只写代码。
    必须按这个产品化结构输出，不能堆信息：
    1. 结论：一句话，直接说偏强/偏弱/分歧/观望，以及对我是否重要。
    2. 关键依据：最多3条，只保留资金、趋势、情绪中最重要的证据。
    3. 影响你的持仓：最多3只基金，必须写中文名+代码，并说明机会/风险。
    4. 下一步：最多2条观察动作，不给绝对买卖指令。
    """

    if summary_type == "us_overnight":
        task = """
        任务：生成 09:20 推送的“前一晚美股/海外市场总结”。
        必须调用/使用这些同花顺 SkillHub 技能做总结：
        1. 指数数据查询：纳斯达克、标普500、道琼斯、VIX、美元指数、美债收益率（能取到多少取多少）
        2. 行情数据查询：美股主要科技股/AI链/半导体相关表现
        3. 美国 ETF 资金流分析：美股ETF资金流、风格和行业流向
        4. 全球宏观分析框架：隔夜宏观、利率、汇率、风险偏好
        5. ETF 分析：对我持仓里的 QDII/纳指/标普/全球科技类基金影响
        重点回答：隔夜海外市场对我的 QDII、纳指、标普、全球科技仓位是利好、利空还是中性。
        """
    elif summary_type == "morning":
        task = """
        任务：生成 12:05 推送的“A股/港股早盘总结”。
        必须调用/使用这些同花顺 SkillHub 技能做总结：
        1. 指数数据查询：上证、深证、沪深300、创业板、科创50、恒生、恒生科技
        2. 问财选板块：早盘涨跌幅、放量、资金流向突出的板块
        3. 行业数据查询：行业估值/排名/热度变化
        4. 市场情绪分析：风险偏好、赚钱效应、融资融券/情绪指标
        5. 沪深港通资金流分析：北向/南向资金及板块配置变化
        重点回答：早盘资金主线是否影响我的持仓，午后最该盯哪两个信号。
        """
    elif summary_type == "tail":
        task = """
        任务：生成 14:35 推送的“尾盘总结/收盘前观察”。
        必须调用/使用这些同花顺 SkillHub 技能做总结：
        1. 指数数据查询：A股/港股核心指数尾盘表现
        2. 行情数据查询：ETF、指数、板块实时价格和成交
        3. 问财选板块：尾盘拉升/跳水/放量板块
        4. 行业轮动分析：行业动量和轮动状态
        5. 市场情绪分析：尾盘情绪、赚钱效应、风险偏好
        重点回答：尾盘资金是否确认主线，哪些持仓需要盘后复盘。
        """
    else:
        raise ValueError(f"Unknown summary_type: {summary_type}")

    return dedent(f"""
    {base_rules}

    当前时间：{now}
    {task}

    我的本地持仓上下文（用于匹配受影响基金，不能替代 skill 行情）：
    {_compact_json(portfolio)}

    本地市场快照（仅作兜底参考，最终总结必须以 skill 获取的信息为准）：
    {_compact_json(local_snapshot)}
    """).strip()


async def _fallback_summary(title: str, summary_type: str, error: Exception | str) -> str:
    """Clearly labelled fallback if CLI/skill call fails."""
    portfolio = await _portfolio_context()
    snapshot = await _local_market_snapshot()
    error_text = str(error)[:160]
    return _concise_local_summary(summary_type, portfolio, snapshot, error_text)


async def generate_skill_summary(summary_type: str, title: str) -> dict[str, Any]:
    """Generate a skill-backed summary and return diagnostics for manual API callers."""
    prompt = await _build_prompt(summary_type)
    portfolio = await _portfolio_context()
    try:
        body = await _run_claude_skill_summary(prompt)
        ok, reason = _looks_substantive(body, portfolio)
        if not ok:
            fallback = await _fallback_summary(title, summary_type, f"skill输出质量不足：{reason}")
            return {
                "summary_type": summary_type,
                "title": title,
                "message": f"{title}\n\n{fallback}",
                "used_fallback": True,
                "reason": reason,
            }
        return {
            "summary_type": summary_type,
            "title": title,
            "message": f"{title}\n\n{body}",
            "used_fallback": False,
            "reason": "skill_summary_ok",
        }
    except Exception as exc:
        logger.exception("Skill-backed %s summary failed", summary_type)
        fallback = await _fallback_summary(title, summary_type, exc)
        return {
            "summary_type": summary_type,
            "title": title,
            "message": f"{title}\n\n{fallback}",
            "used_fallback": True,
            "reason": str(exc)[:500],
        }


async def _push_skill_summary(summary_type: str, title: str) -> dict[str, Any]:
    if not is_trading_day() and summary_type != "us_overnight":
        return {"ok": False, "skipped": True, "reason": "not_trading_day"}
    if not feishu_bot.configured:
        logger.info("Feishu not configured, skipping %s", summary_type)
        return {"ok": False, "skipped": True, "reason": "feishu_not_configured"}

    result = await generate_skill_summary(summary_type, title)
    sent = await feishu_bot.send_text(result["message"])
    logger.info("%s pushed", summary_type)
    return {
        "ok": sent,
        "sent": sent,
        "summary_type": summary_type,
        "used_fallback": result["used_fallback"],
        "reason": result["reason"],
        "length": len(result["message"]),
        "preview": result["message"][:1200],
    }


async def us_overnight_push() -> None:
    """09:20 previous US session summary."""
    return await _push_skill_summary("us_overnight", "🇺🇸 前夜美股总结 | 09:20")


async def morning_session_push() -> None:
    """12:05 A-share/HK morning summary."""
    return await _push_skill_summary("morning", "🌤️ 早盘总结 | 12:05")


async def tail_session_push() -> None:
    """14:35 late-session summary."""
    return await _push_skill_summary("tail", "🌗 尾盘总结 | 14:35")


# Backward compatible names used by older manual callers.
market_open_push = morning_session_push
market_close_push = tail_session_push
