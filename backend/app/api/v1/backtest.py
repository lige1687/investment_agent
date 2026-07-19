"""Fund backtest REST API endpoints."""

from __future__ import annotations

from dataclasses import asdict, replace

from fastapi import APIRouter, HTTPException

from app.backtest.engine import BacktestEngine
from app.backtest.fees import FundFeeModel, RedemptionFeeTier
from app.backtest.fund_nav_data import EastmoneyFundNavClient
from app.backtest.models import (
    BacktestConfig,
    FundNavPoint,
    ProsperityConfig,
    SignalBar,
)
from app.backtest.presets import (
    BacktestPreset,
    get_backtest_preset,
    list_backtest_presets,
)
from app.backtest.strategy_compiler_agent import compile_and_apply_strategy_text
from app.backtest.westock_data import WestockDataClient
from app.schemas.backtest import (
    BacktestPresetItem,
    BacktestPresetsResponse,
    BacktestRunPresetRequest,
    BacktestRunRequest,
    BacktestRunResponse,
    EtfDataSourceSchema,
)

router = APIRouter(prefix="/backtest", tags=["Backtest"])

DISCLAIMER = "过去表现不代表未来收益，本结果仅供参考，不构成投资建议"


@router.post("/run", response_model=BacktestRunResponse)
async def run_backtest(payload: BacktestRunRequest) -> BacktestRunResponse:
    """Run an inline-data fund backtest.

    MVP accepts historical arrays directly. A later data layer can hydrate the
    same engine from westock-data, 同花顺, or cached database records.
    """
    config_payload = payload.config
    prosperity_payload = config_payload.prosperity
    config = BacktestConfig(
        **config_payload.model_dump(exclude={"prosperity"}),
        prosperity=ProsperityConfig(**prosperity_payload.model_dump()),
    )
    config, strategy_profile = await compile_and_apply_strategy_text(
        config,
        payload.strategy_text,
        use_ai=payload.use_ai_strategy_compiler,
    )
    fee_model = FundFeeModel(
        subscription_fee_rate=payload.fee_model.subscription_fee_rate,
        redemption_fee_tiers=[
            RedemptionFeeTier(**tier.model_dump())
            for tier in payload.fee_model.redemption_fee_tiers
        ],
    )
    if payload.etf_data_source is not None:
        fund_nav, signal_bars = await _load_etf_data(payload.etf_data_source)
    else:
        fund_nav = await _load_fund_nav(payload)
        signal_bars = await _load_signal_bars(payload)
    return await _run_engine_response(
        config, fee_model, fund_nav, signal_bars, strategy_profile, payload.test_mode
    )


@router.get("/presets", response_model=BacktestPresetsResponse)
async def get_presets() -> BacktestPresetsResponse:
    return BacktestPresetsResponse(
        presets=[
            BacktestPresetItem(
                preset_id=preset.preset_id,
                title=preset.title,
                fund_code=preset.fund_code,
                fund_name=preset.fund_name,
                signal_symbol=preset.signal_symbol,
                signal_name=preset.signal_name,
                signal_provider=preset.signal_provider,
                description=preset.description,
                etf_only=preset.etf_only,
            )
            for preset in list_backtest_presets()
        ]
    )


@router.post("/run-preset", response_model=BacktestRunResponse)
async def run_backtest_preset(payload: BacktestRunPresetRequest) -> BacktestRunResponse:
    try:
        preset = get_backtest_preset(payload.preset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    config = _config_from_preset(preset, payload)
    config, strategy_profile = await compile_and_apply_strategy_text(
        config,
        payload.strategy_text,
        use_ai=payload.use_ai_strategy_compiler,
    )
    fee_model = FundFeeModel(
        subscription_fee_rate=payload.fee_model.subscription_fee_rate,
        redemption_fee_tiers=[
            RedemptionFeeTier(**tier.model_dump())
            for tier in payload.fee_model.redemption_fee_tiers
        ],
    )
    if preset.etf_only:
        # ETF / 指数模式：一次拉取 OHLCV，close 同时充当 NAV 和信号
        try:
            fund_nav, signal_bars = await _load_etf_data(
                EtfDataSourceSchema(
                    provider="westock",
                    symbol=preset.signal_symbol,
                    name=preset.signal_name,
                    period=preset.signal_period,
                    limit=payload.signal_limit,
                )
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"ETF data fetch failed: {exc}",
            ) from exc
    else:
        try:
            fund_nav = await EastmoneyFundNavClient().fetch_nav(
                fund_code=preset.fund_code,
                start_date=payload.start_date,
                end_date=payload.end_date,
                page_size=payload.fund_nav_page_size,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Eastmoney fund NAV fetch failed: {exc}",
            ) from exc
        try:
            signal_bars = await WestockDataClient().fetch_kline(
                symbol=preset.signal_symbol,
                period=preset.signal_period,
                limit=payload.signal_limit,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"westock-data fetch failed: {exc}",
            ) from exc
    return await _run_engine_response(
        config, fee_model, fund_nav, signal_bars, strategy_profile, payload.test_mode
    )


async def _run_engine_response(
    config: BacktestConfig,
    fee_model: FundFeeModel,
    fund_nav: list[FundNavPoint],
    signal_bars: list[SignalBar],
    strategy_profile: dict,
    test_mode: bool = False,
) -> BacktestRunResponse:
    fund_nav, signal_bars = _align_by_date(fund_nav, signal_bars)
    result = await BacktestEngine(fee_model=fee_model).run(
        config=config,
        fund_nav=fund_nav,
        signal_bars=signal_bars,
        test_mode=test_mode,
    )
    return BacktestRunResponse(
        config=asdict(result.config),
        metrics=asdict(result.metrics),
        equity_curve=[asdict(item) for item in result.equity_curve],
        signal_bars=[asdict(item) for item in signal_bars],
        trades=[asdict(item) for item in result.trades],
        events=result.events,
        strategy_profile=strategy_profile,
        disclaimer=DISCLAIMER,
        execution_log_path=result.execution_log_path,
    )


def _config_from_preset(
    preset: BacktestPreset,
    payload: BacktestRunPresetRequest,
) -> BacktestConfig:
    config = replace(preset.config, initial_cash=payload.initial_cash)
    if payload.initial_position_pct is not None:
        config = replace(config, initial_position_pct=payload.initial_position_pct)
    if payload.target_position_pct is not None:
        config = replace(config, target_position_pct=payload.target_position_pct)
    if payload.prosperity_score is not None:
        config = replace(
            config,
            prosperity=replace(config.prosperity, score=payload.prosperity_score),
        )
    config = replace(
        config,
        current_correlated_growth_exposure_pct=payload.current_correlated_growth_exposure_pct,
    )
    return config


async def _load_fund_nav(payload: BacktestRunRequest) -> list[FundNavPoint]:
    if payload.fund_nav is not None:
        return [FundNavPoint(**item.model_dump()) for item in payload.fund_nav]
    if payload.fund_nav_data_source is None:
        raise HTTPException(
            status_code=422,
            detail="Either fund_nav or fund_nav_data_source must be provided",
        )
    source = payload.fund_nav_data_source
    if source.provider == "eastmoney":
        try:
            return await EastmoneyFundNavClient().fetch_nav(
                fund_code=source.fund_code,
                start_date=source.start_date,
                end_date=source.end_date,
                page_size=source.page_size,
                timeout=source.timeout,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Eastmoney fund NAV fetch failed: {exc}",
            ) from exc
    raise HTTPException(
        status_code=422, detail=f"Unsupported fund NAV provider: {source.provider}"
    )


async def _load_signal_bars(payload: BacktestRunRequest) -> list[SignalBar]:
    if payload.signal_bars is not None:
        return [SignalBar(**item.model_dump()) for item in payload.signal_bars]
    if payload.signal_data_source is None:
        raise HTTPException(
            status_code=422,
            detail="Either signal_bars or signal_data_source must be provided",
        )
    source = payload.signal_data_source
    if source.provider == "westock":
        try:
            return await WestockDataClient().fetch_kline(
                symbol=source.symbol,
                period=source.period,
                limit=source.limit,
                timeout=source.timeout,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"westock-data fetch failed: {exc}",
            ) from exc
    raise HTTPException(
        status_code=422, detail=f"Unsupported signal provider: {source.provider}"
    )


async def _load_etf_data(
    source: EtfDataSourceSchema,
) -> tuple[list[FundNavPoint], list[SignalBar]]:
    """ETF / 指数独立回测数据加载。

    一次拉取 OHLCV，同时生成两路数据：
    - signal_bars：原始 OHLCV，用于技术指标（MA/MACD/量比）
    - fund_nav：close 价格 → NAV，用于持仓估值和收益计算

    为什么 close 可以作为 NAV：
    - ETF 的持仓成本就是买入的 close 价格
    - 收益率 = (当日 close - 买入 close) / 买入 close，与 NAV 公式完全一致
    - 相比基金 T+1 NAV，ETF 回测用 T+0 close，时序更精确
    """
    if source.provider != "westock":
        raise HTTPException(
            status_code=422,
            detail=f"ETF data source provider not supported: {source.provider}",
        )
    try:
        signal_bars = await WestockDataClient().fetch_kline(
            symbol=source.symbol,
            period=source.period,
            limit=source.limit,
            timeout=source.timeout,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"ETF OHLCV fetch failed ({source.symbol}): {exc}",
        ) from exc

    if not signal_bars:
        raise HTTPException(
            status_code=502,
            detail=f"No OHLCV data returned for ETF symbol: {source.symbol}",
        )

    # close 价格作为 NAV
    fund_nav = [FundNavPoint(date=bar.date, nav=bar.close) for bar in signal_bars]
    return fund_nav, signal_bars


def _align_by_date(
    fund_nav: list[FundNavPoint],
    signal_bars: list[SignalBar],
) -> tuple[list[FundNavPoint], list[SignalBar]]:
    nav_by_date = {item.date: item for item in fund_nav}
    bar_by_date = {item.date: item for item in signal_bars}
    common_dates = sorted(set(nav_by_date) & set(bar_by_date))
    if len(common_dates) < 2:
        raise HTTPException(
            status_code=422,
            detail="Fund NAV and signal bars need at least two overlapping dates",
        )
    return (
        [nav_by_date[item_date] for item_date in common_dates],
        [bar_by_date[item_date] for item_date in common_dates],
    )
