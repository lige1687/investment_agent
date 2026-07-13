"""P0 market-data trust contract tests."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from app.config import Settings
from app.config import settings
from app.skills.base import SkillResult
from app.skills.bridge import bridge
from app.services.market_service import MarketService


def test_market_data_mode_defaults_to_live():
    assert Settings(_env_file=None).market_data_mode == "live"


def test_market_data_meta_exposes_decision_grade_provenance():
    from app.schemas.market import MarketDataMeta

    fetched_at = datetime.now(timezone.utc)
    meta = MarketDataMeta(
        source="westock",
        fetched_at=fetched_at,
        mode="live",
        status="ok",
    )

    assert meta.fetched_at == fetched_at
    assert meta.stale is False
    assert meta.is_mock is False
    assert meta.message is None


@pytest.mark.parametrize(
    "response_name",
    [
        "QuotesListResponse",
        "KlineResponse",
        "IndicesListResponse",
        "HeatmapResponse",
        "DiagnosisResponse",
        "SectorRankingResponse",
    ],
)
def test_every_market_response_requires_meta(response_name):
    from app import schemas

    response_type = getattr(schemas.market, response_name)
    assert "meta" in response_type.model_fields
    assert response_type.model_fields["meta"].is_required()


def test_index_validation_rejects_non_positive_and_out_of_range_values():
    from app.services.market_data_trust import validate_index_rows

    rows, rejected = validate_index_rows(
        [
            {"code": "000001", "price": 3000.0, "change_pct": 1.2},
            {"code": "BAD_PRICE", "price": 0, "change_pct": 1.0},
            {"code": "BAD_PCT", "price": 100.0, "change_pct": 21.0},
            {"code": "MISSING_PCT", "price": 100.0},
        ]
    )

    assert [row["code"] for row in rows] == ["000001"]
    assert rejected == ["BAD_PRICE", "BAD_PCT", "MISSING_PCT"]


@pytest.mark.asyncio
async def test_live_index_failure_does_not_call_mock_provider(monkeypatch):
    monkeypatch.setattr(settings, "market_data_mode", "live")
    monkeypatch.setattr(
        bridge,
        "invoke_simple",
        AsyncMock(return_value=SkillResult(success=False, error="provider unavailable")),
    )
    service = MarketService(Mock())
    service._data_provider = Mock()

    response = await service.get_global_indices(["000001"])

    service._data_provider.get_global_indices.assert_not_called()
    assert response.indices == []
    assert response.meta.mode == "live"
    assert response.meta.status == "unavailable"
    assert response.meta.is_mock is False


@pytest.mark.asyncio
async def test_demo_index_failure_returns_labeled_mock_data(monkeypatch):
    monkeypatch.setattr(settings, "market_data_mode", "demo")
    monkeypatch.setattr(
        bridge,
        "invoke_simple",
        AsyncMock(return_value=SkillResult(success=False, error="provider unavailable")),
    )
    service = MarketService(Mock())
    service._data_provider = Mock()
    service._data_provider.get_global_indices.return_value = [
        {
            "code": "000001",
            "name": "上证指数",
            "price": 3000.0,
            "change": 15.0,
            "change_pct": 0.5,
        }
    ]

    response = await service.get_global_indices(["000001"])

    assert response.indices[0].change_pct == 0.5
    assert response.meta.mode == "demo"
    assert response.meta.source == "demo/mock"
    assert response.meta.status == "ok"
    assert response.meta.is_mock is True


@pytest.mark.asyncio
async def test_invalid_live_index_data_is_not_decision_grade(monkeypatch):
    monkeypatch.setattr(settings, "market_data_mode", "live")
    monkeypatch.setattr(
        bridge,
        "invoke_simple",
        AsyncMock(
            return_value=SkillResult(
                success=True,
                strategy_used="westock",
                data=[
                    {
                        "code": "000001",
                        "price": 3000.0,
                        "change": 12.5,
                    }
                ],
            )
        ),
    )
    service = MarketService(Mock())
    service._data_provider = Mock()

    response = await service.get_global_indices(["000001"])

    assert response.indices == []
    assert response.meta.source == "westock"
    assert response.meta.status == "invalid"
    assert "不可用于交易决策" in (response.meta.message or "")
    service._data_provider.get_global_indices.assert_not_called()


@pytest.mark.asyncio
async def test_live_quote_failure_returns_unavailable_meta(monkeypatch):
    monkeypatch.setattr(settings, "market_data_mode", "live")
    monkeypatch.setattr(
        bridge,
        "invoke_simple",
        AsyncMock(return_value=SkillResult(success=False, error="offline")),
    )

    response = await MarketService(Mock()).get_quotes(["510050"])

    assert response.quotes == []
    assert response.meta.status == "unavailable"
    assert response.meta.is_mock is False


@pytest.mark.asyncio
async def test_live_heatmap_failure_never_calls_generated_provider(monkeypatch):
    monkeypatch.setattr(settings, "market_data_mode", "live")
    monkeypatch.setattr(
        bridge,
        "invoke_simple",
        AsyncMock(return_value=SkillResult(success=False, error="offline")),
    )
    service = MarketService(Mock())
    service._data_provider = Mock()

    response = await service.get_heatmap()

    assert response.sectors == []
    assert response.meta.status == "unavailable"
    service._data_provider.get_heatmap_sectors.assert_not_called()


@pytest.mark.asyncio
async def test_live_sector_ranking_failure_never_calls_mock_rows(monkeypatch):
    monkeypatch.setattr(settings, "market_data_mode", "live")
    service = MarketService(Mock())
    monkeypatch.setattr(service, "_fetch_sectors_from_skill", AsyncMock(return_value=[]))
    mock_rows = Mock(return_value=[])
    monkeypatch.setattr(service, "_get_mock_sector_data", mock_rows)

    response = await service.get_sector_rankings()

    assert response.all_rankings == []
    assert response.meta.status == "unavailable"
    mock_rows.assert_not_called()


@pytest.mark.asyncio
async def test_kline_failure_returns_unavailable_meta(monkeypatch):
    monkeypatch.setattr(
        bridge,
        "invoke_simple",
        AsyncMock(return_value=SkillResult(success=False, error="offline")),
    )
    service = MarketService(Mock())
    monkeypatch.setattr(service, "_get_kline_from_cache", AsyncMock(return_value=[]))

    response = await service.get_kline("510050", count=1)

    assert response.klines == []
    assert response.meta.status == "unavailable"


@pytest.mark.asyncio
async def test_kline_cache_is_labeled_with_local_source(monkeypatch):
    from app.schemas.market import KlineItem

    service = MarketService(Mock())
    cached = [
        KlineItem(
            timestamp="2026-07-13T15:00:00+08:00",
            open=1.0,
            high=1.1,
            low=0.9,
            close=1.05,
            volume=100.0,
        )
    ]
    monkeypatch.setattr(service, "_get_kline_from_cache", AsyncMock(return_value=cached))

    response = await service.get_kline("510050", count=1)

    assert response.klines == cached
    assert response.meta.source == "local/sqlite"
    assert response.meta.status == "ok"


@pytest.mark.asyncio
async def test_major_indices_use_same_fail_closed_contract(monkeypatch):
    monkeypatch.setattr(settings, "market_data_mode", "live")
    monkeypatch.setattr(
        bridge,
        "invoke_simple",
        AsyncMock(return_value=SkillResult(success=False, error="offline")),
    )
    service = MarketService(Mock())
    service._data_provider = Mock()

    response = await service.get_indices()

    assert response.indices == []
    assert response.meta.status == "unavailable"
    service._data_provider.get_global_indices.assert_not_called()


@pytest.mark.asyncio
async def test_live_diagnosis_failure_does_not_use_generated_inputs(monkeypatch):
    monkeypatch.setattr(settings, "market_data_mode", "live")
    monkeypatch.setattr(
        bridge,
        "invoke_simple",
        AsyncMock(return_value=SkillResult(success=False, error="offline")),
    )
    service = MarketService(Mock())
    service._data_provider = Mock()

    response = await service.get_diagnosis()

    assert response.sentiment is None
    assert response.top_capital_inflow == []
    assert response.sector_rotation == []
    assert response.meta.status == "unavailable"
    service._data_provider.get_sentiment.assert_not_called()
    service._data_provider.get_capital_flow.assert_not_called()
    service._data_provider.get_sector_rotation.assert_not_called()
    service._data_provider.get_north_bound_sectors.assert_not_called()
