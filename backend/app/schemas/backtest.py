"""Pydantic schemas for fund backtest APIs."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProsperityConfigSchema(BaseModel):
    score: float = 0.0
    min_score_to_buy: float = 7.0
    reasons: list[str] = Field(default_factory=list)


class BacktestConfigSchema(BaseModel):
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
    fund_category: Literal[
        "high_elastic",
        "medium_elastic",
        "defensive",
        "broad_index",
        "hong_kong_tech",
        "commodity",
        "bond",
    ] = "high_elastic"
    min_cash_pct: float = 0.1
    max_account_position_pct: float = 0.9
    max_single_position_pct: float = 0.5
    min_trade_position_pct: float = 0.02
    max_correlated_growth_exposure_pct: float = 0.6
    current_correlated_growth_exposure_pct: float = 0.0
    account_drawdown_redline_pct: float = 10.0
    prosperity: ProsperityConfigSchema = Field(default_factory=ProsperityConfigSchema)


class FundNavPointSchema(BaseModel):
    date: date
    nav: float


class SignalBarSchema(BaseModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float | None = None


class RedemptionFeeTierSchema(BaseModel):
    max_holding_days: int | None = None
    fee_rate: float


class FundFeeModelSchema(BaseModel):
    subscription_fee_rate: float = 0.0
    redemption_fee_tiers: list[RedemptionFeeTierSchema] = Field(default_factory=list)


class SignalDataSourceSchema(BaseModel):
    provider: Literal["westock"]
    symbol: str
    period: str = "day"
    limit: int = 200
    timeout: int = 30


class FundNavDataSourceSchema(BaseModel):
    provider: Literal["eastmoney"]
    fund_code: str
    start_date: date | None = None
    end_date: date | None = None
    page_size: int = 100
    timeout: int = 15


class EtfDataSourceSchema(BaseModel):
    """ETF 或指数独立回测数据源。

    close 价格同时作为 NAV（持仓估值）和信号线，无需单独的基金数据。
    适用场景：直接持有 ETF / 跟踪某指数本身。
    """
    provider: Literal["westock"]
    symbol: str                  # 如 sh515880、sh000001
    name: str = ""               # 显示名称，如"通信ETF"
    period: str = "day"
    limit: int = 500
    timeout: int = 30


class BacktestRunRequest(BaseModel):
    config: BacktestConfigSchema
    # 模式 A：基金 + 独立信号资产
    fund_nav: list[FundNavPointSchema] | None = None
    fund_nav_data_source: FundNavDataSourceSchema | None = None
    signal_bars: list[SignalBarSchema] | None = None
    signal_data_source: SignalDataSourceSchema | None = None
    # 模式 B：纯 ETF / 指数（close 同时充当 NAV 和信号）
    etf_data_source: EtfDataSourceSchema | None = None
    fee_model: FundFeeModelSchema = Field(default_factory=FundFeeModelSchema)
    strategy_text: str | None = None
    use_ai_strategy_compiler: bool = False
    test_mode: bool = False


class BacktestRunResponse(BaseModel):
    config: dict[str, Any]
    metrics: dict[str, Any]
    equity_curve: list[dict[str, Any]]
    signal_bars: list[dict[str, Any]]
    trades: list[dict[str, Any]]
    events: list[dict[str, Any]]
    strategy_profile: dict[str, Any]
    disclaimer: str
    execution_log_path: str | None = None  # 执行日志文件路径


class BacktestPresetItem(BaseModel):
    preset_id: str
    title: str
    fund_code: str
    fund_name: str
    signal_symbol: str
    signal_name: str
    signal_provider: str
    description: str
    etf_only: bool = False          # True = 纯ETF/指数模式，无独立基金数据


class BacktestPresetsResponse(BaseModel):
    presets: list[BacktestPresetItem]


class BacktestRunPresetRequest(BaseModel):
    preset_id: str
    start_date: date | None = None
    end_date: date | None = None
    initial_cash: float = 100_000.0
    initial_position_pct: float | None = None
    target_position_pct: float | None = None
    prosperity_score: float | None = None
    current_correlated_growth_exposure_pct: float = 0.0
    fund_nav_page_size: int = 100
    signal_limit: int = 200
    strategy_text: str | None = None
    use_ai_strategy_compiler: bool = False
    test_mode: bool = False
    fee_model: FundFeeModelSchema = Field(default_factory=FundFeeModelSchema)
