"""Skill-backed Feishu market summary tasks.

Wave 2 refactor: real data feeds (GlobalIndexProvider + eastmoney sectors +
PortfolioValuationService) replace the deterministic MarketDataProvider mock
in live mode. The mock is preserved ONLY for ``market_data_mode == "demo"``.
All three push types (us_overnight / morning / tail) share a unified 4-section
structure and a real-number quality gate so the LLM can never publish empty
talk without citing at least one real figure.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from textwrap import dedent
from typing import Any

from app.config import settings
from app.database import async_session
from app.feishu.bot import feishu_bot
from app.services import sector_card_service
from app.services.global_index_provider import DataUnavailable, GlobalIndexProvider
from app.services.market_data_provider import MarketDataProvider
from app.services.market_data_trust import market_data_meta
from app.services.portfolio_valuation_service import PortfolioValuationService
from app.tasks.scheduler import is_trading_day

logger = logging.getLogger(__name__)

SUMMARY_MIN_CHARS = 180

# ── Index code sets ──────────────────────────────────────────────────────────

# Full set fetched once per snapshot (A-share + overseas + optional macros).
_SNAPSHOT_INDEX_CODES = [
    "000001",
    "399001",
    "000300",
    "399006",
    "000688",
    "000016",
    "HSI",
    "N225",
    "KOSPI",
    "IXIC",
    "SPX",
    "DJI",
    "VIX",
    "USDX",
]

_OVERSEAS_INDEX_CODES = {"DJI", "SPX", "IXIC", "N225", "KOSPI", "HSI", "VIX", "USDX"}
_ASHARE_INDEX_CODES = {"000001", "399001", "000300", "399006", "000688"}

# ── Overseas-exposure classification ─────────────────────────────────────────

# Holding codes from the WATCH_BASKET groups that track overnight overseas
# markets (美股科技/纳指 + 港股互联网). These rank first in portfolio sorting
# so the us_overnight push shows the most impacted holdings.
_OVERSEAS_HOLDING_CODES: set[str] = set()
for _group in sector_card_service.WATCH_BASKET:
    if _group["name"] in ("美股科技/纳指", "港股互联网"):
        _OVERSEAS_HOLDING_CODES.update(_group.get("holding_codes", []))

# Name keywords that also indicate overseas exposure (belt-and-suspenders with
# the code set above, for holdings not yet in WATCH_BASKET).
_OVERSEAS_NAME_KEYWORDS = (
    "QDII",
    "纳指",
    "纳斯达克",
    "标普",
    "恒生",
    "全球",
    "美国",
    "道琼斯",
    "美股",
    "港股互联网",
)

# Beta map for overnight impact estimation (holding name keyword -> beta vs the
# representative overseas index). Nice-to-have heuristic; defaults to 1.0.
_BETA_MAP: dict[str, float] = {
    "纳指": 1.0,
    "纳斯达克": 1.0,
    "标普": 1.0,
    "道琼斯": 1.0,
    "美股": 1.0,
    "恒生": 0.8,
    "港股互联网": 0.8,
    "全球": 0.9,
}


def _is_overseas_holding(code: str, name: str) -> bool:
    """True if a holding is exposed to overnight overseas markets."""
    if code in _OVERSEAS_HOLDING_CODES:
        return True
    return any(kw in name for kw in _OVERSEAS_NAME_KEYWORDS)


def _beta_for_holding(name: str) -> float:
    for kw, beta in _BETA_MAP.items():
        if kw in name:
            return beta
    return 1.0


def _overnight_change_for_holding(
    name: str, overseas_indices: list[dict]
) -> float | None:
    """Pick the overseas index change most relevant to a given holding."""
    by_code = {i["code"]: i for i in overseas_indices}

    if any(
        kw in name
        for kw in ("纳指", "纳斯达克", "标普", "道琼斯", "美股", "全球", "QDII")
    ):
        for code in ("IXIC", "SPX", "DJI"):
            idx = by_code.get(code)
            if idx and idx.get("change_pct") is not None:
                return float(idx["change_pct"])

    if any(kw in name for kw in ("恒生", "港股", "互联网")):
        idx = by_code.get("HSI")
        if idx and idx.get("change_pct") is not None:
            return float(idx["change_pct"])

    for idx in overseas_indices:
        if idx.get("change_pct") is not None:
            return float(idx["change_pct"])
    return None


# ── Claude CLI subprocess (kept as-is) ───────────────────────────────────────


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


# ── A3: local market snapshot ────────────────────────────────────────────────


def _convert_sector_rows(raw: list[dict]) -> list[dict]:
    """Convert raw eastmoney sector rows (f14/f3/f62) to bridge format."""
    rows: list[dict] = []
    for item in raw:
        name = str(item.get("f14") or "").strip()
        if not name:
            continue
        net_flow = float(item.get("f62") or 0)
        change_pct = float(item.get("f3") or 0)
        rows.append(
            {
                "name": name,
                "sector_name": name,
                "code": str(item.get("f12") or ""),
                "net_flow": net_flow,
                "capital_flow": net_flow,
                "change_pct": change_pct,
            }
        )
    return rows


async def _local_market_snapshot() -> dict:
    """Build a local market snapshot from real data sources.

    Live mode: ``GlobalIndexProvider`` + eastmoney sectors. Fails closed on
    source failure -- never substitutes mock data (market-data trust boundary).
    Demo mode: deterministic ``MarketDataProvider`` mock.
    """
    if settings.market_data_mode == "demo":
        provider = MarketDataProvider()
        indices = provider.get_global_indices()
        capital_flow = provider.get_capital_flow()
        sentiment = provider.get_sentiment()
        sectors = capital_flow.get("sectors", [])
        sectors_top = sorted(sectors, key=lambda s: s.get("net_flow", 0), reverse=True)
        sectors_bottom = sorted(sectors, key=lambda s: s.get("net_flow", 0))
        meta = market_data_meta(source="demo/mock", status="ok", is_mock=True)
        return {
            "indices": indices,
            "capital_flow": capital_flow,
            "sectors_top": sectors_top,
            "sectors_bottom": sectors_bottom,
            "sentiment": sentiment,
            "meta": meta,
        }

    # ── live mode ──
    indices: list[dict] = []
    try:
        indices = await GlobalIndexProvider().get_indices(_SNAPSHOT_INDEX_CODES)
    except DataUnavailable as exc:
        logger.warning("GlobalIndexProvider unavailable: %s", exc)

    sectors: list[dict] = []
    try:
        raw = await asyncio.to_thread(sector_card_service._fetch_eastmoney_all_sectors)
        sectors = _convert_sector_rows(raw)
    except Exception as exc:
        logger.warning("sector fetch failed: %s", exc)

    sectors_top = sorted(sectors, key=lambda s: s.get("net_flow", 0), reverse=True)
    sectors_bottom = sorted(sectors, key=lambda s: s.get("net_flow", 0))

    if not indices and not sectors:
        status = "unavailable"
    elif not indices or not sectors:
        status = "empty"
    else:
        status = "ok"

    meta = market_data_meta(source="eastmoney", status=status, is_mock=False)

    return {
        "indices": indices,
        "capital_flow": {"sectors": sectors},
        "sectors_top": sectors_top,
        "sectors_bottom": sectors_bottom,
        "sentiment": {},  # live mode: no mock sentiment (trust boundary)
        "meta": meta,
    }


# ── B4: portfolio context ────────────────────────────────────────────────────


async def _portfolio_context() -> dict:
    """Load portfolio valuation with overseas-exposure priority sorting.

    Holdings exposed to overnight overseas markets (QDII / 纳指 / 标普 / 恒生 /
    全球 / 港股互联网) rank FIRST so the us_overnight push shows the most
    impacted positions. Within a priority group, sort by market_value desc.
    """
    try:
        async with async_session() as db:
            service = PortfolioValuationService(db)
            rows = await service.get_live_valuation()
    except Exception as exc:
        logger.warning("Could not load portfolio context for skill summary: %s", exc)
        return {"error": str(exc), "positions": []}

    if not rows:
        return {
            "total_value": 0.0,
            "total_cost": 0.0,
            "total_pnl": 0.0,
            "total_pnl_pct": 0.0,
            "positions": [],
        }

    positions: list[dict] = []
    total_value = 0.0
    total_cost = 0.0
    for row in rows:
        market_value = float(row.get("market_value") or 0)
        pnl_pct_raw = row.get("unrealized_pnl_pct")
        pnl_pct = float(pnl_pct_raw) if pnl_pct_raw is not None else 0.0
        code = str(row.get("symbol") or "")
        name = str(row.get("name") or code)
        positions.append(
            {
                "code": code,
                "name": name,
                "market_value": round(market_value, 2),
                "pnl_pct": round(pnl_pct, 2),
                "today_estimated_pct": row.get("today_estimated_pct"),
                "stale": bool(row.get("stale")),
            }
        )
        total_value += market_value
        # When pnl_pct is available, derive cost; otherwise assume cost ≈ value.
        if pnl_pct_raw is not None and pnl_pct != 0:
            total_cost += market_value / (1 + pnl_pct / 100)
        else:
            total_cost += market_value

    positions.sort(
        key=lambda p: (
            0 if _is_overseas_holding(p["code"], p["name"]) else 1,
            -(p["market_value"]),
        )
    )

    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0.0

    return {
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "positions": positions[:12],
    }


# ── Facts extraction (C2 + C3) ───────────────────────────────────────────────


def _build_facts(summary_type: str, snapshot: dict, portfolio: dict) -> dict:
    """Extract structured real-number facts for prompt + quality gate."""
    indices = snapshot.get("indices") or []
    positions = portfolio.get("positions") or []

    if summary_type == "us_overnight":
        return _build_us_overnight_facts(indices, positions)
    return _build_ashare_facts(indices, snapshot, positions)


def _build_us_overnight_facts(indices: list[dict], positions: list[dict]) -> dict:
    overseas_indices = [
        {
            "code": i["code"],
            "name": i["name"],
            "change_pct": i["change_pct"],
            "price": i.get("price"),
        }
        for i in indices
        if i.get("code") in _OVERSEAS_INDEX_CODES
    ]

    impacted_holdings: list[dict] = []
    for p in positions:
        if not _is_overseas_holding(p["code"], p["name"]):
            continue
        overnight = _overnight_change_for_holding(p["name"], overseas_indices)
        beta = _beta_for_holding(p["name"])
        impact_pct = round(overnight * beta, 2) if overnight is not None else None
        impacted_holdings.append(
            {
                "name": p["name"],
                "code": p["code"],
                "today_estimated_pct": p.get("today_estimated_pct"),
                "impact_pct": impact_pct,
                "stale": p.get("stale", False),
            }
        )

    return {
        "overseas_indices": overseas_indices,
        "impacted_holdings": impacted_holdings,
    }


def _build_ashare_facts(
    indices: list[dict], snapshot: dict, positions: list[dict]
) -> dict:
    ashare_indices = [
        {
            "code": i["code"],
            "name": i["name"],
            "change_pct": i["change_pct"],
            "price": i.get("price"),
        }
        for i in indices
        if i.get("code") in _ASHARE_INDEX_CODES
    ]

    sectors_top = snapshot.get("sectors_top") or []
    sectors_bottom = snapshot.get("sectors_bottom") or []

    top_inflow = [
        {
            "name": s.get("name") or s.get("sector_name"),
            "net_flow": s.get("net_flow", 0),
            "change_pct": s.get("change_pct", 0),
        }
        for s in sectors_top[:3]
    ]
    top_outflow = [
        {
            "name": s.get("name") or s.get("sector_name"),
            "net_flow": s.get("net_flow", 0),
            "change_pct": s.get("change_pct", 0),
        }
        for s in sectors_bottom[:3]
    ]

    holdings = [
        {
            "name": p["name"],
            "code": p["code"],
            "today_estimated_pct": p.get("today_estimated_pct"),
            "pnl_pct": p.get("pnl_pct", 0),
            "stale": p.get("stale", False),
        }
        for p in positions[:12]
    ]

    return {
        "ashare_indices": ashare_indices,
        "top_inflow_sectors": top_inflow,
        "top_outflow_sectors": top_outflow,
        "holdings": holdings,
    }


# ── Prompt builder ───────────────────────────────────────────────────────────


def _compact_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _build_prompt(summary_type: str, facts: dict, portfolio: dict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    base_rules = """
    你是我的基金/ETF投资辅助 Agent，只做分析和提醒，不构成投资建议。
    以下 facts 为真实数据，不得编造，只能解读；任务是把这些真实数字翻译成中文解读并判断对我持仓利好/利空/中性。
    如果某些数据缺失就在末尾说明是数据源限制，不要说成 skill 失败。
    输出直接用于飞书群消息：中文、短句、分层清晰，220-500字，不要输出代码块。
    绝对不能只输出标题、空话、免责声明或"无法访问"。即使部分数据缺失，也必须结合已有真实 facts 给出有内容的总结。
    涉及我的持仓时，必须显示基金中文名称 + 代码，不要只写代码。
    必须按这个产品化结构输出，不能堆信息：
    1. 【结论】一句话，直接说偏强/偏弱/分歧/观望，以及对我是否重要。
    2. 【关键依据】最多3条，只保留资金、趋势、情绪中最重要的真实数字证据。
    3. 【影响你的持仓】最多3只基金，必须写中文名+代码，并说明机会/风险。
    4. 【下一步】最多2条观察动作，不给绝对买卖指令。
    """

    if summary_type == "us_overnight":
        task = """
        任务：生成 09:20 推送的"前一晚美股/海外市场总结"。
        基于以下真实 facts 解读隔夜海外市场对我的 QDII、纳指、标普、全球科技仓位是利好、利空还是中性。
        重点关联 impacted_holdings 里的 impact_pct（隔夜外盘对今日开盘的估算影响）和 today_estimated_pct。
        """
    elif summary_type == "morning":
        task = """
        任务：生成 12:05 推送的"A股/港股早盘总结"。
        基于以下真实 facts 解读早盘资金主线，关联我的持仓。
        重点回答：早盘资金主线是否影响我的持仓，午后最该盯哪两个信号。
        """
    elif summary_type == "tail":
        task = """
        任务：生成 14:35 推送的"尾盘总结/收盘前观察"。
        基于以下真实 facts 解读尾盘资金是否确认主线，哪些持仓需要盘后复盘。
        """
    else:
        raise ValueError(f"Unknown summary_type: {summary_type}")

    return dedent(f"""
    {base_rules}

    当前时间：{now}
    {task}

    真实数据 facts（JSON，不得编造，只能解读）：
    {_compact_json(facts)}

    我的本地持仓上下文（用于匹配受影响基金）：
    {_compact_json(portfolio)}
    """).strip()


# ── Quality gate (C4) ────────────────────────────────────────────────────────


def _collect_fact_numbers(facts: dict) -> list[str]:
    """Collect string representations of numeric facts for the real-number gate."""
    numbers: list[str] = []

    def add(value: Any) -> None:
        if value is None:
            return
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        if abs(v) < 0.001:
            return
        numbers.append(f"{v:+.2f}")
        numbers.append(f"{v:.2f}")

    for idx in facts.get("overseas_indices", []) or []:
        add(idx.get("change_pct"))
    for idx in facts.get("ashare_indices", []) or []:
        add(idx.get("change_pct"))
    for s in facts.get("top_inflow_sectors", []) or []:
        add(s.get("change_pct"))
    for s in facts.get("top_outflow_sectors", []) or []:
        add(s.get("change_pct"))
    for h in facts.get("impacted_holdings", []) or []:
        add(h.get("today_estimated_pct"))
        add(h.get("impact_pct"))
    for h in facts.get("holdings", []) or []:
        add(h.get("today_estimated_pct"))
    return numbers


def _looks_substantive(body: str, facts: dict, portfolio: dict) -> tuple[bool, str]:
    stripped = body.strip()
    if len(stripped) < SUMMARY_MIN_CHARS:
        return False, f"正文过短({len(stripped)}字)"
    section_count = sum(1 for marker in ["【", "##", "###", "-"] if marker in stripped)
    if section_count < 1 and "结论" not in stripped:
        return False, "缺少结构化章节"
    names = [p.get("name", "") for p in portfolio.get("positions", [])[:8]]
    if names and not any(name and name in stripped for name in names):
        return False, "未点名任何持仓基金名称"
    # Real-number gate: body must cite at least one real figure from facts.
    fact_numbers = _collect_fact_numbers(facts)
    if fact_numbers and not any(num in stripped for num in fact_numbers):
        return False, "未引用任何真实数据数字"
    return True, "ok"


# ── Fallback summary (C4) ────────────────────────────────────────────────────


def _concise_local_summary(
    summary_type: str, facts: dict, portfolio: dict, reason: str
) -> str:
    """Build the 4-section structure from REAL facts (never mock in live mode)."""
    if summary_type == "us_overnight":
        return _concise_us_overnight(facts, reason)
    return _concise_ashare(summary_type, facts, reason)


def _concise_us_overnight(facts: dict, reason: str) -> str:
    overseas = facts.get("overseas_indices", []) or []
    impacted = facts.get("impacted_holdings", []) or []

    if not overseas:
        conclusion = "海外指数数据暂缺，无法判断隔夜风险偏好，先观望。"
    else:
        ups = [i for i in overseas if (i.get("change_pct") or 0) > 0]
        downs = [i for i in overseas if (i.get("change_pct") or 0) < 0]
        if len(ups) > len(downs):
            conclusion = "隔夜海外偏强，关注是否带动你的 QDII/纳指仓位。"
        elif len(downs) > len(ups):
            conclusion = "隔夜海外偏弱，警惕对你的 QDII/纳指/恒生仓位形成拖累。"
        else:
            conclusion = "隔夜海外分化，美股与亚太走势不一致，按持仓分别评估。"

    drivers: list[str] = []
    for i in overseas[:3]:
        pct = i.get("change_pct")
        if pct is not None:
            drivers.append(f"{i.get('name')} {pct:+.2f}%")
    if not drivers:
        drivers.append("海外指数数据暂缺")

    holding_lines: list[str] = []
    for h in impacted[:3]:
        parts = [f"- {h.get('name')}（{h.get('code')}）"]
        est = h.get("today_estimated_pct")
        if est is not None:
            parts.append(f"今日预估 {est:+.2f}%")
        impact = h.get("impact_pct")
        if impact is not None:
            parts.append(f"隔夜影响约 {impact:+.2f}%")
        if h.get("stale"):
            parts.append("估值可能延迟")
        holding_lines.append("，".join(parts))
    if not holding_lines:
        holding_lines.append("- 暂无受隔夜外盘影响的持仓")

    actions = [
        "A股科技/半导体是否跟随美股风险偏好。",
        "港股互联网是否修复，别只看隔夜美股强弱。",
    ]

    return (
        f"【结论】{conclusion}\n\n"
        f"【关键依据】\n" + "\n".join(f"- {d}" for d in drivers[:3]) + "\n\n"
        "【影响你的持仓】\n" + "\n".join(holding_lines[:3]) + "\n\n"
        "【下一步】\n" + "\n".join(f"- {a}" for a in actions[:2]) + "\n\n"
        f"注：LLM 解读未产出，已用真实数据结构化要点。原因：{reason}"
    )


def _concise_ashare(summary_type: str, facts: dict, reason: str) -> str:
    ashare = facts.get("ashare_indices", []) or []
    inflow = facts.get("top_inflow_sectors", []) or []
    outflow = facts.get("top_outflow_sectors", []) or []
    holdings = facts.get("holdings", []) or []

    if not ashare and not inflow:
        conclusion = "A股数据暂缺，无法判断资金主线，先观望。"
    elif summary_type == "morning":
        conclusion = "早盘先看资金主线是否延续，别被单个指数涨跌带偏。"
    else:
        conclusion = "尾盘重点判断资金是否愿意把主线留到收盘。"

    drivers: list[str] = []
    for i in ashare[:3]:
        pct = i.get("change_pct")
        if pct is not None:
            drivers.append(f"{i.get('name')} {pct:+.2f}%")
    for s in inflow[:2]:
        flow = s.get("net_flow")
        if flow is not None:
            drivers.append(f"资金流入：{s.get('name')} {flow / 1e8:+.1f}亿")
    for s in outflow[:1]:
        flow = s.get("net_flow")
        if flow is not None:
            drivers.append(f"资金流出：{s.get('name')} {flow / 1e8:+.1f}亿")
    if not drivers:
        drivers.append("数据暂缺")

    holding_lines: list[str] = []
    for h in holdings[:3]:
        parts = [f"- {h.get('name')}（{h.get('code')}）"]
        est = h.get("today_estimated_pct")
        if est is not None:
            parts.append(f"今日预估 {est:+.2f}%")
        if h.get("stale"):
            parts.append("估值可能延迟")
        holding_lines.append("，".join(parts))
    if not holding_lines:
        holding_lines.append("- 暂无持仓估值数据")

    if summary_type == "morning":
        actions = [
            "资金流入前二板块能否维持到 14:00 后。",
            "高仓位科技基金是否跟主线同向。",
        ]
    else:
        actions = [
            "高仓位基金是否仍在市场主线内。",
            "亏损仓位对应板块是否继续被资金流出。",
        ]

    return (
        f"【结论】{conclusion}\n\n"
        f"【关键依据】\n" + "\n".join(f"- {d}" for d in drivers[:3]) + "\n\n"
        "【影响你的持仓】\n" + "\n".join(holding_lines[:3]) + "\n\n"
        "【下一步】\n" + "\n".join(f"- {a}" for a in actions[:2]) + "\n\n"
        f"注：LLM 解读未产出，已用真实数据结构化要点。原因：{reason}"
    )


# ── Orchestrator (refactored: fetch ONCE) ────────────────────────────────────


async def generate_skill_summary(summary_type: str, title: str) -> dict[str, Any]:
    """Generate a skill-backed summary and return diagnostics for manual API callers."""
    snapshot = await _local_market_snapshot()
    portfolio = await _portfolio_context()
    facts = _build_facts(summary_type, snapshot, portfolio)
    prompt = _build_prompt(summary_type, facts, portfolio)
    meta_dict = snapshot["meta"].model_dump(mode="json")

    try:
        body = await _run_claude_skill_summary(prompt)
        ok, reason = _looks_substantive(body, facts, portfolio)
        if ok:
            return {
                "summary_type": summary_type,
                "title": title,
                "message": f"{title}\n\n{body}",
                "used_fallback": False,
                "reason": "skill_summary_ok",
                "meta": meta_dict,
            }
        fallback = _concise_local_summary(summary_type, facts, portfolio, reason)
        return {
            "summary_type": summary_type,
            "title": title,
            "message": f"{title}\n\n{fallback}",
            "used_fallback": True,
            "reason": reason,
            "meta": meta_dict,
        }
    except Exception as exc:
        logger.exception("Skill-backed %s summary failed", summary_type)
        fallback = _concise_local_summary(
            summary_type, facts, portfolio, str(exc)[:160]
        )
        return {
            "summary_type": summary_type,
            "title": title,
            "message": f"{title}\n\n{fallback}",
            "used_fallback": True,
            "reason": str(exc)[:500],
            "meta": meta_dict,
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
