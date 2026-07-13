"""Market data provider - realistic simulated data for development/demo.

Used as a fallback when SkillBridge strategies return empty data.
Generates data with small random variations per call to simulate
real-time market movements. Uses a date-based seed for consistency
within a session (same day = same RNG sequence).
"""
import logging
import random
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)


class MarketDataProvider:
    """Provides realistic simulated market data for the Dashboard.

    Each method returns data in the same dict/list format that the
    SkillBridge strategies would return, so it plugs directly into
    the existing MarketService parsing code.

    A date-seeded RNG ensures values are deterministic within a day
    but vary day-to-day. Each call produces slightly different values
    as the RNG advances.
    """

    # ── Global Indices ──────────────────────────────────────────────

    INDEX_BASES: dict[str, dict[str, Any]] = {
        "000001": {"name": "上证指数", "market": "A股", "price": 3250.0},
        "399001": {"name": "深证成指", "market": "A股", "price": 10200.0},
        "000300": {"name": "沪深300", "market": "A股", "price": 3890.0},
        "399006": {"name": "创业板指", "market": "A股", "price": 2180.0},
        "000688": {"name": "科创50", "market": "A股", "price": 1025.0},
        "000016": {"name": "上证50", "market": "A股", "price": 2580.0},
        "HSI":    {"name": "恒生指数", "market": "港股", "price": 18200.0},
        "N225":   {"name": "日经225", "market": "日股", "price": 38500.0},
        "KOSPI":  {"name": "韩国KOSPI", "market": "韩股", "price": 2780.0},
        "IXIC":   {"name": "纳斯达克", "market": "美股", "price": 18500.0},
        "SPX":    {"name": "标普500", "market": "美股", "price": 6050.0},
        "DJI":    {"name": "道琼斯", "market": "美股", "price": 39200.0},
    }

    # ── Capital Flow Sectors ────────────────────────────────────────

    INFLOW_SECTORS: list[dict[str, Any]] = [
        {"name": "半导体", "flow": 12.0, "pct": 2.8},
        {"name": "新能源", "flow": 8.0, "pct": 1.5},
        {"name": "AI", "flow": 15.0, "pct": 3.2},
        {"name": "医药", "flow": 5.0, "pct": 1.0},
        {"name": "消费电子", "flow": 6.0, "pct": 2.1},
    ]

    OUTFLOW_SECTORS: list[dict[str, Any]] = [
        {"name": "地产", "flow": -8.0, "pct": -1.8},
        {"name": "银行", "flow": -5.0, "pct": -0.8},
        {"name": "钢铁", "flow": -3.0, "pct": -0.5},
        {"name": "煤炭", "flow": -2.0, "pct": -0.3},
        {"name": "纺织", "flow": -1.0, "pct": -0.2},
    ]

    # ── Sector Rotation ─────────────────────────────────────────────

    ROTATION_SECTORS: list[dict[str, Any]] = [
        {"name": "人工智能", "momentum": 85, "heat": 5, "trend": "leading"},
        {"name": "半导体",   "momentum": 78, "heat": 5, "trend": "leading"},
        {"name": "新能源",   "momentum": 65, "heat": 4, "trend": "improving"},
        {"name": "消费电子", "momentum": 60, "heat": 4, "trend": "improving"},
        {"name": "医药",     "momentum": 52, "heat": 3, "trend": "improving"},
        {"name": "银行",     "momentum": 45, "heat": 2, "trend": "weakening"},
        {"name": "地产",     "momentum": 30, "heat": 2, "trend": "weakening"},
        {"name": "钢铁",     "momentum": 25, "heat": 1, "trend": "lagging"},
    ]

    # ── North-bound Flow ────────────────────────────────────────────

    NB_STOCKS: list[dict[str, Any]] = [
        {"name": "宁德时代", "flow": 8.5},
        {"name": "贵州茅台", "flow": 6.2},
        {"name": "美的集团", "flow": 4.8},
        {"name": "招商银行", "flow": 3.5},
        {"name": "中国平安", "flow": 2.8},
    ]

    # ── Heatmap Sectors ─────────────────────────────────────────────

    HEATMAP_SECTORS: list[str] = [
        "人工智能", "半导体", "新能源", "消费电子", "医药",
        "银行", "地产", "钢铁", "煤炭", "纺织",
        "食品饮料", "家电", "汽车", "军工", "证券",
        "保险", "有色", "化工", "机械", "电力",
        "通信", "软件", "传媒", "旅游", "零售",
        "建筑", "建材", "农业", "环保", "物流",
    ]

    def __init__(self) -> None:
        # Deterministic per-day seed so data is consistent within a session
        self._rng = random.Random(date.today().toordinal())
        logger.info(
            "MarketDataProvider initialized (seed=%d)",
            date.today().toordinal(),
        )

    # ── Helpers ─────────────────────────────────────────────────────

    def _jitter(self, base: float, pct: float = 0.005) -> float:
        """Apply random variation of ±pct (%) to *base*."""
        return base * (1 + self._rng.uniform(-pct, pct))

    def _change_from_price(self, price: float) -> tuple[float, float]:
        """Generate a realistic (change, change_pct) pair from a price."""
        change_pct = round(self._rng.uniform(-2.5, 2.5), 2)
        change = round(price * change_pct / 100, 2)
        return change, change_pct

    def _shuffle(self, items: list[str]) -> list[str]:
        """Return a shuffled copy of a list, advancing the RNG."""
        shuffled = items[:]
        self._rng.shuffle(shuffled)
        return shuffled

    # ── Global Indices ──────────────────────────────────────────────

    def get_global_indices(
        self, codes: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Return realistic index quotes in bridge format.

        Each item: {code, name, price, close, change, change_pct, changePct, market}
        """
        if codes is None:
            codes = list(self.INDEX_BASES.keys())

        indices: list[dict[str, Any]] = []
        for code in codes:
            info = self.INDEX_BASES.get(code)
            if info is None:
                continue
            price = round(self._jitter(info["price"]), 2)
            change, change_pct = self._change_from_price(price)
            indices.append({
                "code": code,
                "name": info["name"],
                "price": price,
                "close": price,
                "change": change,
                "change_pct": change_pct,
                "changePct": change_pct,
                "market": info["market"],
            })
        return indices

    # ── Sentiment ───────────────────────────────────────────────────

    def get_sentiment(self) -> dict[str, Any]:
        """Return realistic sentiment data in bridge format.

        Fields match what 市场情绪分析 (#120) skill would return.
        """
        fear_greed = round(self._rng.uniform(43, 57))
        if fear_greed <= 25:
            label = "极度恐惧"
        elif fear_greed <= 40:
            label = "恐惧"
        elif fear_greed <= 60:
            label = "中性"
        elif fear_greed <= 75:
            label = "贪婪"
        else:
            label = "极度贪婪"

        margin_balance = round(self._jitter(15200, 0.012), 1)
        short_balance = round(self._jitter(980, 0.025), 1)

        return {
            "fear_greed_index": fear_greed,
            "fear_greed_label": label,
            "put_call_ratio": round(self._rng.uniform(0.75, 0.95), 2),
            "margin_balance": margin_balance,
            "short_balance": short_balance,
            "margin_short_ratio": round(
                margin_balance / short_balance if short_balance else 15.5, 2
            ),
            "turnover_rate": round(self._rng.uniform(0.8, 1.5), 2),
            "north_bound_flow": round(self._rng.uniform(-50, 50), 1),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    # ── Capital Flow ────────────────────────────────────────────────

    def get_capital_flow(self) -> dict[str, Any]:
        """Return realistic sector capital flow in bridge format.

        Returns {"sectors": [...]} so it works with existing parsing
        that checks ``data.get("capital_flow", data.get("sectors", []))``.
        """
        sectors: list[dict[str, Any]] = []

        for idx, s in enumerate(self.INFLOW_SECTORS):
            flow = round(self._jitter(s["flow"], 0.3), 1)
            sectors.append({
                "name": s["name"],
                "sector_name": s["name"],
                "code": f"BK{1001 + idx}",
                "net_flow": flow,
                "capital_flow": flow,
                "change_pct": round(self._jitter(s["pct"], 0.5), 2),
                "large_order_flow": round(flow * self._rng.uniform(0.3, 0.6), 1),
                "consecutive_days": self._rng.randint(1, 5),
                "rank": idx + 1,
            })

        for idx, s in enumerate(self.OUTFLOW_SECTORS):
            flow = round(self._jitter(s["flow"], 0.3), 1)
            sectors.append({
                "name": s["name"],
                "sector_name": s["name"],
                "code": f"BK{2001 + idx}",
                "net_flow": flow,
                "capital_flow": flow,
                "change_pct": round(self._jitter(s["pct"], 0.5), 2),
                "large_order_flow": round(flow * self._rng.uniform(0.3, 0.6), 1),
                "consecutive_days": -self._rng.randint(1, 3),
                "rank": idx + len(self.INFLOW_SECTORS) + 1,
            })

        return {"sectors": sectors}

    # ── Sector Rotation ─────────────────────────────────────────────

    def get_sector_rotation(self) -> list[dict[str, Any]]:
        """Return realistic sector rotation data in bridge format.

        Each item: {name, sector_name, code, momentum_score, heat_level,
                     hot_level, trend, change_1w, change_1m, capital_flow_5d}
        """
        items: list[dict[str, Any]] = []
        for s in self.ROTATION_SECTORS:
            score = max(0, min(100, round(self._jitter(s["momentum"], 0.12))))
            items.append({
                "name": s["name"],
                "sector_name": s["name"],
                "code": f"BK90{len(items) + 1}",
                "momentum_score": score,
                "heat_level": s["heat"],
                "hot_level": s["heat"],
                "trend": s["trend"],
                "change_1w": round(self._rng.uniform(-3, 8), 2),
                "change_1m": round(self._rng.uniform(-5, 15), 2),
                "capital_flow_5d": round(self._rng.uniform(-10, 20), 1),
            })
        return items

    # ── North-bound Capital Flow ────────────────────────────────────

    def get_north_bound_sectors(self) -> list[dict[str, Any]]:
        """Return realistic north-bound flow data in bridge format.

        Each item: {name, sector_name, code, net_flow, capital_flow,
                     change_pct, consecutive_days}
        """
        items: list[dict[str, Any]] = []
        for idx, s in enumerate(self.NB_STOCKS):
            flow = round(self._jitter(s["flow"], 0.2), 1)
            items.append({
                "name": s["name"],
                "sector_name": s["name"],
                "code": f"STOCK_{idx + 1:02d}",
                "net_flow": flow,
                "capital_flow": flow,
                "change_pct": round(self._rng.uniform(0.5, 3.0), 2),
                "consecutive_days": self._rng.randint(1, 5),
            })
        return items

    # ── Heatmap Sectors ─────────────────────────────────────────────

    def get_heatmap_sectors(self) -> list[dict[str, Any]]:
        """Return realistic sector heatmap data in bridge format.

        Each item: {code, name, sector_type, change_pct, changePct,
                     turnover, volume, capital_flow, capitalFlow,
                     rank, rank_change, rankChange}
        """
        shuffled = self._shuffle(self.HEATMAP_SECTORS)
        items: list[dict[str, Any]] = []
        for idx, name in enumerate(shuffled):
            change_pct = round(self._rng.uniform(-5, 5), 2)
            flow = round(self._rng.uniform(-10, 15), 1)
            items.append({
                "code": f"BK{8001 + idx}",
                "name": name,
                "sector_type": "industry",
                "change_pct": change_pct,
                "changePct": change_pct,
                "turnover": round(self._rng.uniform(10, 500), 1),
                "volume": round(self._rng.uniform(100, 5000), 0),
                "capital_flow": flow,
                "capitalFlow": flow,
                "rank": idx + 1,
                "rank_change": self._rng.randint(-3, 3),
                "rankChange": self._rng.randint(-3, 3),
            })
        return items
