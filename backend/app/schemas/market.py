"""Market data Pydantic schemas."""
from datetime import datetime
from pydantic import BaseModel, Field


class QuoteResponse(BaseModel):
    symbol: str
    name: str = ""
    price: float = 0.0
    change: float = 0.0
    change_pct: float = 0.0
    volume: float = 0.0
    turnover: float | None = None
    high: float | None = None
    low: float | None = None
    open: float | None = None
    prev_close: float | None = None
    timestamp: str = ""

    class Config:
        from_attributes = True


class QuotesListResponse(BaseModel):
    quotes: list[QuoteResponse]


class KlineItem(BaseModel):
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float | None = None


class KlineResponse(BaseModel):
    symbol: str
    period: str
    klines: list[KlineItem]


class IndexResponse(BaseModel):
    code: str
    name: str
    price: float = 0.0
    change: float = 0.0
    change_pct: float = 0.0


class IndicesListResponse(BaseModel):
    indices: list[IndexResponse]


class SectorItem(BaseModel):
    code: str
    name: str
    sector_type: str = ""
    change_pct: float = 0.0
    turnover: float | None = None
    volume: float | None = None
    capital_flow: float | None = None
    rank: int | None = None
    rank_change: int | None = None


class HeatmapResponse(BaseModel):
    sectors: list[SectorItem]


# ── Market Diagnosis Schemas ──

class SentimentData(BaseModel):
    """Market sentiment indicators."""
    fear_greed_index: int | None = None  # 0-100, <25 extreme fear, >75 extreme greed
    fear_greed_label: str = ""  # "极度恐惧"/"恐惧"/"中性"/"贪婪"/"极度贪婪"
    put_call_ratio: float | None = None
    margin_balance: float | None = None  # 融资余额 (亿元)
    short_balance: float | None = None   # 融券余额 (亿元)
    margin_short_ratio: float | None = None  # 融资融券比
    turnover_rate: float | None = None   # 换手率
    north_bound_flow: float | None = None  # 北向资金净流入 (亿元)
    updated_at: str = ""


class CapitalFlowItem(BaseModel):
    """Capital flow into a sector."""
    sector_name: str
    sector_code: str = ""
    net_flow: float = 0.0  # 净流入 (亿元)
    change_pct: float = 0.0
    large_order_flow: float | None = None  # 大单净流入
    consecutive_days: int | None = None  # 连续流入天数
    rank: int = 0


class SectorRotationItem(BaseModel):
    """Sector rotation analysis."""
    sector_name: str
    sector_code: str = ""
    momentum_score: float = 0.0  # 动量评分
    heat_level: int = 0  # 热度 1-5
    trend: str = ""  # "leading"/"improving"/"weakening"/"lagging"
    change_1w: float | None = None
    change_1m: float | None = None
    capital_flow_5d: float | None = None  # 5日资金净流入


class DiagnosisResponse(BaseModel):
    """Complete market diagnosis."""
    sentiment: SentimentData | None = None
    top_capital_inflow: list[CapitalFlowItem] = []
    top_capital_outflow: list[CapitalFlowItem] = []
    sector_rotation: list[SectorRotationItem] = []
    north_bound_sectors: list[CapitalFlowItem] = []  # 北向资金加仓板块
    summary: str = ""  # AI-generated diagnosis summary


# ── Sector Ranking Schemas ──

class SectorScoreDimension(BaseModel):
    """Detailed score breakdown."""
    price: float = 0.0  # 技术面 (0-10)
    flow: float = 0.0   # 资金面 (0-10)
    heat: float = 0.0   # 热度面 (0-10)
    momentum: float = 0.0  # 动量面 (0-10)


class SectorRankingItem(BaseModel):
    """Single sector ranking entry with detailed scores."""
    rank: int = 0
    code: str
    name: str
    matched_sector: str = ""  # 实际匹配的板块名称
    change_pct: float = 0.0  # 涨跌幅%
    flow_value: float = 0.0  # 主力净流入 (亿元)
    turnover: float = 0.0  # 成交额 (亿元)

    # Comprehensive scoring
    base_score: float = 0.0  # 综合评分 (0-10)
    breakdown: SectorScoreDimension  # 维度分数

    # Signal & confidence
    signal: str = "WATCH"  # STRONG/WATCH/WEAK/AVOID
    confidence: float = 0.0  # 信号置信度 (0-1)

    # Supporting technical analysis
    technical: str = ""  # 技术面评价
    volume: str = ""  # 量能评价
    opportunity: str = ""  # 机会评价

    # Related holdings (可选)
    related_holdings: list[str] = []  # 相关持仓基金代码


class SectorRankingResponse(BaseModel):
    """Full sector ranking response."""
    timestamp: str = ""
    total_sectors: int = 0
    strong_signals: list[SectorRankingItem] = []  # 信号强的 TOP
    watch_signals: list[SectorRankingItem] = []   # 观察信号的
    weak_signals: list[SectorRankingItem] = []    # 弱势信号的
    all_rankings: list[SectorRankingItem] = []    # 全部排序
