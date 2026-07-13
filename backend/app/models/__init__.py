"""Import all models for Alembic auto-discovery."""
from app.models.base import Base
from app.models.etf import ETFProfile
from app.models.sector import SectorProfile, SectorETFSMapping, SectorDailyStats
from app.models.fund import FundProfile, Watchlist, WatchlistItem
from app.models.position import Position, Transaction, InvestmentPlan
from app.models.alert import PriceAlert, AlertHistory
from app.models.signal import Signal
from app.models.kline import KlineCache, MarketCalendar, DailySummary
from app.models.feishu import FeishuConfig
from app.models.yangjibao import YangjibaoToken
from app.models.agent_context import AgentContextSnapshot
from app.models.evidence import Evidence, StoredDecision, GuardianRun

__all__ = [
    "Base",
    "ETFProfile",
    "SectorProfile", "SectorETFSMapping", "SectorDailyStats",
    "FundProfile", "Watchlist", "WatchlistItem",
    "Position", "Transaction", "InvestmentPlan",
    "PriceAlert", "AlertHistory",
    "Signal",
    "KlineCache", "MarketCalendar", "DailySummary",
    "FeishuConfig",
    "YangjibaoToken",
    "AgentContextSnapshot",
    "Evidence", "StoredDecision", "GuardianRun",
]
