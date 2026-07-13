from datetime import date

import pytest

from app.backtest.fund_nav_data import EastmoneyFundNavClient, parse_eastmoney_nav_response


def test_parse_eastmoney_nav_response_converts_lsjz_rows_to_nav_points():
    payload = {
        "Data": {
            "LSJZList": [
                {"FSRQ": "2026-01-03", "DWJZ": "1.0300"},
                {"FSRQ": "2026-01-02", "DWJZ": "1.0200"},
                {"FSRQ": "2026-01-01", "DWJZ": "1.0100"},
            ]
        }
    }

    points = parse_eastmoney_nav_response(payload)

    assert [point.date for point in points] == [
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
    ]
    assert [point.nav for point in points] == [1.01, 1.02, 1.03]


def test_parse_eastmoney_nav_response_skips_empty_or_invalid_nav_rows():
    payload = {
        "Data": {
            "LSJZList": [
                {"FSRQ": "2026-01-03", "DWJZ": ""},
                {"FSRQ": "2026-01-02", "DWJZ": "abc"},
                {"FSRQ": "2026-01-01", "DWJZ": "1.0100"},
            ]
        }
    }

    points = parse_eastmoney_nav_response(payload)

    assert len(points) == 1
    assert points[0].date == date(2026, 1, 1)


def test_parse_eastmoney_nav_response_rejects_error_payload():
    with pytest.raises(ValueError, match="missing historical NAV list"):
        parse_eastmoney_nav_response({"Data": {}})


@pytest.mark.asyncio
async def test_eastmoney_client_fetches_expected_lsjz_parameters():
    calls = []

    async def fake_fetcher(url, params, headers, timeout):
        calls.append((url, params, headers, timeout))
        return {
            "Data": {
                "LSJZList": [
                    {"FSRQ": "2026-01-02", "DWJZ": "1.0200"},
                    {"FSRQ": "2026-01-01", "DWJZ": "1.0100"},
                ]
            }
        }

    client = EastmoneyFundNavClient(fetcher=fake_fetcher)

    points = await client.fetch_nav(
        fund_code="001513",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        page_size=200,
    )

    assert [point.nav for point in points] == [1.01, 1.02]
    url, params, headers, timeout = calls[0]
    assert url == "https://api.fund.eastmoney.com/f10/lsjz"
    assert params["fundCode"] == "001513"
    assert params["startDate"] == "2026-01-01"
    assert params["endDate"] == "2026-01-31"
    assert params["pageSize"] == 200
    assert "Referer" in headers
    assert timeout == 15


@pytest.mark.asyncio
async def test_eastmoney_client_fetches_all_pages_and_deduplicates_points():
    calls = []
    rows_by_page = {
        1: [
            {"FSRQ": "2026-01-05", "DWJZ": "1.0500"},
            {"FSRQ": "2026-01-04", "DWJZ": "1.0400"},
        ],
        2: [
            {"FSRQ": "2026-01-04", "DWJZ": "1.0400"},
            {"FSRQ": "2026-01-03", "DWJZ": "1.0300"},
        ],
        3: [
            {"FSRQ": "2026-01-02", "DWJZ": "1.0200"},
        ],
    }

    async def fake_fetcher(url, params, headers, timeout):
        calls.append(params.copy())
        return {"Data": {"LSJZList": rows_by_page[params["pageIndex"]]}}

    client = EastmoneyFundNavClient(fetcher=fake_fetcher)

    points = await client.fetch_nav(
        fund_code="001513",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 5),
        page_size=2,
    )

    assert [call["pageIndex"] for call in calls] == [1, 2, 3]
    assert [point.date for point in points] == [
        date(2026, 1, 2),
        date(2026, 1, 3),
        date(2026, 1, 4),
        date(2026, 1, 5),
    ]
    assert [point.nav for point in points] == [1.02, 1.03, 1.04, 1.05]


@pytest.mark.asyncio
async def test_eastmoney_client_uses_response_total_count_when_server_caps_page_size():
    calls = []
    rows_by_page = {
        1: [
            {"FSRQ": "2026-01-05", "DWJZ": "1.0500"},
            {"FSRQ": "2026-01-04", "DWJZ": "1.0400"},
        ],
        2: [
            {"FSRQ": "2026-01-03", "DWJZ": "1.0300"},
        ],
    }

    async def fake_fetcher(url, params, headers, timeout):
        calls.append(params.copy())
        return {
            "Data": {"LSJZList": rows_by_page[params["pageIndex"]]},
            "TotalCount": 3,
            "PageSize": 2,
            "PageIndex": params["pageIndex"],
        }

    client = EastmoneyFundNavClient(fetcher=fake_fetcher)

    points = await client.fetch_nav(
        fund_code="001513",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 5),
        page_size=100,
    )

    assert [call["pageIndex"] for call in calls] == [1, 2]
    assert [point.date for point in points] == [
        date(2026, 1, 3),
        date(2026, 1, 4),
        date(2026, 1, 5),
    ]
