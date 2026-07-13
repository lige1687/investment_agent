"""Typed domain objects for fund backtests."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

FundCategory = Literal[
    "high_elastic",
    "medium_elastic",
    "defensive",
    "broad_index",
    "hong_kong_tech",
    "commodity",
    "bond",
]


@dataclass(frozen=True)
class FundNavPoint:
    """Daily fund net asset value used for T+1 execution and valuation."""

    date: date
    nav: float


@dataclass(frozen=True)
class SignalBar:
    """Daily OHLCV bar for the ETF/index/sector used as strategy signal."""

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float | None = None


@dataclass(frozen=True)
class ProsperityConfig:
    """Industry prosperity gate for buy decisions."""

    score: float = 0.0
    min_score_to_buy: float = 7.0
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BacktestConfig:
    """Runtime configuration for one fund backtest."""

    fund_code: str
    fund_name: str
    signal_code: str
    signal_name: str
    initial_cash: float = 100_000.0
    initial_position_pct: float = 0.0
    target_position_pct: float = 0.2
    buy_ma_window: int = 20
    buy_volume_window: int = 20
    buy_volume_ratio: float = 1.2
    buy_stand_days: int = 2
    expma_window: int = 15
    breakdown_volume_ratio: float = 1.5
    profit_drawdown_trigger_pct: float = 8.0
    stop_loss_trigger_pct: float = 10.0
    observe_days: int = 3
    buy_cooldown_days: int = 10
    sell_cooldown_days: int = 10
    weak_buy_allows_trade: bool = False
    first_entry_plan_ratio: float = 0.5
    fund_category: FundCategory = "high_elastic"
    min_cash_pct: float = 0.1
    max_account_position_pct: float = 0.9
    max_single_position_pct: float = 0.5
    min_trade_position_pct: float = 0.02
    max_correlated_growth_exposure_pct: float = 0.6
    current_correlated_growth_exposure_pct: float = 0.0
    account_drawdown_redline_pct: float = 10.0
    prosperity: ProsperityConfig = field(default_factory=ProsperityConfig)


@dataclass(frozen=True)
class PortfolioSnapshot:
    date: date
    cash: float
    shares: float
    nav: float
    equity: float
    position_pct: float
    cumulative_return_pct: float
    peak_return_pct: float


@dataclass(frozen=True)
class TradeRecord:
    date: date
    action: Literal["buy", "sell"]
    nav: float
    shares: float
    cash_delta: float
    fee: float
    reason: str
    event_type: str
    batch_type: str | None = None
    batch_cost_nav: float | None = None
    batch_return_pct: float | None = None
    batch_peak_return_pct: float | None = None


@dataclass(frozen=True)
class BacktestMetrics:
    total_return_pct: float
    annual_return_pct: float
    max_drawdown_pct: float
    trade_count: int
    final_equity: float


@dataclass(frozen=True)
class BacktestResult:
    config: BacktestConfig
    metrics: BacktestMetrics
    equity_curve: list[PortfolioSnapshot]
    trades: list[TradeRecord]
    events: list[dict[str, Any]]
    execution_log_path: str | None = None  # 执行日志文件路径
