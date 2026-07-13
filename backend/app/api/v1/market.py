"""Market data REST API endpoints."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.market_service import MarketService
from app.schemas.market import (
    QuotesListResponse, KlineResponse, IndicesListResponse,
    HeatmapResponse, DiagnosisResponse, SectorRankingResponse,
)

router = APIRouter(prefix="/market", tags=["Market"])


@router.get("/quotes", response_model=QuotesListResponse)
async def get_quotes(
    symbols: str = Query(..., description="Comma-separated symbols, e.g. 510050,159915"),
    db: AsyncSession = Depends(get_db),
):
    """Get real-time quotes for specified symbols."""
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    service = MarketService(db)
    return await service.get_quotes(symbol_list)


@router.get("/kline", response_model=KlineResponse)
async def get_kline(
    symbol: str = Query(..., description="Symbol code"),
    period: str = Query("daily", description="K-line period"),
    count: int = Query(120, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Get K-line candlestick data."""
    service = MarketService(db)
    return await service.get_kline(symbol, period, count)


@router.get("/indices", response_model=IndicesListResponse)
async def get_indices(
    codes: str | None = Query(None, description="Comma-separated index codes, default: major A-shares"),
    db: AsyncSession = Depends(get_db),
):
    """Get global index quotes. 指数数据查询 skill."""
    service = MarketService(db)
    code_list = [c.strip() for c in codes.split(",") if c.strip()] if codes else None
    return await service.get_global_indices(code_list)


@router.get("/heatmap", response_model=HeatmapResponse)
async def get_heatmap(db: AsyncSession = Depends(get_db)):
    """Get sector performance heatmap data."""
    service = MarketService(db)
    return await service.get_heatmap()


@router.get("/diagnosis", response_model=DiagnosisResponse)
async def get_diagnosis(db: AsyncSession = Depends(get_db)):
    """Get comprehensive market diagnosis.

    Aggregates: 市场情绪分析(#120) + 行业轮动分析(#119) +
    沪深港通资金流(#108) + 行业轮动监控(#187)
    """
    service = MarketService(db)
    return await service.get_diagnosis()


@router.get("/sector/rankings", response_model=SectorRankingResponse)
async def get_sector_rankings(db: AsyncSession = Depends(get_db)):
    """Get real-time sector rankings with multi-dimensional scoring.

    Returns sectors ranked by composite score:
    - Price/Technical (25%): 技术面
    - Capital Flow (30%): 资金面
    - Heat Level (20%): 热度面
    - Momentum (25%): 动量面

    Categorized into: STRONG / WATCH / WEAK / AVOID signals.
    """
    service = MarketService(db)
    return await service.get_sector_rankings()
