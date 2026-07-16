"""Tests for daily_summary real-data path (Wave 2: A3 + B4 + C1-C5).

All network access is mocked: GlobalIndexProvider, sector_card_service,
PortfolioValuationService, and the Claude CLI subprocess. No test hits the
real network or depends on the real ``claude`` binary.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.global_index_provider import DataUnavailable
from app.tasks import daily_summary as ds

# ─── Fixtures (realistic mock data) ─────────────────────────────────────────

INDEX_ROWS = [
    {
        "code": "000001",
        "name": "上证指数",
        "price": 3923.2,
        "change": -32.38,
        "change_pct": -0.82,
        "market": "A股",
    },
    {
        "code": "399001",
        "name": "深证成指",
        "price": 10200.0,
        "change": -100.0,
        "change_pct": -0.97,
        "market": "A股",
    },
    {
        "code": "000300",
        "name": "沪深300",
        "price": 3890.0,
        "change": -30.0,
        "change_pct": -0.76,
        "market": "A股",
    },
    {
        "code": "399006",
        "name": "创业板指",
        "price": 2180.0,
        "change": -20.0,
        "change_pct": -0.91,
        "market": "A股",
    },
    {
        "code": "000688",
        "name": "科创50",
        "price": 1025.0,
        "change": -10.0,
        "change_pct": -0.97,
        "market": "A股",
    },
    {
        "code": "HSI",
        "name": "恒生指数",
        "price": 25157.56,
        "change": 476.46,
        "change_pct": 1.93,
        "market": "港股",
    },
    {
        "code": "N225",
        "name": "日经225",
        "price": 66704.49,
        "change": -2047.02,
        "change_pct": -2.98,
        "market": "日股",
    },
    {
        "code": "KOSPI",
        "name": "韩国KOSPI",
        "price": 6786.27,
        "change": -498.14,
        "change_pct": -6.84,
        "market": "韩股",
    },
    {
        "code": "IXIC",
        "name": "纳斯达克",
        "price": 26269.23,
        "change": 162.22,
        "change_pct": 0.62,
        "market": "美股",
    },
    {
        "code": "SPX",
        "name": "标普500",
        "price": 6050.0,
        "change": 15.0,
        "change_pct": 0.25,
        "market": "美股",
    },
    {
        "code": "DJI",
        "name": "道琼斯",
        "price": 52658.64,
        "change": 150.37,
        "change_pct": 0.29,
        "market": "美股",
    },
]

SECTOR_ROWS = [
    {"f14": "光模块", "f12": "BK1001", "f3": 3.21, "f62": 15.5e8},
    {"f14": "半导体设备", "f12": "BK1002", "f3": 2.15, "f62": 12.3e8},
    {"f14": "通信设备", "f12": "BK1003", "f3": 1.88, "f62": 8.7e8},
    {"f14": "消费电子", "f12": "BK1004", "f3": 1.05, "f62": 5.2e8},
    {"f14": "医药", "f12": "BK1005", "f3": 0.55, "f62": 3.1e8},
    {"f14": "地产", "f12": "BK2001", "f3": -1.82, "f62": -8.0e8},
    {"f14": "银行", "f12": "BK2002", "f3": -0.85, "f62": -5.0e8},
    {"f14": "钢铁", "f12": "BK2003", "f3": -0.52, "f62": -3.0e8},
    {"f14": "煤炭", "f12": "BK2004", "f3": -0.35, "f62": -2.0e8},
    {"f14": "纺织", "f12": "BK2005", "f3": -0.22, "f62": -1.0e8},
]

VALUATION_ROWS = [
    {
        "symbol": "001513",
        "name": "易方达信息产业混合A",
        "position_type": "fund",
        "market_value": 16000,
        "unrealized_pnl_pct": None,
        "today_estimated_pct": 2.55,
        "estimated_at": "2026-07-16T10:00:00",
        "stale": False,
    },
    {
        "symbol": "022184",
        "name": "富国全球科技互联网",
        "position_type": "fund",
        "market_value": 12000,
        "unrealized_pnl_pct": None,
        "today_estimated_pct": 1.20,
        "estimated_at": "2026-07-16T10:00:00",
        "stale": False,
    },
    {
        "symbol": "013171",
        "name": "华夏恒生互联网科技业ETF联接",
        "position_type": "fund",
        "market_value": 8000,
        "unrealized_pnl_pct": None,
        "today_estimated_pct": -0.85,
        "estimated_at": "2026-07-16T10:00:00",
        "stale": False,
    },
    {
        "symbol": "006503",
        "name": "财通集成电路产业股票C",
        "position_type": "fund",
        "market_value": 10000,
        "unrealized_pnl_pct": None,
        "today_estimated_pct": 1.85,
        "estimated_at": "2026-07-16T10:00:00",
        "stale": False,
    },
]


def _mock_async_session():
    """Create a mock that works as ``async with async_session() as db:``."""
    mock = MagicMock()
    mock.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
    mock.return_value.__aexit__ = AsyncMock(return_value=None)
    return mock


def _patch_live_data():
    """Context-manager stack patching all live data sources + Claude CLI."""
    return (
        patch("app.tasks.daily_summary.GlobalIndexProvider"),
        patch("app.services.sector_card_service._fetch_eastmoney_all_sectors"),
        patch("app.tasks.daily_summary.async_session"),
        patch("app.tasks.daily_summary.PortfolioValuationService"),
        patch(
            "app.tasks.daily_summary._run_claude_skill_summary", new_callable=AsyncMock
        ),
    )


# ─── A3: _local_market_snapshot ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_live_snapshot_returns_real_indices_and_meta():
    """Live mode: mocked provider returns rows -> is_mock False, source eastmoney."""
    with patch("app.tasks.daily_summary.GlobalIndexProvider") as mock_cls, patch(
        "app.services.sector_card_service._fetch_eastmoney_all_sectors",
        return_value=SECTOR_ROWS,
    ):
        mock_cls.return_value.get_indices = AsyncMock(return_value=INDEX_ROWS)

        snapshot = await ds._local_market_snapshot()

    assert snapshot["meta"].is_mock is False
    assert snapshot["meta"].source == "eastmoney"
    assert snapshot["meta"].status == "ok"
    assert len(snapshot["indices"]) == len(INDEX_ROWS)
    sh = next(i for i in snapshot["indices"] if i["code"] == "000001")
    assert sh["change_pct"] == -0.82
    # sectors converted from raw f14/f3/f62
    assert len(snapshot["capital_flow"]["sectors"]) == len(SECTOR_ROWS)
    top = snapshot["sectors_top"]
    assert top[0]["name"] == "光模块"  # highest net_flow
    assert top[0]["net_flow"] == 15.5e8
    # live mode must NOT use mock sentiment
    assert snapshot["sentiment"] == {}


@pytest.mark.asyncio
async def test_live_snapshot_fail_closed_on_data_unavailable():
    """Provider raises DataUnavailable -> status unavailable, no mock data leaked."""
    with patch("app.tasks.daily_summary.GlobalIndexProvider") as mock_cls, patch(
        "app.services.sector_card_service._fetch_eastmoney_all_sectors", return_value=[]
    ):
        mock_cls.return_value.get_indices = AsyncMock(
            side_effect=DataUnavailable("eastmoney down")
        )

        snapshot = await ds._local_market_snapshot()

    assert snapshot["meta"].status == "unavailable"
    assert snapshot["indices"] == []
    # NO mock data leaked -- MarketDataProvider would have random change_pct values
    # and sentiment; assert sentiment is empty (not mock)
    assert snapshot["sentiment"] == {}
    assert snapshot["meta"].is_mock is False


@pytest.mark.asyncio
async def test_live_snapshot_partial_failure_status_empty():
    """Indices ok but sectors empty -> status empty (not unavailable)."""
    with patch("app.tasks.daily_summary.GlobalIndexProvider") as mock_cls, patch(
        "app.services.sector_card_service._fetch_eastmoney_all_sectors", return_value=[]
    ):
        mock_cls.return_value.get_indices = AsyncMock(return_value=INDEX_ROWS)

        snapshot = await ds._local_market_snapshot()

    assert snapshot["meta"].status == "empty"
    assert len(snapshot["indices"]) == len(INDEX_ROWS)
    assert snapshot["capital_flow"]["sectors"] == []


@pytest.mark.asyncio
async def test_demo_snapshot_uses_mock_provider():
    """Demo mode: MarketDataProvider mock -> is_mock True, source demo/mock."""
    with patch.object(ds.settings, "market_data_mode", "demo"):
        snapshot = await ds._local_market_snapshot()

    assert snapshot["meta"].is_mock is True
    assert snapshot["meta"].source == "demo/mock"
    assert snapshot["meta"].status == "ok"
    assert len(snapshot["indices"]) > 0
    assert snapshot["sentiment"] != {}  # demo mode has mock sentiment


# ─── B4: _portfolio_context ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_portfolio_context_overseas_sorts_first():
    """Overseas-exposed holding ranks before pure-A-share of equal/higher value."""
    mock_session = _mock_async_session()
    with patch("app.tasks.daily_summary.async_session", mock_session), patch(
        "app.tasks.daily_summary.PortfolioValuationService"
    ) as mock_svc:
        mock_svc.return_value.get_live_valuation = AsyncMock(
            return_value=VALUATION_ROWS
        )

        portfolio = await ds._portfolio_context()

    positions = portfolio["positions"]
    assert len(positions) == 4
    codes = [p["code"] for p in positions]
    # 022184 (overseas, mv=12000) must come before 001513 (A-share, mv=16000)
    assert codes.index("022184") < codes.index("001513")
    # 013171 (overseas, mv=8000) must also come before 001513
    assert codes.index("013171") < codes.index("001513")
    # within overseas: 022184 (mv=12000) before 013171 (mv=8000)
    assert codes.index("022184") < codes.index("013171")
    # within A-share: 001513 (mv=16000) before 006503 (mv=10000)
    assert codes.index("001513") < codes.index("006503")
    # today_estimated_pct is carried through
    by_code = {p["code"]: p for p in positions}
    assert by_code["001513"]["today_estimated_pct"] == 2.55
    assert by_code["022184"]["today_estimated_pct"] == 1.20


@pytest.mark.asyncio
async def test_portfolio_context_empty_valuation():
    """No holdings -> zero totals, empty positions."""
    mock_session = _mock_async_session()
    with patch("app.tasks.daily_summary.async_session", mock_session), patch(
        "app.tasks.daily_summary.PortfolioValuationService"
    ) as mock_svc:
        mock_svc.return_value.get_live_valuation = AsyncMock(return_value=[])

        portfolio = await ds._portfolio_context()

    assert portfolio["total_value"] == 0
    assert portfolio["positions"] == []


@pytest.mark.asyncio
async def test_portfolio_context_exception_returns_error():
    """Service exception -> error dict with empty positions (defense)."""
    mock_session = _mock_async_session()
    mock_session.side_effect = RuntimeError("db connection lost")
    with patch("app.tasks.daily_summary.async_session", mock_session):
        portfolio = await ds._portfolio_context()

    assert "error" in portfolio
    assert portfolio["positions"] == []


# ─── C2: _build_facts us_overnight ──────────────────────────────────────────


def test_build_facts_us_overnight_returns_overseas_indices_and_impacted():
    """us_overnight facts: overseas indices + impacted holdings (not A-share)."""
    snapshot = {"indices": INDEX_ROWS}
    portfolio = {
        "positions": [
            {
                "code": "022184",
                "name": "富国全球科技互联网",
                "market_value": 12000,
                "pnl_pct": 0,
                "today_estimated_pct": 1.20,
                "stale": False,
            },
            {
                "code": "001513",
                "name": "易方达信息产业混合A",
                "market_value": 16000,
                "pnl_pct": 0,
                "today_estimated_pct": 2.55,
                "stale": False,
            },
        ]
    }
    facts = ds._build_facts("us_overnight", snapshot, portfolio)

    overseas_codes = {i["code"] for i in facts["overseas_indices"]}
    assert overseas_codes == {"DJI", "SPX", "IXIC", "N225", "KOSPI", "HSI"}
    assert "000001" not in overseas_codes  # A-share excluded

    impacted_codes = {h["code"] for h in facts["impacted_holdings"]}
    assert "022184" in impacted_codes  # overseas-exposed
    assert "001513" not in impacted_codes  # pure A-share excluded

    # impact_pct should be computed from overnight index
    impacted = facts["impacted_holdings"][0]
    assert impacted["impact_pct"] is not None
    assert impacted["today_estimated_pct"] == 1.20


def test_build_facts_us_overnight_impact_pct_uses_beta():
    """纳指 holding impact ≈ IXIC change_pct * 1.0 beta."""
    snapshot = {
        "indices": [
            {"code": "IXIC", "name": "纳斯达克", "change_pct": 0.62, "price": 26269.23},
        ]
    }
    portfolio = {
        "positions": [
            {
                "code": "022184",
                "name": "纳指100ETF",
                "market_value": 10000,
                "pnl_pct": 0,
                "today_estimated_pct": None,
                "stale": False,
            },
        ]
    }
    facts = ds._build_facts("us_overnight", snapshot, portfolio)
    impacted = facts["impacted_holdings"][0]
    assert impacted["impact_pct"] == pytest.approx(0.62, abs=0.01)


# ─── C3: _build_facts morning ───────────────────────────────────────────────


def test_build_facts_morning_returns_ashare_and_real_sectors():
    """morning facts: A-share indices + real sector names (not synthesized 'AI')."""
    sectors_top = [
        {
            "name": "光模块",
            "sector_name": "光模块",
            "code": "BK1001",
            "net_flow": 15.5e8,
            "capital_flow": 15.5e8,
            "change_pct": 3.21,
        },
        {
            "name": "半导体设备",
            "sector_name": "半导体设备",
            "code": "BK1002",
            "net_flow": 12.3e8,
            "capital_flow": 12.3e8,
            "change_pct": 2.15,
        },
        {
            "name": "通信设备",
            "sector_name": "通信设备",
            "code": "BK1003",
            "net_flow": 8.7e8,
            "capital_flow": 8.7e8,
            "change_pct": 1.88,
        },
    ]
    sectors_bottom = [
        {
            "name": "地产",
            "sector_name": "地产",
            "code": "BK2001",
            "net_flow": -8.0e8,
            "capital_flow": -8.0e8,
            "change_pct": -1.82,
        },
        {
            "name": "银行",
            "sector_name": "银行",
            "code": "BK2002",
            "net_flow": -5.0e8,
            "capital_flow": -5.0e8,
            "change_pct": -0.85,
        },
        {
            "name": "钢铁",
            "sector_name": "钢铁",
            "code": "BK2003",
            "net_flow": -3.0e8,
            "capital_flow": -3.0e8,
            "change_pct": -0.52,
        },
    ]
    snapshot = {
        "indices": INDEX_ROWS,
        "sectors_top": sectors_top,
        "sectors_bottom": sectors_bottom,
    }
    portfolio = {"positions": []}
    facts = ds._build_facts("morning", snapshot, portfolio)

    ashare_codes = {i["code"] for i in facts["ashare_indices"]}
    assert ashare_codes == {"000001", "399001", "000300", "399006", "000688"}
    assert "IXIC" not in ashare_codes  # overseas excluded

    inflow_names = [s["name"] for s in facts["top_inflow_sectors"]]
    assert "光模块" in inflow_names
    assert "半导体设备" in inflow_names
    # "AI" must NOT be synthesized -- names come from real sector data
    assert "AI" not in inflow_names
    assert not any("AI" == name for name in inflow_names)

    outflow_names = [s["name"] for s in facts["top_outflow_sectors"]]
    assert "地产" in outflow_names


# ─── C4: _looks_substantive (real-number gate) ──────────────────────────────


def _sample_facts() -> dict:
    return {
        "overseas_indices": [
            {"code": "IXIC", "name": "纳斯达克", "change_pct": 0.62, "price": 26269.23},
        ],
        "impacted_holdings": [
            {
                "name": "富国全球科技互联网",
                "code": "022184",
                "today_estimated_pct": 1.20,
                "impact_pct": 0.56,
                "stale": False,
            },
        ],
    }


def _sample_portfolio() -> dict:
    return {
        "positions": [
            {
                "code": "022184",
                "name": "富国全球科技互联网",
                "market_value": 12000,
                "pnl_pct": 0,
                "today_estimated_pct": 1.20,
                "stale": False,
            },
        ]
    }


def test_looks_substantive_rejects_body_without_facts_numbers():
    """Body with fund name + length + structure but NO facts number -> False."""
    body = (
        "【结论】市场整体偏强，但需要关注后续走势变化，对你的持仓影响中性偏正面。\n"
        "【关键依据】市场整体走势向好，资金面较为宽松，板块轮动节奏正常，"
        "但主线尚未完全确认，需要更多交易日验证趋势的持续性。\n"
        "【影响你的持仓】富国全球科技互联网表现不错，可以继续持有观察，"
        "注意控制仓位不要过度集中，等待更明确的趋势信号再考虑调整。\n"
        "【下一步】关注后续市场变化，注意风险控制，特别是海外市场联动效应。"
    )
    assert len(body) >= ds.SUMMARY_MIN_CHARS
    ok, reason = ds._looks_substantive(body, _sample_facts(), _sample_portfolio())
    assert ok is False
    assert "真实数据" in reason


def test_looks_substantive_accepts_body_with_facts_number():
    """Body with fund name + length + structure + a facts number -> True."""
    body = (
        "【结论】隔夜美股偏强，纳斯达克 +0.62%，对你的富国全球科技互联网仓位偏利好。\n"
        "【关键依据】纳斯达克 +0.62%领涨，道琼斯 +0.29%和标普 +0.25%跟随，"
        "整体美股科技风险偏好回升，但日经 -2.98%和KOSPI -6.84%显示亚太仍有压力。\n"
        "【影响你的持仓】富国全球科技互联网（022184）今日预估 +1.20%，"
        "隔夜影响约 +0.56%，可以继续持有但注意亚太市场拖累风险。\n"
        "【下一步】关注A股科技半导体是否跟随美股风险偏好回升，港股互联网是否同步修复。"
    )
    ok, reason = ds._looks_substantive(body, _sample_facts(), _sample_portfolio())
    assert ok is True
    assert reason == "ok"


def test_looks_substantive_rejects_short_body():
    ok, reason = ds._looks_substantive("太短了", _sample_facts(), _sample_portfolio())
    assert ok is False
    assert "过短" in reason


def test_looks_substantive_skips_number_gate_when_no_facts():
    """When facts have no numbers (data unavailable), number gate is vacuously passed."""
    facts = {"overseas_indices": [], "impacted_holdings": []}
    body = (
        "【结论】市场数据暂缺，无法判断偏强偏弱，建议先观望等待数据恢复后再做决策。\n"
        "【关键依据】海外指数数据源暂时不可用，无法获取隔夜涨跌数据，"
        "需要等待数据源恢复后重新评估市场走势和风险偏好变化趋势，"
        "当前不构成明确的交易信号，保持耐心等待数据恢复是合理选择。\n"
        "【影响你的持仓】富国全球科技互联网继续持有，在数据恢复前不做任何调整，"
        "保持现有仓位不变，关注后续数据恢复后的重新评估结果和持仓影响分析。\n"
        "【下一步】等待数据源恢复后重新评估市场走势，关注后续交易日资金流向和板块轮动信号。"
    )
    assert len(body) >= ds.SUMMARY_MIN_CHARS
    ok, reason = ds._looks_substantive(body, facts, _sample_portfolio())
    assert ok is True


# ─── C4: _concise_local_summary (4-section from real facts) ─────────────────


def test_concise_local_summary_us_overnight_has_4_sections_and_real_numbers():
    facts = _sample_facts()
    text = ds._concise_local_summary(
        "us_overnight", facts, _sample_portfolio(), "claude timeout"
    )

    assert "【结论】" in text
    assert "【关键依据】" in text
    assert "【影响你的持仓】" in text
    assert "【下一步】" in text
    # Real facts number present
    assert "+0.62" in text
    # today_estimated_pct line present
    assert "今日预估" in text
    assert "+1.20" in text
    # impact_pct present
    assert "+0.56" in text
    # Fallback note
    assert "LLM 解读未产出" in text
    assert "claude timeout" in text


def test_concise_local_summary_morning_has_real_sector_names():
    facts = {
        "ashare_indices": [
            {
                "code": "000001",
                "name": "上证指数",
                "change_pct": -0.82,
                "price": 3923.2,
            },
        ],
        "top_inflow_sectors": [
            {"name": "光模块", "net_flow": 15.5e8, "change_pct": 3.21},
        ],
        "top_outflow_sectors": [
            {"name": "地产", "net_flow": -8.0e8, "change_pct": -1.82},
        ],
        "holdings": [
            {
                "name": "易方达信息产业混合A",
                "code": "001513",
                "today_estimated_pct": 2.55,
                "pnl_pct": 0,
                "stale": False,
            },
        ],
    }
    text = ds._concise_local_summary(
        "morning", facts, {"positions": []}, "skill unavailable"
    )

    assert "【结论】" in text
    assert "光模块" in text
    assert "地产" in text
    assert "今日预估" in text
    assert "+2.55" in text
    assert "-0.82" in text
    assert "AI" not in text  # no synthesized "AI"


def test_concise_local_summary_marks_stale_holdings():
    facts = {
        "ashare_indices": [],
        "top_inflow_sectors": [],
        "top_outflow_sectors": [],
        "holdings": [
            {
                "name": "某基金",
                "code": "001111",
                "today_estimated_pct": None,
                "pnl_pct": 0,
                "stale": True,
            },
        ],
    }
    text = ds._concise_local_summary("tail", facts, {"positions": []}, "no data")
    assert "估值可能延迟" in text


# ─── C5: /api/v1/feishu/preview endpoint ────────────────────────────────────


def test_preview_endpoint_returns_message_and_meta_without_push():
    """Preview returns message + meta (is_mock=False in live), does NOT push."""
    mock_session = _mock_async_session()
    with patch("app.tasks.daily_summary.GlobalIndexProvider") as mock_cls, patch(
        "app.services.sector_card_service._fetch_eastmoney_all_sectors",
        return_value=SECTOR_ROWS,
    ), patch("app.tasks.daily_summary.async_session", mock_session), patch(
        "app.tasks.daily_summary.PortfolioValuationService"
    ) as mock_svc, patch(
        "app.tasks.daily_summary._run_claude_skill_summary",
        new_callable=AsyncMock,
        side_effect=RuntimeError("no claude"),
    ), patch(
        "app.feishu.bot.feishu_bot.send_text", new_callable=AsyncMock
    ) as mock_send:

        mock_cls.return_value.get_indices = AsyncMock(return_value=INDEX_ROWS)
        mock_svc.return_value.get_live_valuation = AsyncMock(
            return_value=VALUATION_ROWS
        )

        client = TestClient(app)
        response = client.get(
            "/api/v1/feishu/preview", params={"summary_type": "us_overnight"}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["summary_type"] == "us_overnight"
    assert "message" in data
    assert len(data["message"]) > 0
    assert data["used_fallback"] is True
    assert data["meta"]["is_mock"] is False
    assert data["meta"]["source"] == "eastmoney"
    # Must NOT have pushed to feishu
    mock_send.assert_not_called()


def test_preview_endpoint_unknown_summary_type_returns_422():
    with patch("app.feishu.bot.feishu_bot.send_text", new_callable=AsyncMock):
        client = TestClient(app)
        response = client.get(
            "/api/v1/feishu/preview", params={"summary_type": "bogus"}
        )
    assert response.status_code == 422


def test_preview_endpoint_default_summary_type():
    """No summary_type query param -> defaults to us_overnight."""
    mock_session = _mock_async_session()
    with patch("app.tasks.daily_summary.GlobalIndexProvider") as mock_cls, patch(
        "app.services.sector_card_service._fetch_eastmoney_all_sectors",
        return_value=SECTOR_ROWS,
    ), patch("app.tasks.daily_summary.async_session", mock_session), patch(
        "app.tasks.daily_summary.PortfolioValuationService"
    ) as mock_svc, patch(
        "app.tasks.daily_summary._run_claude_skill_summary",
        new_callable=AsyncMock,
        side_effect=RuntimeError("no claude"),
    ), patch(
        "app.feishu.bot.feishu_bot.send_text", new_callable=AsyncMock
    ):

        mock_cls.return_value.get_indices = AsyncMock(return_value=INDEX_ROWS)
        mock_svc.return_value.get_live_valuation = AsyncMock(
            return_value=VALUATION_ROWS
        )

        client = TestClient(app)
        response = client.get("/api/v1/feishu/preview")

    assert response.status_code == 200
    assert response.json()["summary_type"] == "us_overnight"
