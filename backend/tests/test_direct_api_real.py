"""Tests for DirectAPIStrategy real-data handlers (_fetch_indices, _fetch_quotes).

Exercises the bridge path with the provider mocked so no network is hit.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from app.services.global_index_provider import DataUnavailable, GlobalIndexProvider
from app.skills.base import SkillRequest
from app.skills.bridge import bridge
from app.skills.strategies.direct_api import DirectAPIStrategy

# ── Secid mapping for stock/ETF quotes ─────────────────────────────────────


@pytest.mark.parametrize(
    "symbol,secid",
    [
        ("510050", "1.510050"),  # SH ETF
        ("588000", "1.588000"),  # SH ETF
        ("159915", "0.159915"),  # SZ ETF
        ("600000", "1.600000"),  # SH stock
        ("688981", "1.688981"),  # SH STAR stock
        ("000001", "0.000001"),  # SZ stock
        ("300750", "0.300750"),  # SZ ChiNext stock
    ],
)
def test_secid_for_symbol(symbol, secid):
    assert DirectAPIStrategy._secid_for_symbol(symbol) == secid


# ── Bridge-level index_quote ───────────────────────────────────────────────


@pytest.fixture
def isolated_bridge():
    """Swap the global bridge to use only a fresh DirectAPIStrategy."""
    original_strategies = bridge._strategies
    bridge._strategies = [DirectAPIStrategy()]
    bridge._cache._memory.clear()
    yield bridge
    bridge._strategies = original_strategies
    bridge._cache._memory.clear()


@pytest.mark.asyncio
async def test_bridge_index_quote_returns_real_list(isolated_bridge, monkeypatch):
    fake_rows = [
        {
            "code": "000001",
            "name": "上证指数",
            "price": 3923.2,
            "change": -32.38,
            "change_pct": -0.82,
            "market": "A股",
        },
        {
            "code": "KOSPI",
            "name": "韩国KOSPI",
            "price": 6786.27,
            "change": -498.14,
            "change_pct": -6.84,
            "market": "韩股",
        },
    ]
    monkeypatch.setattr(
        GlobalIndexProvider, "get_indices", AsyncMock(return_value=fake_rows)
    )

    result = await isolated_bridge.invoke_simple(
        "index_quote", params={"codes": ["000001", "KOSPI"]}, cache_ttl=0
    )

    assert result.success is True
    assert result.strategy_used == "direct_api"
    assert isinstance(result.data, list)
    assert len(result.data) == 2
    assert result.data[0]["code"] == "000001"
    assert result.data[1]["code"] == "KOSPI"


@pytest.mark.asyncio
async def test_bridge_index_quote_fail_closed_on_data_unavailable(
    isolated_bridge, monkeypatch
):
    """When the provider raises DataUnavailable, the bridge must report failure
    (so MarketService returns 'unavailable' in live mode, never mock)."""
    monkeypatch.setattr(
        GlobalIndexProvider,
        "get_indices",
        AsyncMock(side_effect=DataUnavailable("eastmoney ulist returned empty diff")),
    )

    result = await isolated_bridge.invoke_simple(
        "index_quote", params={"codes": ["000001"]}, cache_ttl=0
    )

    assert result.success is False
    # The bridge falls through to "no strategy available" when the only
    # registered strategy fails, so strategy_used may be empty. What matters
    # is that success is False (MarketService returns 'unavailable' in live
    # mode, never mock).
    assert result.data is None


# ── _fetch_quotes via DirectAPIStrategy.execute ────────────────────────────


def _mock_quote_response(price, code, name, change, change_pct):
    resp = Mock()
    resp.status_code = 200
    resp.json = Mock(
        return_value={
            "data": {
                "f43": price,
                "f57": code,
                "f58": name,
                "f169": change,
                "f170": change_pct,
            }
        }
    )
    return resp


def _mock_async_client(responses):
    """Return a mock AsyncClient whose .get cycles through ``responses``."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=list(responses))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


@pytest.mark.asyncio
async def test_fetch_quotes_returns_valid_rows(monkeypatch):
    mock_client = _mock_async_client(
        [_mock_quote_response(3.039, "510050", "上证50ETF华夏", -0.025, -0.82)]
    )
    monkeypatch.setattr(
        "app.skills.strategies.direct_api.httpx.AsyncClient",
        lambda **kw: mock_client,
    )

    rows = await DirectAPIStrategy()._fetch_quotes(["510050"])

    assert len(rows) == 1
    assert rows[0]["symbol"] == "510050"
    assert rows[0]["code"] == "510050"
    assert rows[0]["name"] == "上证50ETF华夏"
    assert rows[0]["price"] == 3.039
    assert rows[0]["change_pct"] == -0.82


@pytest.mark.asyncio
async def test_fetch_quotes_skips_failed_symbol(monkeypatch):
    """A single failed symbol must not fail the whole batch."""
    mock_client = _mock_async_client(
        [
            _mock_quote_response(3.039, "510050", "上证50ETF华夏", -0.025, -0.82),
            Mock(status_code=503, json=Mock(return_value={})),  # 503 -> skipped
        ]
    )
    monkeypatch.setattr(
        "app.skills.strategies.direct_api.httpx.AsyncClient",
        lambda **kw: mock_client,
    )

    rows = await DirectAPIStrategy()._fetch_quotes(["510050", "159915"])

    assert len(rows) == 1
    assert rows[0]["symbol"] == "510050"


@pytest.mark.asyncio
async def test_fetch_quotes_all_fail_raises_data_unavailable(monkeypatch):
    mock_client = _mock_async_client(
        [Mock(status_code=503, json=Mock(return_value={}))]
    )
    monkeypatch.setattr(
        "app.skills.strategies.direct_api.httpx.AsyncClient",
        lambda **kw: mock_client,
    )

    with pytest.raises(DataUnavailable, match="all quote rows failed"):
        await DirectAPIStrategy()._fetch_quotes(["510050"])


@pytest.mark.asyncio
async def test_execute_index_quote_returns_skill_result(monkeypatch):
    """DirectAPIStrategy.execute wraps the list into a SkillResult."""
    monkeypatch.setattr(
        GlobalIndexProvider,
        "get_indices",
        AsyncMock(
            return_value=[
                {
                    "code": "000001",
                    "name": "上证指数",
                    "price": 3923.2,
                    "change": -32.38,
                    "change_pct": -0.82,
                    "market": "A股",
                }
            ]
        ),
    )

    result = await DirectAPIStrategy().execute(
        SkillRequest(skill_name="index_quote", params={"codes": ["000001"]})
    )

    assert result.success is True
    assert result.strategy_used == "direct_api"
    assert isinstance(result.data, list)
    assert result.data[0]["price"] == 3923.2


@pytest.mark.asyncio
async def test_execute_index_quote_fail_closed(monkeypatch):
    monkeypatch.setattr(
        GlobalIndexProvider,
        "get_indices",
        AsyncMock(side_effect=DataUnavailable("empty diff")),
    )

    result = await DirectAPIStrategy().execute(
        SkillRequest(skill_name="index_quote", params={"codes": ["000001"]})
    )

    assert result.success is False
    assert result.strategy_used == "direct_api"
