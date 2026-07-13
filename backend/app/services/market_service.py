"""Market data service - coordinates data fetching via SkillBridge."""
import logging
from datetime import date, datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.skills.bridge import bridge
from app.models.kline import KlineCache
from app.schemas.market import (
    QuoteResponse, QuotesListResponse, KlineItem, KlineResponse,
    IndexResponse, IndicesListResponse, SectorItem, HeatmapResponse,
    SectorRankingItem, SectorRankingResponse, SectorScoreDimension,
)
from app.services.market_data_provider import MarketDataProvider

logger = logging.getLogger(__name__)


class MarketService:
    """Service for market data: quotes, K-line, indices, sectors."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._data_provider = MarketDataProvider()

    # ── Quotes ──

    async def get_quotes(self, symbols: list[str]) -> QuotesListResponse:
        """Get real-time quotes for symbols."""
        result = await bridge.invoke_simple(
            "market_quote",
            params={"symbols": symbols},
            cache_ttl=30,
        )
        if result.success and isinstance(result.data, dict):
            quotes_data = result.data.get("quotes", result.data.get("data", []))
            if isinstance(quotes_data, list):
                return QuotesListResponse(quotes=[
                    QuoteResponse(
                        symbol=q.get("symbol", q.get("code", "")),
                        name=q.get("name", ""),
                        price=q.get("price", q.get("close", 0)),
                        change=q.get("change", 0),
                        change_pct=q.get("change_pct", q.get("changePct", 0)),
                        volume=q.get("volume", 0),
                        turnover=q.get("turnover"),
                        high=q.get("high"),
                        low=q.get("low"),
                        open=q.get("open"),
                        prev_close=q.get("prev_close", q.get("prevClose")),
                        timestamp=q.get("timestamp", datetime.now().isoformat()),
                    )
                    for q in quotes_data
                ])

        # Return empty if data unavailable
        return QuotesListResponse(quotes=[])

    # ── K-line ──

    async def get_kline(
        self, symbol: str, period: str = "daily", count: int = 120
    ) -> KlineResponse:
        """Get K-line data, checking cache first."""
        # Try SQLite cache first
        cached = await self._get_kline_from_cache(symbol, period, count)
        if cached and len(cached) >= count:
            return KlineResponse(symbol=symbol, period=period, klines=cached)

        # Fetch via SkillBridge
        result = await bridge.invoke_simple(
            "kline_data",
            params={"symbol": symbol, "period": period, "count": count},
            cache_ttl=300 if period == "daily" else 60,
        )
        if result.success:
            klines = self._parse_kline_data(result.data, count)
            await self._cache_kline_data(symbol, period, klines)
            return KlineResponse(symbol=symbol, period=period, klines=klines)

        return KlineResponse(symbol=symbol, period=period, klines=[])

    async def _get_kline_from_cache(
        self, symbol: str, period: str, count: int
    ) -> list[KlineItem]:
        """Read K-line from SQLite cache."""
        stmt = (
            select(KlineCache)
            .where(KlineCache.symbol == symbol, KlineCache.period == period)
            .order_by(KlineCache.timestamp.desc())
            .limit(count)
        )
        result = await self.db.execute(stmt)
        rows = result.scalars().all()
        return [
            KlineItem(
                timestamp=r.timestamp.isoformat(),
                open=r.open,
                high=r.high,
                low=r.low,
                close=r.close,
                volume=r.volume,
                amount=r.amount,
            )
            for r in reversed(rows)  # chronological order
        ]

    async def _cache_kline_data(self, symbol: str, period: str, klines: list[KlineItem]):
        """Store K-line data in SQLite cache."""
        for k in klines:
            ts = datetime.fromisoformat(k.timestamp) if k.timestamp else datetime.now()
            existing = await self.db.get(KlineCache, (symbol, period, ts))
            if not existing:
                self.db.add(KlineCache(
                    symbol=symbol,
                    period=period,
                    timestamp=ts,
                    open=k.open,
                    high=k.high,
                    low=k.low,
                    close=k.close,
                    volume=k.volume,
                    amount=k.amount,
                ))
        await self.db.flush()

    def _parse_kline_data(self, data, count: int) -> list[KlineItem]:
        """Parse K-line data from various response formats."""
        klines_raw = data.get("klines", data.get("data", []))
        if isinstance(klines_raw, dict):
            klines_raw = klines_raw.get("items", klines_raw.get("list", []))

        result = []
        for item in klines_raw[-count:]:
            if isinstance(item, dict):
                result.append(KlineItem(
                    timestamp=str(item.get("timestamp", item.get("date", ""))),
                    open=float(item.get("open", 0)),
                    high=float(item.get("high", 0)),
                    low=float(item.get("low", 0)),
                    close=float(item.get("close", 0)),
                    volume=float(item.get("volume", 0)),
                    amount=item.get("amount"),
                ))
        return result

    # ── Indices ──

    async def get_indices(self) -> IndicesListResponse:
        """Get major index quotes."""
        result = await bridge.invoke_simple("index_quote", cache_ttl=30)
        indices = []
        idx_map = {
            "000001": "上证指数", "000300": "沪深300",
            "399006": "创业板指", "000688": "科创50",
            "399001": "深证成指", "000016": "上证50",
        }
        if result.success and isinstance(result.data, list):
            for item in result.data:
                code = item.get("code", item.get("symbol", ""))
                indices.append(IndexResponse(
                    code=code,
                    name=idx_map.get(code, item.get("name", "")),
                    price=item.get("price", item.get("close", 0)),
                    change=item.get("change", 0),
                    change_pct=item.get("change_pct", item.get("changePct", 0)),
                ))
        return IndicesListResponse(indices=indices)

    # ── Sectors / Heatmap ──

    async def get_heatmap(self) -> HeatmapResponse:
        """Get sector performance data for heatmap.

        Falls back to MarketDataProvider when SkillBridge returns empty data.
        """
        result = await bridge.invoke_simple(
            "sector_data",
            params={"sector_type": "industry", "sort_by": "change_pct", "limit": 60},
            cache_ttl=300,
        )

        # Fallback to provider when bridge returns empty
        data = None
        if result.success and isinstance(result.data, list) and result.data:
            data = result.data
        else:
            data = self._data_provider.get_heatmap_sectors()

        sectors = []
        for item in data:
            sectors.append(SectorItem(
                code=item.get("code", ""),
                name=item.get("name", ""),
                sector_type=item.get("sector_type", "industry"),
                change_pct=item.get("change_pct", item.get("changePct", 0)),
                turnover=item.get("turnover"),
                volume=item.get("volume"),
                capital_flow=item.get("capital_flow", item.get("capitalFlow")),
                rank=item.get("rank"),
                rank_change=item.get("rank_change", item.get("rankChange")),
            ))
        return HeatmapResponse(sectors=sectors)

    # ── Market Diagnosis ──

    # Default global indices config
    GLOBAL_INDICES = [
        {"code": "000001", "name": "上证指数", "market": "A股"},
        {"code": "399001", "name": "深证成指", "market": "A股"},
        {"code": "000300", "name": "沪深300", "market": "A股"},
        {"code": "399006", "name": "创业板指", "market": "A股"},
        {"code": "000688", "name": "科创50", "market": "A股"},
        {"code": "HSI", "name": "恒生指数", "market": "港股"},
        {"code": "N225", "name": "日经225", "market": "日股"},
        {"code": "KOSPI", "name": "韩国KOSPI", "market": "韩股"},
        {"code": "IXIC", "name": "纳斯达克", "market": "美股"},
        {"code": "SPX", "name": "标普500", "market": "美股"},
        {"code": "DJI", "name": "道琼斯", "market": "美股"},
    ]

    async def get_global_indices(
        self, codes: list[str] | None = None
    ) -> IndicesListResponse:
        """Get global index quotes. Uses 指数数据查询 (#73) skill.

        Falls back to MarketDataProvider when SkillBridge returns empty data.
        """
        if codes is None:
            codes = [i["code"] for i in self.GLOBAL_INDICES]  # All indices

        result = await bridge.invoke_simple(
            "index_quote",
            params={"codes": codes},
            cache_ttl=30,
        )

        # Fallback to provider when bridge returns empty
        data = None
        if result.success and isinstance(result.data, list) and result.data:
            data = result.data
        else:
            data = self._data_provider.get_global_indices(codes)

        idx_map = {i["code"]: i for i in self.GLOBAL_INDICES}
        indices = []

        for item in data:
            code = item.get("code", item.get("symbol", ""))
            info = idx_map.get(code, {})
            indices.append(IndexResponse(
                code=code,
                name=info.get("name", item.get("name", "")),
                price=item.get("price", item.get("close", 0)),
                change=item.get("change", 0),
                change_pct=item.get("change_pct", item.get("changePct", 0)),
            ))

        return IndicesListResponse(indices=indices)

    async def get_diagnosis(self) -> "DiagnosisResponse":
        """Get comprehensive market diagnosis.

        Aggregates data from multiple skills:
        - 市场情绪分析 (#120): Fear & Greed, Put/Call, margin
        - 行业轮动分析 (#119): Sector momentum, heatmap
        - 沪深港通资金流分析 (#108): North/south capital flow
        """
        from app.schemas.market import (
            DiagnosisResponse, SentimentData,
            CapitalFlowItem, SectorRotationItem,
        )

        # Fetch from multiple skills in parallel where possible
        sentiment = await self._fetch_sentiment()
        top_inflow, top_outflow = await self._fetch_capital_flow()
        rotation = await self._fetch_sector_rotation()
        north_sectors = await self._fetch_north_bound_sectors()

        # Build AI summary
        summary_parts = []
        if sentiment and sentiment.fear_greed_index is not None:
            summary_parts.append(f"市场情绪: {sentiment.fear_greed_label}({sentiment.fear_greed_index})")
        if top_inflow:
            top3 = ", ".join(f"{s.sector_name}(+{s.net_flow:.0f}亿)" for s in top_inflow[:3])
            summary_parts.append(f"资金流入TOP3: {top3}")
        if rotation:
            leading = [s.sector_name for s in rotation if s.trend == "leading"][:3]
            if leading:
                summary_parts.append(f"领涨板块: {', '.join(leading)}")

        return DiagnosisResponse(
            sentiment=sentiment,
            top_capital_inflow=top_inflow,
            top_capital_outflow=top_outflow,
            sector_rotation=rotation,
            north_bound_sectors=north_sectors,
            summary="；".join(summary_parts) if summary_parts else "数据获取中...",
        )

    async def _fetch_sentiment(self) -> "SentimentData | None":
        """Fetch market sentiment via 市场情绪分析 (#120) skill.

        Falls back to MarketDataProvider when SkillBridge returns empty data.
        """
        from app.schemas.market import SentimentData
        result = await bridge.invoke_simple(
            "sentiment_analysis",
            cache_ttl=300,
        )

        data = (result.data
                if result.success and isinstance(result.data, dict)
                else self._data_provider.get_sentiment())

        if isinstance(data, dict):
            return SentimentData(
                fear_greed_index=data.get("fear_greed_index"),
                fear_greed_label=data.get("fear_greed_label", ""),
                put_call_ratio=data.get("put_call_ratio"),
                margin_balance=data.get("margin_balance"),
                short_balance=data.get("short_balance"),
                margin_short_ratio=data.get("margin_short_ratio"),
                turnover_rate=data.get("turnover_rate"),
                north_bound_flow=data.get("north_bound_flow"),
                updated_at=data.get("updated_at", ""),
            )
        return None

    async def _fetch_capital_flow(self) -> tuple[list["CapitalFlowItem"], list["CapitalFlowItem"]]:
        """Fetch sector capital flow via 行业轮动分析 (#119) skill.

        Falls back to MarketDataProvider when SkillBridge returns empty data.
        """
        from app.schemas.market import CapitalFlowItem
        result = await bridge.invoke_simple(
            "sector_rotation_analysis",
            cache_ttl=300,
        )

        data = (result.data
                if result.success and isinstance(result.data, dict)
                else self._data_provider.get_capital_flow())

        inflow, outflow = [], []
        if isinstance(data, dict):
            for item in data.get("capital_flow", data.get("sectors", [])):
                cf = CapitalFlowItem(
                    sector_name=item.get("name", item.get("sector_name", "")),
                    sector_code=item.get("code", ""),
                    net_flow=item.get("net_flow", item.get("capital_flow", 0)),
                    change_pct=item.get("change_pct", 0),
                    large_order_flow=item.get("large_order_flow"),
                    consecutive_days=item.get("consecutive_days"),
                    rank=item.get("rank", 0),
                )
                if cf.net_flow > 0:
                    inflow.append(cf)
                else:
                    outflow.append(cf)
        inflow.sort(key=lambda x: x.net_flow, reverse=True)
        outflow.sort(key=lambda x: x.net_flow)
        return inflow[:5], outflow[:5]

    async def _fetch_sector_rotation(self) -> list["SectorRotationItem"]:
        """Fetch sector rotation via 行业轮动监控 (#187) skill.

        Falls back to MarketDataProvider when SkillBridge returns empty data.
        """
        from app.schemas.market import SectorRotationItem
        result = await bridge.invoke_simple(
            "sector_rotation_analysis",
            cache_ttl=600,
        )

        data = (result.data
                if result.success and isinstance(result.data, list) and result.data
                else self._data_provider.get_sector_rotation())

        items = []
        if isinstance(data, list):
            for item in data:
                items.append(SectorRotationItem(
                    sector_name=item.get("name", item.get("sector_name", "")),
                    sector_code=item.get("code", ""),
                    momentum_score=item.get("momentum_score", 0),
                    heat_level=item.get("heat_level", item.get("hot_level", 0)),
                    trend=item.get("trend", ""),
                    change_1w=item.get("change_1w"),
                    change_1m=item.get("change_1m"),
                    capital_flow_5d=item.get("capital_flow_5d"),
                ))
        return items

    async def _fetch_north_bound_sectors(self) -> list["CapitalFlowItem"]:
        """Fetch north-bound capital flow via 沪深港通资金流分析 (#108) skill.

        Falls back to MarketDataProvider when SkillBridge returns empty data.
        """
        from app.schemas.market import CapitalFlowItem
        result = await bridge.invoke_simple(
            "north_bound_flow",
            cache_ttl=300,
        )

        data = (result.data
                if result.success and isinstance(result.data, list) and result.data
                else self._data_provider.get_north_bound_sectors())

        items = []
        if isinstance(data, list):
            for item in data:
                items.append(CapitalFlowItem(
                    sector_name=item.get("name", item.get("sector_name", "")),
                    sector_code=item.get("code", ""),
                    net_flow=item.get("net_flow", item.get("capital_flow", 0)),
                    change_pct=item.get("change_pct", 0),
                    consecutive_days=item.get("consecutive_days"),
                ))
        items.sort(key=lambda x: x.net_flow, reverse=True)
        return items[:5]

    # ── Sector Ranking (Multi-dimensional Scoring) ──

    async def get_sector_rankings(self) -> SectorRankingResponse:
        """Get real-time sector rankings with multi-dimensional scoring.

        Hybrid approach: fetches live data from hithink-sector-selector skill,
        then layers SectorScoringEngine AI scoring on top.
        Falls back to mock data if the skill is unavailable.
        """
        from app.services.sector_scoring_engine import SectorScoringEngine

        skill_rows = await self._fetch_sectors_from_skill()
        if skill_rows:
            sectors_to_score = skill_rows
            logger.info(f"Sector rankings: using skill data ({len(skill_rows)} sectors)")
        else:
            mock_rows = self._get_mock_sector_data()
            sectors_to_score = [
                {
                    "code": r.get("source_code", ""),
                    "name": r.get("name", ""),
                    "matched_sector": r.get("matched_sector", ""),
                    "change_pct": r.get("change_pct_value", 0),
                    "flow_value": r.get("net_inflow", 0),
                    "turnover": r.get("turnover", 0),
                    "technical": r.get("technical", ""),
                    "volume": r.get("volume", ""),
                    "opportunity": r.get("opportunity", ""),
                }
                for r in mock_rows
            ]
            logger.info(f"Sector rankings: skill unavailable, using mock ({len(sectors_to_score)} sectors)")

        # Score all sectors
        scored = SectorScoringEngine.score_multiple(sectors_to_score)

        # Build response items
        all_ranking_items = []
        strong_items = []
        watch_items = []
        weak_items = []

        for idx, score in enumerate(scored, 1):
            item = SectorRankingItem(
                rank=idx,
                code=score.code,
                name=score.name,
                matched_sector=score.matched_sector,
                change_pct=score.change_pct,
                flow_value=score.flow_value,
                turnover=score.turnover,
                base_score=round(score.composite_score, 2),
                breakdown=SectorScoreDimension(
                    price=round(score.price_score, 2),
                    flow=round(score.flow_score, 2),
                    heat=round(score.heat_score, 2),
                    momentum=round(score.momentum_score, 2),
                ),
                signal=score.signal,
                confidence=round(score.confidence, 2),
                technical=score.technical,
                volume=score.volume,
                opportunity=score.opportunity or f"{score.name} 综合评分 {score.composite_score:.1f}/10",
            )
            all_ranking_items.append(item)

            if score.signal == "STRONG":
                strong_items.append(item)
            elif score.signal == "WATCH":
                watch_items.append(item)
            else:
                weak_items.append(item)

        return SectorRankingResponse(
            timestamp=datetime.now().isoformat(),
            total_sectors=len(scored),
            strong_signals=strong_items[:5],
            watch_signals=watch_items[:10],
            weak_signals=weak_items[:5],
            all_rankings=all_ranking_items,
        )

    async def _fetch_sectors_from_skill(self) -> list[dict]:
        """Fetch live sector data via hithink-sector-selector skill.

        Returns list of dicts ready for SectorScoringEngine, or empty list on failure.
        """
        result = await bridge.invoke_simple(
            "sector_select",
            params={
                "sector_type": "industry",
                "sort_by": "net_flow",
                "limit": 50,
            },
            cache_ttl=300,
        )

        if not result.success or not result.data:
            logger.warning(f"sector_select skill failed: {result.error}")
            return []

        raw = result.data
        if isinstance(raw, dict):
            raw = raw.get("sectors", raw.get("data", raw.get("items", [])))
        if not isinstance(raw, list):
            logger.warning(f"Unexpected sector_select response type: {type(raw)}")
            return []

        sectors = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = (
                item.get("sector_name")
                or item.get("name")
                or item.get("板块名称", "")
            )
            code = (
                item.get("sector_code")
                or item.get("code")
                or item.get("板块代码", "")
            )
            change_pct = float(
                item.get("change_pct")
                or item.get("涨跌幅")
                or item.get("changePct", 0)
                or 0
            )
            # net flow: prefer 亿元, convert from 万元 if needed
            flow_raw = (
                item.get("net_flow_amount")
                or item.get("net_flow")
                or item.get("主力净流入")
                or item.get("capital_flow", 0)
                or 0
            )
            flow_value = float(flow_raw)
            # Values above 10000 are likely in 万元 → convert to 亿元
            if abs(flow_value) > 10000:
                flow_value = flow_value / 10000

            turnover_raw = (
                item.get("turnover")
                or item.get("成交额")
                or item.get("amount", 0)
                or 0
            )
            turnover = float(turnover_raw)
            if turnover > 100000:
                turnover = turnover / 10000

            consecutive = item.get("consecutive_days") or item.get("连续流入天数", 0)
            heat = item.get("heat_level") or item.get("热度", 0)

            sectors.append({
                "code": str(code),
                "name": str(name),
                "matched_sector": str(name),
                "change_pct": change_pct,
                "flow_value": flow_value,
                "turnover": turnover,
                "technical": item.get("technical") or item.get("技术面", ""),
                "volume": item.get("volume") or item.get("成交量", ""),
                "opportunity": item.get("opportunity") or item.get("机会评价", ""),
                "consecutive_days": int(consecutive) if consecutive else 0,
                "heat_level": int(heat) if heat else 0,
            })

        logger.info(f"_fetch_sectors_from_skill: parsed {len(sectors)} sectors")
        return sectors

    @staticmethod
    def _get_mock_sector_data() -> list[dict]:
        """Return realistic mock sector data for demo/fallback.

        Note: net_inflow and turnover are in units of 100万元 (亿元)
        Examples:
        - net_inflow: 82.0 → 82亿元
        - turnover: 1200.0 → 1200亿元
        """
        return [
            {
                "name": "半导体",
                "source_code": "931743",
                "matched_sector": "半导体设备",
                "change_pct_value": 3.2,
                "net_inflow": 8.2,  # 8.2亿元
                "turnover": 120.5,  # 120.5亿元
                "technical": "放量转强，站上5日线",
                "volume": "明显放大",
                "opportunity": "有短线机会，但只适合回踩不破后小仓观察",
            },
            {
                "name": "光模块/通信",
                "source_code": "931160",
                "matched_sector": "通信设备",
                "change_pct_value": 2.8,
                "net_inflow": 6.5,  # 6.5亿元
                "turnover": 98.0,   # 98亿元
                "technical": "中阳收盘，5日线上方",
                "volume": "量能温和放大",
                "opportunity": "资金持续净流入，值得关注",
            },
            {
                "name": "电池",
                "source_code": "931719",
                "matched_sector": "中证电池",
                "change_pct_value": -1.2,
                "net_inflow": -3.5,  # -3.5亿元 (净流出)
                "turnover": 45.0,    # 45亿元
                "technical": "跌破5日线，需警惕",
                "volume": "缩量下跌",
                "opportunity": "机会不足，先等止跌信号",
            },
            {
                "name": "有色金属",
                "source_code": "000819",
                "matched_sector": "有色金属",
                "change_pct_value": 0.8,
                "net_inflow": 2.8,   # 2.8亿元
                "turnover": 62.0,    # 62亿元
                "technical": "震荡走势",
                "volume": "量能平稳",
                "opportunity": "信号一般，等价格方向确认",
            },
            {
                "name": "港股互联网",
                "source_code": "H30533",
                "matched_sector": "中国互联网50",
                "change_pct_value": -2.1,
                "net_inflow": -4.8,  # -4.8亿元 (净流出)
                "turnover": 38.0,    # 38亿元
                "technical": "长阴走弱",
                "volume": "资金持续流出",
                "opportunity": "资金仍在流出，不适合主动加仓",
            },
            {
                "name": "医药生物",
                "source_code": "931170",
                "matched_sector": "医药生物",
                "change_pct_value": 1.5,
                "net_inflow": 5.2,   # 5.2亿元
                "turnover": 75.5,    # 75.5亿元
                "technical": "缓和上升，需要确认",
                "volume": "量能温和",
                "opportunity": "回踩支撑后可关注",
            },
            {
                "name": "新能源车",
                "source_code": "931720",
                "matched_sector": "新能源汽车",
                "change_pct_value": -0.5,
                "net_inflow": 1.2,   # 1.2亿元
                "turnover": 55.3,    # 55.3亿元
                "technical": "震荡偏弱",
                "volume": "成交量平稳",
                "opportunity": "等待明确信号，不急入场",
            },
        ]
