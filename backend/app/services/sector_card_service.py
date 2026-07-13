"""Build user-facing sector summary cards from market flow + portfolio data."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import httpx

from app.feishu.cards import build_sector_summary_card
from app.services.sector_monitor_agents import (
    decide_sector_opportunities,
    fetch_market_mood_snapshot,
    run_iwencai_skill,
)
from app.skills.bridge import bridge

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "financial.db"
ASTOCK_SKILL_CLI = Path.home() / ".openclaw" / "workspace" / "skills" / "hithink-astock-selector" / "scripts" / "cli.py"

WATCH_BASKET: list[dict[str, Any]] = [
    {
        "name": "光模块/通信",
        "priority": "core",
        "keywords": ["光模块", "CPO", "通信设备", "通信服务", "5G", "算力"],
        "source": {"secid": "2.931160", "display_code": "931160", "provider": "东方财富-中证指数", "name": "通信设备"},
        "etf": "通信ETF / 云计算ETF / 人工智能ETF",
        "holding_codes": ["001513", "025881"],
        "holding_hint": "易方达信息产业混合A",
    },
    {
        "name": "半导体/芯片",
        "priority": "core",
        "keywords": ["半导体", "芯片", "集成电路", "半导体设备"],
        "preferred_names": ["半导体设备", "半导体", "半导体材料", "第四代半导体", "集成电路制造", "数字芯片设计"],
        "source": {"secid": "2.931743", "display_code": "931743", "provider": "东方财富-中证指数", "name": "半导体材料设备"},
        "etf": "芯片ETF / 半导体ETF / 科创芯片ETF",
        "holding_codes": ["006503", "021225"],
        "holding_hint": "财通集成电路产业股票C",
    },
    {
        "name": "中证电池",
        "priority": "core",
        "keywords": ["电池", "锂电", "新能源车", "储能"],
        "source": {"secid": "2.931719", "display_code": "931719", "provider": "东方财富-中证指数", "name": "CS电池"},
        "etf": "电池ETF / 新能源车ETF",
        "holding_codes": ["018927"],
        "holding_hint": "南方中证电池主题ETF联接C",
    },
    {
        "name": "有色金属",
        "priority": "core",
        "keywords": ["有色金属", "工业金属", "小金属", "贵金属", "黄金"],
        "source": {"secid": "1.000819", "display_code": "1B0819", "provider": "东方财富-指数行情", "name": "有色金属"},
        "etf": "有色金属ETF / 黄金ETF",
        "holding_codes": ["004432"],
        "holding_hint": "南方有色金属ETF联接A",
    },
    {
        "name": "港股互联网",
        "priority": "satellite",
        "keywords": ["互联网服务", "港股互联网", "恒生科技", "中国互联网50", "软件开发"],
        "preferred_names": ["中国互联网50", "恒生科技"],
        "source": {"secid": "2.H30533", "display_code": "H30533", "provider": "东方财富-中证指数", "name": "中国互联网50"},
        "etf": "恒生科技ETF / 港股互联网ETF",
        "holding_codes": ["013171"],
        "holding_hint": "华夏恒生互联网科技业ETF联接",
    },
    {
        "name": "美股科技/纳指",
        "priority": "satellite",
        "keywords": ["纳斯达克", "标普500", "道琼斯", "全球科技", "人工智能"],
        "preferred_names": ["纳斯达克100", "标普500", "道琼斯工业平均"],
        "source": {"secid": "100.NDX100", "display_code": "NDX100", "provider": "东方财富-全球指数", "name": "纳斯达克100"},
        "etf": "纳指ETF / 标普500ETF / 道琼斯ETF",
        "holding_codes": ["022184", "100055", "012920", "012922", "016452", "008971", "019172", "019173", "161125"],
        "holding_hint": "富国全球科技互联网 / 纳指 / 标普持仓",
    },
    {
        "name": "主要消费",
        "priority": "satellite",
        "keywords": ["中证消费", "主要消费", "食品饮料", "白酒", "商贸零售"],
        "preferred_names": ["中证消费", "食品饮料", "白酒", "商贸零售"],
        "source": {"secid": "1.000932", "display_code": "000932", "provider": "东方财富-中证指数", "name": "中证消费"},
        "etf": "消费ETF / 食品饮料ETF",
        "holding_codes": ["009180"],
        "holding_hint": "嘉实中证主要消费ETF联接C",
    },
]


def _fetch_eastmoney_sectors(
    fid: str = "f62",
    po: int = 1,
    pz: int = 8,
    fs: str = "m:90+t:2",
) -> list[dict[str, Any]]:
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1,
        "pz": pz,
        "po": po,
        "np": 1,
        "fltt": 2,
        "invt": 2,
        "fid": fid,
        "fs": fs,
        "fields": "f12,f14,f2,f3,f62,f66,f69,f72,f75,f184",
    }
    try:
        with httpx.Client(timeout=15.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            return resp.json().get("data", {}).get("diff", []) or []
    except Exception:
        return []


def _fetch_eastmoney_all_sectors(pz: int = 200) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fs in ("m:90+t:2", "m:90+t:3"):
        for fid, po in (("f3", 1), ("f3", 0), ("f62", 1), ("f62", 0)):
            rows.extend(_fetch_eastmoney_sectors(fid, po, pz, fs=fs))

    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = row.get("f14")
        if name:
            deduped[name] = row
    return list(deduped.values())


def _load_focus_holdings() -> dict[str, dict[str, Any]]:
    if not DB_PATH.exists():
        return {}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        select p.symbol, f.name, p.market_value, p.unrealized_pnl_pct
        from positions p
        left join fund_profiles f on f.code = p.symbol
        where p.source = 'yangjibao'
        """
    ).fetchall()
    return {row["symbol"]: dict(row) for row in rows}


def _format_flow(sector: dict[str, Any] | None) -> str:
    if not sector:
        return "暂无"
    return f"{sector.get('f3', 0):+.2f}% / {sector.get('f62', 0) / 1e8:+.1f}亿"


def build_signal_bar(value: float, width: int = 10) -> str:
    """Render a Feishu-safe text bar for quick mobile scanning."""
    magnitude = min(abs(value), 5.0) / 5.0
    filled = max(1 if value != 0 else 0, round(magnitude * width))
    empty = max(width - filled, 0)
    if value > 0:
        return "█" * filled + "░" * empty
    if value < 0:
        return "░" * empty + "█" * filled
    return "░" * width


def _sector_score(sector: dict[str, Any]) -> float:
    return float(sector.get("f3") or 0) + float(sector.get("f62") or 0) / 1e9


def _best_sector_match(
    sectors: list[dict[str, Any]],
    keywords: list[str],
    preferred_names: list[str] | None = None,
) -> dict[str, Any] | None:
    matches = [
        sector for sector in sectors
        if any(keyword.lower() in str(sector.get("f14", "")).lower() for keyword in keywords)
    ]
    if not matches:
        return None
    preferred_names = preferred_names or []
    preferred = [
        sector for sector in matches
        if str(sector.get("f14", "")) in preferred_names
    ]
    if preferred:
        return max(preferred, key=_sector_score)
    return max(matches, key=lambda item: abs(float(item.get("f62") or 0)))


def _flow_text(flow: float) -> str:
    return f"{flow / 1e8:+.1f}亿"


def _technical_label(change_pct: float, flow: float) -> str:
    if change_pct > 1 and flow > 0:
        return "放量转强"
    if change_pct > 0 and flow < 0:
        return "上涨但资金分歧"
    if change_pct < -1 and flow < 0:
        return "放量走弱"
    if change_pct < 0 and flow > 0:
        return "资金低吸"
    return "震荡观察"


def _status_label(change_pct: float, flow: float) -> str:
    if change_pct >= 1 and flow >= 0:
        return "强"
    if change_pct <= -1 and flow <= 0:
        return "弱"
    if flow > 0:
        return "吸"
    if flow < 0:
        return "流"
    return "平"


def _fetch_sector_klines(code: str, limit: int = 20) -> list[list[str]]:
    if not code:
        return []
    secid = code if "." in code else f"90.{code}"
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "end": "20500101",
        "lmt": limit,
    }
    try:
        with httpx.Client(timeout=8.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            klines = resp.json().get("data", {}).get("klines", []) or []
    except Exception:
        return []
    return [line.split(",") for line in klines]


def _ma(values: list[float], size: int) -> float:
    return sum(values[-size:]) / size


def _kline_label(code: str, fallback: str) -> str:
    klines = _fetch_sector_klines(code)
    if len(klines) < 10:
        return fallback
    closes = [float(row[2]) for row in klines if len(row) > 2]
    latest = klines[-1]
    latest_pct = float(latest[8]) if len(latest) > 8 else 0.0
    close = closes[-1]
    prev_close = closes[-2]
    ma5 = _ma(closes, 5)
    ma10 = _ma(closes, 10)
    prev_ma5 = _ma(closes[:-1], 5)
    prev_ma10 = _ma(closes[:-1], 10)
    above_now = close > ma5 and close > ma10
    above_prev = prev_close > prev_ma5 and prev_close > prev_ma10
    below_now = close < ma5 and close < ma10
    below_prev = prev_close < prev_ma5 and prev_close < prev_ma10
    if above_now and above_prev:
        return "继续站上5/10日线，短线仍站稳"
    if above_now and not above_prev:
        return "首次站上5/10日线，仍需明日确认站稳"
    if below_now and below_prev:
        return "继续跌破5/10日线，趋势仍未修复"
    if below_now and not below_prev:
        return "首次跌破5/10日线，短线转弱需警惕"
    if latest_pct <= -2:
        return "日K长阴走弱"
    if latest_pct >= 2:
        return "日K中阳转强"
    if close > ma5 and close < ma10:
        return "站上5日线但未站稳10日线，仍是修复观察"
    if close < ma5 and close > ma10:
        return "跌破5日线但仍在10日线上方，短线转弱未破位"
    return "日K震荡，均线信号不明确"


def _market_context_text(inflow: list[dict[str, Any]], outflow: list[dict[str, Any]]) -> str:
    in_names = "、".join(f"{row.get('f14')} {row.get('f62', 0) / 1e8:+.0f}亿" for row in inflow[:2])
    out_names = "、".join(f"{row.get('f14')} {row.get('f62', 0) / 1e8:+.0f}亿" for row in outflow[:2])
    if in_names and out_names:
        return f"资金流入集中在{in_names}，流出压力集中在{out_names}"
    if in_names:
        return f"资金流入集中在{in_names}"
    if out_names:
        return f"资金流出压力集中在{out_names}"
    return ""


def _load_iwencai_env() -> dict[str, str]:
    env = os.environ.copy()
    if env.get("IWENCAI_API_KEY"):
        return env

    for profile in (Path.home() / ".zshrc", Path.home() / ".zprofile", Path.home() / ".bash_profile", Path.home() / ".profile"):
        if not profile.exists():
            continue
        try:
            for line in profile.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line.startswith("export IWENCAI_") or "=" not in line:
                    continue
                key, value = line.removeprefix("export ").split("=", 1)
                env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        except OSError:
            continue
    return env


async def _run_astock_skill_query(query: str, limit: int = 5) -> dict[str, Any]:
    if not ASTOCK_SKILL_CLI.exists():
        return {}
    env = _load_iwencai_env()
    if not env.get("IWENCAI_API_KEY"):
        return {}
    try:
        proc = await asyncio.create_subprocess_exec(
            "python3",
            str(ASTOCK_SKILL_CLI),
            "--query",
            query,
            "--limit",
            str(limit),
            "--timeout",
            "30",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=35)
    except Exception:
        return {}
    if proc.returncode != 0:
        return {}
    try:
        data = json.loads(stdout.decode("utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) and data.get("success") else {}


def _first_field(row: dict[str, Any], *fragments: str) -> Any:
    for key, value in row.items():
        if all(fragment in key for fragment in fragments):
            return value
    return None


def _format_iwencai_sector(row: dict[str, Any]) -> str:
    name = row.get("指数简称") or row.get("板块简称") or row.get("股票简称") or row.get("名称") or "-"
    code = row.get("指数代码") or row.get("板块代码") or row.get("股票代码") or ""
    pct = _first_field(row, "涨跌幅") or row.get("最新涨跌幅:前复权")
    amount = _first_field(row, "成交额")
    pct_text = f"{float(pct):+.2f}%" if isinstance(pct, int | float) else str(pct or "-")
    amount_text = f"，成交额{float(amount) / 1e8:.0f}亿" if isinstance(amount, int | float) else ""
    code_text = f"({code})" if code else ""
    return f"{name}{code_text} {pct_text}{amount_text}"


def _iwencai_sector_to_flow_row(row: dict[str, Any]) -> dict[str, Any] | None:
    name = row.get("指数简称")
    code = row.get("指数代码")
    if not name or not code:
        return None
    pct = _first_field(row, "涨跌幅") or row.get("最新涨跌幅:前复权")
    amount = _first_field(row, "成交额")
    if pct is None and amount is None:
        return None
    pct = pct or 0
    amount = amount or 0
    net_inflow = _first_field(row, "主力净买入额") or _first_field(row, "主力资金流向")
    try:
        pct_value = float(pct)
        amount_value = float(amount)
        net_inflow_value = float(net_inflow) if net_inflow is not None else None
    except (TypeError, ValueError):
        return None
    source_skill = row.get("_source_skill") or "hithink-industry-query"
    if net_inflow_value is None:
        display_flow = f"成交额 {amount_value / 1e8:.1f}亿 / 主力 暂无"
    else:
        display_flow = f"成交额 {amount_value / 1e8:.1f}亿 / 主力 {net_inflow_value / 1e8:+.1f}亿"
    return {
        "f12": code,
        "f14": name,
        "f3": pct_value,
        "f62": net_inflow_value,
        "amount": amount_value,
        "source_code": code,
        "source_provider": "同花顺问财",
        "source_skill": source_skill,
        "display_flow": display_flow,
    }


async def _fetch_iwencai_focus_sector_rows() -> list[dict[str, Any]]:
    queries = [
        (
            "hithink-industry-query",
            "今日通信设备、半导体、有色金属、电池、消费行业行情、成交额、主力资金净流入",
            25,
        ),
        (
            "hithink-industry-query",
            "今日中证消费、食品饮料、白酒、商贸零售行情、成交额、主力资金净流入",
            12,
        ),
        (
            "hithink-zhishu-query",
            "纳斯达克100、标普500、道琼斯、恒生科技、中国互联网50、中证消费 今日涨跌幅、成交额",
            12,
        ),
    ]
    results = await asyncio.gather(
        *(run_iwencai_skill(skill, query, limit=limit) for skill, query, limit in queries),
        return_exceptions=True,
    )
    deduped: dict[str, dict[str, Any]] = {}
    for result, (skill, _query, _limit) in zip(results, queries, strict=False):
        if not isinstance(result, dict):
            continue
        for item in result.get("datas") or []:
            if isinstance(item, dict):
                item = {**item, "_source_skill": skill}
                parsed = _iwencai_sector_to_flow_row(item)
                if parsed:
                    deduped[parsed["f14"]] = parsed
    return list(deduped.values())


async def _fetch_iwencai_market_diagnosis(
    inflow: list[dict[str, Any]],
    outflow: list[dict[str, Any]],
) -> str:
    queries = [
        "今日A股涨幅居前的行业板块，包含涨跌幅和成交额",
        "今日A股跌幅居前的行业板块，包含涨跌幅和成交额",
        "今日A股成交额放大且涨幅居前的行业板块，包含涨跌幅和成交额",
    ]
    results = await asyncio.gather(
        *(_run_astock_skill_query(query, limit=5) for query in queries),
        return_exceptions=True,
    )
    parsed = [item if isinstance(item, dict) else {} for item in results]
    strong = (parsed[0].get("datas") or [])[:3]
    weak = (parsed[1].get("datas") or [])[:2]
    volume = (parsed[2].get("datas") or [])[:2]

    if strong or weak or volume:
        parts = []
        if strong:
            parts.append("强势方向集中在" + "、".join(_format_iwencai_sector(row) for row in strong))
        if weak:
            parts.append("压力方向集中在" + "、".join(_format_iwencai_sector(row) for row in weak))
        if volume:
            parts.append("放量弹性优先看" + "、".join(_format_iwencai_sector(row) for row in volume))
        return "同花顺问财：" + "；".join(parts) + "。"

    fallback = _market_context_text(inflow, outflow)
    return f"同花顺问财暂未返回可用结果；本地资金流兜底显示：{fallback}。" if fallback else "同花顺问财暂未返回可用大盘诊断。"


def _volume_label(code: str, flow: float) -> str:
    klines = _fetch_sector_klines(code)
    flow_text = "主力净流入" if flow > 0 else "主力净流出" if flow < 0 else "主力资金数据缺失/不明显"
    if len(klines) < 6:
        return flow_text
    amounts = [float(row[6]) for row in klines if len(row) > 6]
    if len(amounts) < 6:
        return flow_text
    latest_amount = amounts[-1]
    avg_amount = sum(amounts[-6:-1]) / 5
    ratio = latest_amount / avg_amount if avg_amount else 1
    if ratio >= 1.25:
        return f"量能放大{ratio:.1f}倍，{flow_text}"
    if ratio <= 0.75:
        return f"量能萎缩至{ratio:.1f}倍，{flow_text}"
    return f"量能接近5日均量，{flow_text}"


def _expert_technical_analysis(
    *,
    name: str,
    code: str,
    change_pct: float,
    flow: float,
    market_context: str = "",
) -> str:
    klines = _fetch_sector_klines(code)
    technical = _kline_label(code, _technical_label(change_pct, flow))
    volume = _volume_label(code, flow)
    if len(klines) < 10:
        return f"{name}今天{change_pct:+.2f}%，{technical}；{volume}。数据长度不足，先按短线信号观察。"

    closes = [float(row[2]) for row in klines if len(row) > 2]
    amounts = [float(row[6]) for row in klines if len(row) > 6]
    latest = klines[-1]
    open_price = float(latest[1])
    close = float(latest[2])
    high = float(latest[3])
    low = float(latest[4])
    ma5 = _ma(closes, 5)
    ma10 = _ma(closes, 10)
    latest_amount = amounts[-1] if amounts else 0
    avg_amount = sum(amounts[-6:-1]) / 5 if len(amounts) >= 6 else 0
    ratio = latest_amount / avg_amount if avg_amount else 1
    candle = "收阳" if close >= open_price else "收阴"
    position = "靠近日内高位" if high and close >= low + (high - low) * 0.65 else "靠近日内低位" if high and close <= low + (high - low) * 0.35 else "位于日内中位"
    trend = "趋势偏强" if close > ma5 and close > ma10 else "趋势偏弱" if close < ma5 and close < ma10 else "趋势修复中"
    flow_text = "主力净流入" if flow > 0 else "主力净流出" if flow < 0 else "主力资金字段缺失，主要参考成交量"
    volume_text = "明显放量" if ratio >= 1.25 else "明显缩量" if ratio <= 0.75 else "接近5日均量"
    return (
        f"{name}今天{change_pct:+.2f}%，K线{candle}且{position}，{technical}，当前{trend}。"
        f"量能{volume_text}（约{ratio:.1f}倍5日均量），{flow_text}。"
        f"因此这里不是单纯看涨跌，重点看后续能否在5日线附近站稳并维持量能；"
        f"若放量上攻后回踩不破，才算更可靠的机会，若缩量反抽或继续失守均线则以防守为主。"
    )


def _fetch_fixed_source_row(
    group: dict[str, Any],
    include_kline: bool = False,
    market_context: str = "",
) -> dict[str, Any] | None:
    source = group.get("source")
    if not source:
        return None
    secid = source["secid"]
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "fields": "f57,f58,f43,f44,f45,f46,f47,f48,f60,f169,f170,f171,f124",
    }
    try:
        with httpx.Client(timeout=8.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
            data = client.get(url, params=params).json().get("data") or {}
    except Exception:
        return None
    if not data:
        return None

    pct = (data.get("f170") or 0) / 100
    amount_value = float(data.get("f48") or 0)
    volume_value = float(data.get("f47") or 0)
    activity_value = amount_value or volume_value
    activity_label = "成交额" if amount_value else "成交量"
    technical = _kline_label(secid, _technical_label(pct, 0)) if include_kline else _technical_label(pct, 0)
    volume = _volume_label(secid, 0) if include_kline else "量能待确认，主力资金数据缺失/不明显"
    expert = _expert_technical_analysis(
        name=source.get("name") or data.get("f58") or source.get("display_code"),
        code=secid,
        change_pct=pct,
        flow=0,
        market_context=market_context,
    ) if include_kline else ""
    return {
        "f12": source.get("display_code") or data.get("f57"),
        "f14": source.get("name") or data.get("f58") or source.get("display_code"),
        "f3": pct,
        "f62": 0,
        "amount": activity_value,
        "display_flow": f"{activity_label} {activity_value / 1e8:.1f}亿" if activity_value else f"{activity_label}暂无",
        "source_code": source.get("display_code") or data.get("f57"),
        "source_provider": source.get("provider", "东方财富"),
        "source_secid": secid,
        "technical_detail": technical,
        "volume_detail": volume,
        "expert_analysis": expert,
    }


def _opportunity_label(status: str, technical: str, flow: float) -> str:
    if status == "强" and ("站上" in technical or "中阳转强" in technical or "放量转强" in technical):
        return "有短线机会，但只适合回踩不破后小仓观察"
    if status == "吸" and flow > 0:
        return "有资金低吸迹象，等价格转强再考虑"
    if status == "弱" and ("跌破" in technical or "长阴" in technical):
        return "机会不足，先等止跌和资金回流"
    if status == "流":
        return "资金仍在流出，不适合主动加仓"
    return "信号一般，只观察不交易"


def _holding_names_for_group(group: dict[str, Any], holdings_by_code: dict[str, dict[str, Any]]) -> str:
    names = [
        holdings_by_code[code].get("name") or code
        for code in group.get("holding_codes", [])
        if code in holdings_by_code
    ]
    if not names:
        return group.get("holding_hint", "-")
    return "、".join(names[:2])


def build_focus_watch_rows(
    sectors: list[dict[str, Any]],
    holdings_by_code: dict[str, dict[str, Any]] | None = None,
    include_kline: bool = False,
    market_context: str = "",
) -> list[dict[str, Any]]:
    """Map user watch basket to current sector signals, ETF references, and holdings."""
    holdings_by_code = holdings_by_code or {}
    rows: list[dict[str, Any]] = []
    for group in WATCH_BASKET:
        skill_sectors = [sector for sector in sectors if sector.get("source_skill")]
        skill_match = _best_sector_match(skill_sectors, group["keywords"], group.get("preferred_names"))
        fixed_source = _fetch_fixed_source_row(group, include_kline, market_context) if include_kline else None
        matched = fixed_source or skill_match or _best_sector_match(
            sectors, group["keywords"], group.get("preferred_names")
        )
        change_pct = float(matched.get("f3") or 0) if matched else 0.0
        flow = float(matched.get("f62") or 0) if matched else 0.0
        sector_name = matched.get("f14") if matched else "暂无匹配"
        fallback_technical = _technical_label(change_pct, flow)
        if matched and matched.get("technical_detail"):
            technical = matched["technical_detail"]
        else:
            technical = _kline_label(matched.get("f12", ""), fallback_technical) if include_kline and matched else fallback_technical
        if matched and matched.get("volume_detail"):
            volume = matched["volume_detail"]
        else:
            volume = _volume_label(matched.get("f12", ""), flow) if include_kline and matched else ("主力净流入" if flow > 0 else "主力净流出" if flow < 0 else "主力资金不明显")
        if matched and matched.get("expert_analysis"):
            expert_analysis = matched["expert_analysis"]
        elif include_kline and matched:
            expert_analysis = _expert_technical_analysis(
                name=sector_name,
                code=matched.get("source_secid") or matched.get("f12", ""),
                change_pct=change_pct,
                flow=flow,
                market_context=market_context,
            )
        else:
            expert_analysis = f"{sector_name}{fallback_technical}，{volume}。"
        status = _status_label(change_pct, flow)
        amount_value = float(matched.get("amount") or 0) if matched else 0.0
        net_inflow = flow if matched and not matched.get("source_secid") and matched.get("f62") not in (None, "") else None
        rows.append({
            "name": group["name"],
            "priority": group.get("priority", "satellite"),
            "status": status,
            "matched_sector": sector_name,
            "source_code": matched.get("source_code") or matched.get("f12") if matched else "",
            "tracking_code": (group.get("source") or {}).get("display_code", ""),
            "source_provider": matched.get("source_provider", "东方财富") if matched else "",
            "source_secid": matched.get("source_secid", "") if matched else "",
            "change_pct": f"{change_pct:+.2f}%",
            "change_pct_value": change_pct,
            "flow": (matched.get("display_flow") if matched else None) or _flow_text(flow),
            "net_inflow": net_inflow,
            "turnover": amount_value,
            "bar": build_signal_bar(change_pct),
            "etf": group["etf"],
            "holding": _holding_names_for_group(group, holdings_by_code),
            "technical": technical,
            "volume": volume,
            "expert_analysis": expert_analysis,
            "opportunity": _opportunity_label(status, technical, flow),
            "score": change_pct + flow / 1e9,
            "source_skill": matched.get("source_skill", "东方财富公开行情") if matched else "",
        })
    return rows


def _summarize_focus_rows(rows: list[dict[str, Any]]) -> str:
    active = [row for row in rows if row.get("matched_sector") != "暂无匹配"]
    if not active:
        return "关注板块暂时没有明显信号，先等资金方向变清楚。"
    strongest = max(active, key=lambda row: row.get("score", 0))
    weakest = min(active, key=lambda row: row.get("score", 0))
    if all(row.get("score", 0) <= 0 for row in active):
        core_names = "、".join(row["name"] for row in rows[:2])
        return f"关注板块普遍走弱，今天先防守；重点等{core_names}止跌，不急补仓。"
    if strongest.get("score", 0) > 1:
        return f"{strongest['name']}最强，先看它是否能带动对应持仓；{weakest['name']}偏弱，暂不加仓。"
    return f"资金没有形成压倒性主线，重点盯{strongest['name']}能否继续放量。"


def _card_tone(rows: list[dict[str, Any]]) -> str:
    core_rows = [row for row in rows if row.get("priority") == "core"]
    if core_rows and all(row.get("score", 0) <= 0 for row in core_rows):
        return "red"
    if any(row.get("score", 0) > 1 for row in core_rows):
        return "green"
    return "orange"


def _decision_label(rows: list[dict[str, Any]]) -> str:
    core_rows = [row for row in rows if row.get("priority") == "core"]
    if core_rows and all(row.get("score", 0) <= 0 for row in core_rows):
        return "防守等待"
    if any(row.get("score", 0) > 1 for row in core_rows):
        return "小仓观察"
    return "只看不动"


def _risk_level(rows: list[dict[str, Any]]) -> str:
    weak_core = [row for row in rows if row.get("priority") == "core" and row.get("score", 0) <= -1]
    if len(weak_core) >= 3:
        return "高"
    if weak_core:
        return "中"
    return "低"


def _action_items(rows: list[dict[str, Any]]) -> list[str]:
    core_rows = [row for row in rows if row.get("priority") == "core"]
    if core_rows and all(row.get("score", 0) <= 0 for row in core_rows):
        return [
            "尾盘只看核心方向是否止跌、缩量，没确认前不主动补仓。",
            "若明天资金回流到光模块/通信或半导体，再重新评估低吸机会。",
        ]
    if any(row.get("score", 0) > 1 for row in core_rows):
        return [
            "强势方向只等回踩确认，不追分时急拉。",
            "点开机会方向详情，核对技术面、资金和消息催化，不只看涨幅。",
        ]
    return [
        "今天只做观察，等待资金方向从分歧变成连续流入。",
        "重点看核心板块能否站回5日线并保持量能。",
    ]


def build_sector_context_payload(
    *,
    market_snapshot: dict[str, Any],
    watch_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the auditable context saved for card follow-up questions."""
    evidence_rows = [
        row for row in watch_rows
        if row.get("matched_sector") and row.get("matched_sector") != "暂无匹配"
    ]
    sector_evidence = []
    for row in evidence_rows:
        sector_evidence.append({
            "name": row.get("name"),
            "matched_sector": row.get("matched_sector"),
            "tracking_code": row.get("tracking_code") or row.get("source_code"),
            "data_code": row.get("source_code"),
            "change_pct": row.get("change_pct_value"),
            "turnover": row.get("turnover"),
            "main_flow": row.get("net_inflow"),
            "opportunity_level": row.get("opportunity_level"),
            "opportunity": row.get("opportunity"),
            "technical": row.get("technical"),
            "volume": row.get("volume"),
            "related_holdings": row.get("holding"),
            "source_skill": row.get("source_skill"),
        })

    decision_summary = ""
    if evidence_rows:
        decision_summary = evidence_rows[0].get("opportunity") or _summarize_focus_rows(evidence_rows)

    skills: list[dict[str, str]] = []
    seen: set[str] = set()
    market_skill = market_snapshot.get("source_skill")
    if market_skill:
        skills.append({"skill": str(market_skill)})
        seen.add(str(market_skill))
    for row in evidence_rows:
        skill = row.get("source_skill")
        if skill and skill not in seen and skill != "东方财富公开行情":
            skills.append({"skill": str(skill)})
            seen.add(str(skill))

    return {
        "market_mood": market_snapshot,
        "context": {
            "market_mood": market_snapshot,
            "sector_evidence": sector_evidence,
        },
        "decision": {
            "summary": decision_summary,
            "opportunities": [
                {
                    "sector": row.get("name"),
                    "level": row.get("opportunity_level"),
                    "action": row.get("action"),
                    "reason": row.get("opportunity"),
                }
                for row in evidence_rows[:6]
            ],
        },
        "skill_calls": skills,
    }


async def _fetch_skill_note(rows: list[dict[str, Any]]) -> str:
    """Ask SkillBridge for optional sector-monitor diagnosis; never block the card."""
    try:
        result = await asyncio.wait_for(
            bridge.invoke_simple(
                "sector_monitor",
                params={
                    "sectors": [row["name"] for row in rows[:6]],
                    "focus": "只输出当前机会评价和技术面/量能关键点，中文短句，不要解释基金持仓映射",
                },
                cache_ttl=600,
            ),
            timeout=8,
        )
    except Exception:
        return ""
    if not result.success or not result.data:
        return ""
    data = result.data
    if isinstance(data, dict):
        raw = data.get("summary") or data.get("conclusion") or data.get("raw_output") or ""
    elif isinstance(data, list) and data:
        raw = str(data[0])
    else:
        raw = str(data)
    return raw.strip().replace("\n", " ")[:90]


async def build_live_sector_card(use_skill: bool = True) -> dict[str, Any]:
    """Create a compact card using current public sector flow and local holdings."""
    inflow = _fetch_eastmoney_sectors("f62", 1, 10)
    outflow = _fetch_eastmoney_sectors("f62", 0, 10)
    all_sectors = _fetch_eastmoney_all_sectors()

    top_inflow = inflow[0] if inflow else None
    top_outflow = outflow[0] if outflow else None
    semi = next((x for x in inflow if "半导体" in x.get("f14", "") or "芯片" in x.get("f14", "")), None)
    tech_risk = next((x for x in outflow if "电子" in x.get("f14", "") or "软件" in x.get("f14", "") or "互联网" in x.get("f14", "")), None)
    market_context = _market_context_text(inflow, outflow)
    market_snapshot = await fetch_market_mood_snapshot() if use_skill else {
        "state": "本地资金流观察",
        "summary": market_context or "暂无大盘情绪数据。",
    }
    market_diagnosis = market_snapshot.get("summary", "")
    iwencai_focus_rows = await _fetch_iwencai_focus_sector_rows() if use_skill else []

    holdings_by_code = _load_focus_holdings()
    watch_rows = build_focus_watch_rows(
        iwencai_focus_rows + all_sectors + inflow + outflow,
        holdings_by_code,
        include_kline=True,
        market_context="",
    )
    watch_rows = decide_sector_opportunities(watch_rows, market_snapshot)
    skill_note = await _fetch_skill_note(watch_rows) if use_skill else ""
    # Focus on the funds most connected to current tech/semiconductor/risk signals.
    focus_codes = ["001513", "006503", "021225", "004432", "013171"]
    holdings = []
    exposure_map = {
        "001513": "科技/信息产业",
        "006503": "半导体",
        "021225": "芯片/科创",
        "004432": "有色/周期",
        "013171": "港股互联网",
    }
    impact_map = {
        "001513": "仓位最高，科技主线强弱会直接影响组合",
        "006503": "半导体资金延续时直接受益",
        "021225": "直接跟芯片，但当前仓位很小",
        "004432": "周期方向偏弱时需要复盘",
        "013171": "仍是弱势仓位，单独看港股互联网修复",
    }
    for code in focus_codes:
        row = holdings_by_code.get(code)
        if not row:
            continue
        holdings.append({
            "name": row.get("name") or code,
            "code": code,
            "exposure": exposure_map.get(code, "相关持仓"),
            "impact": f"{impact_map.get(code, '关注相关板块持续性')}；盈亏 {row.get('unrealized_pnl_pct', 0):+.1f}%",
        })

    if semi:
        conclusion = _summarize_focus_rows(watch_rows)
    elif tech_risk:
        conclusion = "科技方向有分歧，先保护高仓位盈利。"
    else:
        conclusion = _summarize_focus_rows(watch_rows)

    drivers = []
    if top_inflow:
        drivers.append({
            "name": top_inflow.get("f14", "资金流入"),
            "value": _format_flow(top_inflow),
            "judgement": "最强主线",
        })
    if semi:
        drivers.append({
            "name": semi.get("f14", "半导体"),
            "value": _format_flow(semi),
            "judgement": "与你相关",
        })
    if top_outflow:
        drivers.append({
            "name": top_outflow.get("f14", "资金流出"),
            "value": _format_flow(top_outflow),
            "judgement": "风险侧",
        })

    card = build_sector_summary_card(
        title="板块监控测试卡",
        conclusion=conclusion,
        drivers=drivers,
        holdings=holdings,
        watch_rows=watch_rows,
        tone=_card_tone(watch_rows),
        decision=_decision_label(watch_rows),
        risk_level=_risk_level(watch_rows),
        skill_note=skill_note,
        market_diagnosis=market_diagnosis,
        actions=_action_items(watch_rows),
        source_note="数据源：同花顺问财 SkillHub（hithink-market-query / hithink-sector-selector / hithink-industry-query / hithink-zhishu-query）+ 东方财富公开板块/指数行情 + 养基宝真实持仓。仅供参考，不构成投资建议。",
    )
    card["_context_snapshot"] = build_sector_context_payload(
        market_snapshot=market_snapshot,
        watch_rows=watch_rows,
    )
    return card
