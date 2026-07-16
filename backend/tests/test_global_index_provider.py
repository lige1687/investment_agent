"""Tests for GlobalIndexProvider -- fail-closed, no mock data in live mode.

All httpx access is mocked; no test hits the real network.
"""

from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app.services.global_index_provider import (
    DataUnavailable,
    GlobalIndexProvider,
    _market_for_code,
    _secid_for_index_code,
)

# ── Secid mapping ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "app_code,secid",
    [
        ("KOSPI", "100.KS11"),
        ("IXIC", "100.NDX"),
        ("DJI", "100.DJIA"),
        ("399006", "0.399006"),
        ("000001", "1.000001"),
        ("399001", "0.399001"),
        ("000300", "1.000300"),
        ("000688", "1.000688"),
        ("HSI", "100.HSI"),
        ("N225", "100.N225"),
        ("SPX", "100.SPX"),
    ],
)
def test_secid_mapping(app_code, secid):
    assert _secid_for_index_code(app_code) == secid


def test_secid_fallback_numeric_not_in_map():
    # 399-prefix -> Shenzhen
    assert _secid_for_index_code("399333") == "0.399333"
    # other numeric -> Shanghai
    assert _secid_for_index_code("000999") == "1.000999"


def test_secid_fallback_named_not_in_map():
    assert _secid_for_index_code("FOO") == "100.FOO"


def test_market_classification():
    assert _market_for_code("000001") == "A股"
    assert _market_for_code("HSI") == "港股"
    assert _market_for_code("N225") == "日股"
    assert _market_for_code("KOSPI") == "韩股"
    assert _market_for_code("IXIC") == "美股"
    assert _market_for_code("USDX") == "宏观"
    assert _market_for_code("UNKNOWN") == "其他"


# ── get_indices parsing ────────────────────────────────────────────────────


def _fake_diff() -> list[dict]:
    """Realistic eastmoney ulist diff response (mirrors live 2026-07-16 data)."""
    return [
        {
            "f12": "000001",
            "f14": "上证指数",
            "f2": 3923.2,
            "f3": -0.82,
            "f4": -32.38,
            "f5": 326326077,
        },
        {
            "f12": "HSI",
            "f14": "恒生指数",
            "f2": 25157.56,
            "f3": 1.93,
            "f4": 476.46,
            "f5": 7115941376,
        },
        {
            "f12": "N225",
            "f14": "日经225",
            "f2": 66704.49,
            "f3": -2.98,
            "f4": -2047.02,
            "f5": 0,
        },
        {
            "f12": "KS11",
            "f14": "韩国KOSPI",
            "f2": 6786.27,
            "f3": -6.84,
            "f4": -498.14,
            "f5": 325069,
        },
        {
            "f12": "NDX",
            "f14": "纳斯达克",
            "f2": 26269.23,
            "f3": 0.62,
            "f4": 162.22,
            "f5": 6328537856,
        },
        {
            "f12": "DJIA",
            "f14": "道琼斯",
            "f2": 52658.64,
            "f3": 0.29,
            "f4": 150.37,
            "f5": 508443312,
        },
    ]


@pytest.mark.asyncio
async def test_get_indices_parses_valid_diff():
    provider = GlobalIndexProvider()
    provider._fetch_ulist = AsyncMock(return_value=_fake_diff())

    codes = ["000001", "HSI", "N225", "KOSPI", "IXIC", "DJI"]
    rows = await provider.get_indices(codes)

    assert len(rows) == 6
    # Alias codes map back to the app codes the caller asked for.
    assert {r["code"] for r in rows} == set(codes)

    sh = next(r for r in rows if r["code"] == "000001")
    assert sh["name"] == "上证指数"
    assert sh["price"] == 3923.2
    assert sh["change"] == -32.38
    assert sh["change_pct"] == -0.82
    assert sh["market"] == "A股"

    kospi = next(r for r in rows if r["code"] == "KOSPI")
    assert kospi["name"] == "韩国KOSPI"
    assert kospi["market"] == "韩股"

    ixic = next(r for r in rows if r["code"] == "IXIC")
    assert ixic["market"] == "美股"

    dji = next(r for r in rows if r["code"] == "DJI")
    assert dji["market"] == "美股"


@pytest.mark.asyncio
async def test_get_indices_drops_invalid_rows_keeps_valid():
    provider = GlobalIndexProvider()
    diff = [
        {
            "f12": "000001",
            "f14": "上证指数",
            "f2": 3923.2,
            "f3": -0.82,
            "f4": -32.38,
            "f5": 0,
        },
        {"f12": "BAD_PRICE", "f14": "坏价", "f2": 0, "f3": 1.0, "f4": 0, "f5": 0},
        {"f12": "BAD_PCT", "f14": "坏幅", "f2": 100.0, "f3": 25.0, "f4": 0, "f5": 0},
    ]
    provider._fetch_ulist = AsyncMock(return_value=diff)

    rows = await provider.get_indices(["000001", "BAD_PRICE", "BAD_PCT"])
    assert len(rows) == 1
    assert rows[0]["code"] == "000001"


@pytest.mark.asyncio
async def test_get_indices_empty_codes_returns_empty_list():
    rows = await GlobalIndexProvider().get_indices([])
    assert rows == []


# ── Fail-closed: DataUnavailable raised, never mock ────────────────────────


@pytest.mark.asyncio
async def test_get_indices_all_rows_rejected_raises():
    provider = GlobalIndexProvider()
    diff = [
        {"f12": "BAD1", "f14": "坏1", "f2": 0, "f3": 1.0, "f4": 0, "f5": 0},
        {"f12": "BAD2", "f14": "坏2", "f2": 100.0, "f3": 25.0, "f4": 0, "f5": 0},
    ]
    provider._fetch_ulist = AsyncMock(return_value=diff)

    with pytest.raises(DataUnavailable, match="all index rows rejected"):
        await provider.get_indices(["BAD1", "BAD2"])


@pytest.mark.asyncio
async def test_get_indices_httpx_error_propagates_as_data_unavailable():
    provider = GlobalIndexProvider()
    provider._fetch_ulist = AsyncMock(
        side_effect=DataUnavailable("eastmoney ulist request failed")
    )

    with pytest.raises(DataUnavailable, match="request failed"):
        await provider.get_indices(["000001"])


def _mock_async_client(get_response=None, get_side_effect=None):
    """Build a mock httpx.AsyncClient usable as ``async with ... as client``."""
    mock_client = AsyncMock()
    if get_side_effect is not None:
        mock_client.get = AsyncMock(side_effect=get_side_effect)
    else:
        mock_client.get = AsyncMock(return_value=get_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


@pytest.mark.asyncio
async def test_fetch_ulist_raises_on_httpx_transport_error(monkeypatch):
    mock_client = _mock_async_client(
        get_side_effect=httpx.ConnectError("connection refused")
    )
    monkeypatch.setattr(
        "app.services.global_index_provider.httpx.AsyncClient",
        lambda **kw: mock_client,
    )

    with pytest.raises(DataUnavailable, match="request failed"):
        await GlobalIndexProvider()._fetch_ulist(["1.000001"])


@pytest.mark.asyncio
async def test_fetch_ulist_raises_on_non_200(monkeypatch):
    resp = Mock()
    resp.status_code = 503
    mock_client = _mock_async_client(get_response=resp)
    monkeypatch.setattr(
        "app.services.global_index_provider.httpx.AsyncClient",
        lambda **kw: mock_client,
    )

    with pytest.raises(DataUnavailable, match="status 503"):
        await GlobalIndexProvider()._fetch_ulist(["1.000001"])


@pytest.mark.asyncio
async def test_fetch_ulist_raises_on_missing_data(monkeypatch):
    resp = Mock()
    resp.status_code = 200
    resp.json = Mock(return_value={"rc": 0, "data": None})
    mock_client = _mock_async_client(get_response=resp)
    monkeypatch.setattr(
        "app.services.global_index_provider.httpx.AsyncClient",
        lambda **kw: mock_client,
    )

    with pytest.raises(DataUnavailable, match="empty diff"):
        await GlobalIndexProvider()._fetch_ulist(["1.000001"])


@pytest.mark.asyncio
async def test_fetch_ulist_raises_on_empty_diff(monkeypatch):
    resp = Mock()
    resp.status_code = 200
    resp.json = Mock(return_value={"data": {"diff": []}})
    mock_client = _mock_async_client(get_response=resp)
    monkeypatch.setattr(
        "app.services.global_index_provider.httpx.AsyncClient",
        lambda **kw: mock_client,
    )

    with pytest.raises(DataUnavailable, match="empty diff"):
        await GlobalIndexProvider()._fetch_ulist(["1.000001"])


# ── get_index convenience ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_index_returns_single_row():
    provider = GlobalIndexProvider()
    provider._fetch_ulist = AsyncMock(
        return_value=[
            {
                "f12": "000001",
                "f14": "上证指数",
                "f2": 3923.2,
                "f3": -0.82,
                "f4": -32.38,
                "f5": 0,
            },
        ]
    )
    row = await provider.get_index("000001")
    assert row is not None
    assert row["code"] == "000001"
    assert row["price"] == 3923.2


@pytest.mark.asyncio
async def test_get_index_raises_on_fetch_failure():
    provider = GlobalIndexProvider()
    provider._fetch_ulist = AsyncMock(side_effect=DataUnavailable("empty diff"))

    with pytest.raises(DataUnavailable):
        await provider.get_index("000001")


# ── Live sanity (skipped by default) ───────────────────────────────────────


@pytest.mark.skip(reason="network -- run manually to verify secid mapping")
@pytest.mark.asyncio
async def test_live_eastmoney_returns_real_data():
    provider = GlobalIndexProvider()
    rows = await provider.get_indices(["000001", "HSI", "N225", "KOSPI", "IXIC", "DJI"])
    assert len(rows) >= 6
    codes = {r["code"] for r in rows}
    assert {"000001", "KOSPI", "IXIC", "DJI"} <= codes
    sh = next(r for r in rows if r["code"] == "000001")
    assert sh["price"] > 0
