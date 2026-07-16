"""Real-time global index provider backed by the eastmoney push2 batch API.

Fail-closed: any transport / parse / validation failure raises
:class:`DataUnavailable`. Demo mode is NOT handled here -- callers (e.g.
``MarketService``) fall back to the deterministic ``MarketDataProvider`` when
``settings.market_data_mode == "demo"``. This module never returns mock data.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.market_data_trust import validate_index_rows

logger = logging.getLogger(__name__)


class DataUnavailable(Exception):
    """Raised when the live index source is unreachable or untrustworthy.

    Callers MUST surface this as an ``unavailable`` status rather than
    substituting mock data (market-data trust boundary).
    """


# App (unprefixed) index code -> eastmoney secid. Verified against
# push2.eastmoney.com/api/qt/ulist.np/get on 2026-07-16.
CODE_TO_SECID: dict[str, str] = {
    "000001": "1.000001",  # 上证指数
    "399001": "0.399001",  # 深证成指
    "000300": "1.000300",  # 沪深300
    "399006": "0.399006",  # 创业板指
    "000688": "1.000688",  # 科创50
    "000016": "1.000016",  # 上证50
    "HSI": "100.HSI",  # 恒生指数
    "N225": "100.N225",  # 日经225
    "KOSPI": "100.KS11",  # 韩国KOSPI (alias)
    "IXIC": "100.NDX",  # 纳斯达克综合 (alias)
    "SPX": "100.SPX",  # 标普500
    "DJI": "100.DJIA",  # 道琼斯 (alias)
    "VIX": "100.VIX",  # VIX (optional)
    "USDX": "100.USDX",  # 美元指数 (optional)
}

# Market classification by app index code for downstream grouping.
MARKET_BY_CODE: dict[str, str] = {
    "000001": "A股",
    "399001": "A股",
    "000300": "A股",
    "399006": "A股",
    "000688": "A股",
    "000016": "A股",
    "HSI": "港股",
    "N225": "日股",
    "KOSPI": "韩股",
    "IXIC": "美股",
    "SPX": "美股",
    "DJI": "美股",
    "VIX": "美股",
    "USDX": "宏观",
}

_EASTMONEY_ULIST_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
_DEFAULT_TIMEOUT = 10.0
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def _secid_for_index_code(code: str) -> str:
    """Map an app index code to an eastmoney secid.

    Explicit aliases win; numeric A-share index codes fall back to the
    Shenzhen (``0.``) / Shanghai (``1.``) prefix rule; other named codes
    default to the overseas ``100.`` prefix.
    """
    if code in CODE_TO_SECID:
        return CODE_TO_SECID[code]
    if code.isdigit():
        return f"0.{code}" if code.startswith("399") else f"1.{code}"
    return f"100.{code}"


def _market_for_code(code: str) -> str:
    return MARKET_BY_CODE.get(code, "其他")


class GlobalIndexProvider:
    """Fetches global index quotes from eastmoney's push2 batch endpoint."""

    async def _fetch_ulist(self, secids: list[str]) -> list[dict[str, Any]]:
        """Return raw eastmoney ``data.diff`` rows for the given secids."""
        params = {
            "secids": ",".join(secids),
            "fields": "f12,f14,f2,f3,f4,f5",
            "fltt": 2,
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(_DEFAULT_TIMEOUT),
                headers={"User-Agent": _UA, "Accept": "application/json"},
            ) as client:
                resp = await client.get(_EASTMONEY_ULIST_URL, params=params)
        except httpx.HTTPError as exc:
            raise DataUnavailable(f"eastmoney ulist request failed: {exc}") from exc

        if resp.status_code != 200:
            raise DataUnavailable(f"eastmoney ulist returned status {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise DataUnavailable(
                f"eastmoney ulist returned non-JSON body: {exc}"
            ) from exc

        diff = ((payload or {}).get("data") or {}).get("diff") or []
        if not diff:
            raise DataUnavailable("eastmoney ulist returned empty diff")
        return diff

    async def get_indices(self, codes: list[str]) -> list[dict[str, Any]]:
        """Fetch validated index rows for the given app codes.

        Returns unified rows ``{code, name, price, change, change_pct, market}``.
        Raises :class:`DataUnavailable` when the source is unreachable, empty,
        or every row fails validation. NEVER returns mock data.
        """
        if not codes:
            return []

        requested = {c: _secid_for_index_code(c) for c in codes}
        # Reverse-lookup eastmoney symbol (the part after the prefix) -> app
        # code so alias codes (KOSPI->KS11, IXIC->NDX, DJI->DJIA) map back.
        symbol_to_app_code: dict[str, str] = {}
        for app_code, secid in requested.items():
            symbol = secid.split(".", 1)[1] if "." in secid else secid
            symbol_to_app_code[symbol] = app_code

        diff = await self._fetch_ulist(list(requested.values()))

        rows: list[dict[str, Any]] = []
        for item in diff:
            raw_code = str(item.get("f12") or "").strip()
            code = symbol_to_app_code.get(raw_code, raw_code)
            rows.append(
                {
                    "code": code,
                    "name": str(item.get("f14") or "").strip(),
                    "price": item.get("f2"),
                    "change": item.get("f4"),
                    "change_pct": item.get("f3"),
                    "market": _market_for_code(code),
                }
            )

        valid, rejected = validate_index_rows(rows)
        for code in rejected:
            logger.debug("global index row rejected by trust validation: %s", code)

        if not valid:
            raise DataUnavailable("all index rows rejected by trust validation")
        return valid

    async def get_index(self, code: str) -> dict[str, Any] | None:
        """Fetch a single index row.

        Returns the row on success, ``None`` if the code was absent from a
        successful response, and raises :class:`DataUnavailable` on fetch
        failure.
        """
        rows = await self.get_indices([code])
        return next((row for row in rows if row.get("code") == code), None)
