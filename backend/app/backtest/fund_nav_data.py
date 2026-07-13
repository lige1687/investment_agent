"""Fund NAV data adapters for backtesting."""
from __future__ import annotations

from datetime import date
from typing import Any, Awaitable, Callable

import httpx

from app.backtest.models import FundNavPoint

EASTMONEY_LSJZ_URL = "https://api.fund.eastmoney.com/f10/lsjz"

Fetcher = Callable[
    [str, dict[str, Any], dict[str, str], int],
    Awaitable[dict[str, Any]],
]


def parse_eastmoney_nav_response(payload: dict[str, Any]) -> list[FundNavPoint]:
    """Parse Eastmoney historical fund NAV JSON into chronological points."""
    rows = _extract_lsjz_rows(payload)
    if not rows:
        raise ValueError("missing historical NAV list in Eastmoney response")
    return _rows_to_nav_points(rows)


def _extract_lsjz_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = ((payload.get("Data") or {}).get("LSJZList") or [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _rows_to_nav_points(rows: list[dict[str, Any]]) -> list[FundNavPoint]:
    points: list[FundNavPoint] = []
    for row in rows:
        raw_date = row.get("FSRQ")
        raw_nav = row.get("DWJZ")
        if not raw_date or raw_nav in (None, ""):
            continue
        try:
            points.append(FundNavPoint(date=date.fromisoformat(str(raw_date)), nav=float(raw_nav)))
        except (TypeError, ValueError):
            continue
    return sorted(points, key=lambda item: item.date)


class EastmoneyFundNavClient:
    """Fetch historical fund NAV from Eastmoney's public fund endpoint."""

    def __init__(self, fetcher: Fetcher | None = None):
        self._fetcher = fetcher or _fetch_json

    async def fetch_nav(
        self,
        fund_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        page_size: int = 100,
        timeout: int = 15,
    ) -> list[FundNavPoint]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Referer": f"https://fundf10.eastmoney.com/jjjz_{fund_code}.html",
        }
        points_by_date: dict[date, FundNavPoint] = {}
        page_index = 1
        while True:
            params = {
                "fundCode": fund_code,
                "pageIndex": page_index,
                "pageSize": page_size,
                "startDate": start_date.isoformat() if start_date else "",
                "endDate": end_date.isoformat() if end_date else "",
            }
            payload = await self._fetcher(EASTMONEY_LSJZ_URL, params, headers, timeout)
            rows = _extract_lsjz_rows(payload)
            if not rows:
                if page_index == 1:
                    raise ValueError("missing historical NAV list in Eastmoney response")
                break

            page_points = _rows_to_nav_points(rows)
            for point in page_points:
                points_by_date[point.date] = point

            oldest_page_date = min((point.date for point in page_points), default=None)
            if (start_date and oldest_page_date and oldest_page_date <= start_date) or _is_last_page(payload, len(rows), page_size):
                break
            page_index += 1

        return sorted(points_by_date.values(), key=lambda item: item.date)


def _is_last_page(payload: dict[str, Any], row_count: int, requested_page_size: int) -> bool:
    total_count = _to_int(payload.get("TotalCount"))
    response_page_size = _to_int(payload.get("PageSize"))
    response_page_index = _to_int(payload.get("PageIndex"))
    if total_count is not None and response_page_size and response_page_index:
        return response_page_index * response_page_size >= total_count
    return row_count < requested_page_size


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _fetch_json(
    url: str,
    params: dict[str, Any],
    headers: dict[str, str],
    timeout: int,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Eastmoney response was not a JSON object")
        return data
