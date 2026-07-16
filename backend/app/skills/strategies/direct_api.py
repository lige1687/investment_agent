"""Strategy 1: Direct API access to eastmoney HTTP APIs.

Fast and free. Used for real-time market data, K-line, indices, and sector data.
"""

import asyncio
import logging
from typing import Any

import httpx

from app.config import settings
from app.services.global_index_provider import DataUnavailable, GlobalIndexProvider
from app.services.market_data_trust import validate_quote_rows
from app.skills.base import SkillRequest, SkillResult, SkillStrategy

logger = logging.getLogger(__name__)

# eastmoney realtime stock/ETF quote endpoint (absolute URL; do NOT use the
# THS base_url client for these).
_EASTMONEY_STOCK_URL = "https://push2.eastmoney.com/api/qt/stock/get"
_EASTMONEY_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_QUOTE_CHUNK_SIZE = 8  # cap concurrent quote requests to avoid bursts

# Skills this strategy can handle
DIRECT_API_SKILLS = {
    "market_quote",
    "kline_data",
    "index_quote",
    "sector_data",
    "etf_quotes",
    "fund_nav",
    # Also try direct for diagnosis data sources
    "sentiment_analysis",
    "sector_rotation_analysis",
    "north_bound_flow",
}


class DirectAPIStrategy(SkillStrategy):
    """Fetches data directly from THS HTTP APIs."""

    def __init__(self):
        self._base_url = settings.ths_api_base_url
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(10.0),
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                    "Accept": "application/json",
                },
            )
        return self._client

    def can_handle(self, skill_name: str) -> bool:
        return skill_name in DIRECT_API_SKILLS

    async def execute(self, request: SkillRequest) -> SkillResult:
        handler = self._get_handler(request.skill_name)
        if handler is None:
            return SkillResult(
                success=False,
                error=f"No handler for {request.skill_name}",
                strategy_used="direct_api",
            )

        try:
            data = await handler(**request.params)
            return SkillResult(success=True, data=data, strategy_used="direct_api")
        except httpx.HTTPError as e:
            logger.error(f"Direct API error for {request.skill_name}: {e}")
            return SkillResult(success=False, error=str(e), strategy_used="direct_api")
        except Exception as e:
            logger.error(
                f"Unexpected error in direct_api for {request.skill_name}: {e}"
            )
            return SkillResult(success=False, error=str(e), strategy_used="direct_api")

    def _get_handler(self, skill_name: str):
        handlers = {
            "market_quote": self._fetch_quotes,
            "kline_data": self._fetch_kline,
            "index_quote": self._fetch_indices,
            "sector_data": self._fetch_sector_data,
            "etf_quotes": self._fetch_quotes,  # Same handler as market_quote
            "fund_nav": self._fetch_fund_nav,
        }
        return handlers.get(skill_name)

    async def _fetch_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        """Fetch real-time quotes for given stock/ETF symbols via eastmoney.

        Symbols use unprefixed app codes (e.g. ``510050``, ``159915``). The
        eastmoney secid prefix is derived from the first digit: ``5/6/9`` ->
        Shanghai (``1.``), otherwise Shenzhen (``0.``).

        Returns a list of unified rows ``{symbol, code, name, price, change,
        change_pct}``. Individual symbol failures are skipped; if every symbol
        fails or is rejected by validation, :class:`DataUnavailable` propagates
        so the strategy reports failure (fail-closed).
        """
        if not symbols:
            return []

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            headers={"User-Agent": _EASTMONEY_UA, "Accept": "application/json"},
        ) as client:
            fetched: list[dict[str, Any] | None] = []
            for i in range(0, len(symbols), _QUOTE_CHUNK_SIZE):
                chunk = symbols[i : i + _QUOTE_CHUNK_SIZE]
                fetched.extend(
                    await asyncio.gather(
                        *(self._fetch_one_quote(client, s) for s in chunk)
                    )
                )

        quotes = [q for q in fetched if q is not None]
        valid, rejected = validate_quote_rows(quotes)
        for sym in rejected:
            logger.debug("quote row rejected by trust validation: %s", sym)

        if not valid:
            raise DataUnavailable("all quote rows failed or rejected validation")
        return valid

    @staticmethod
    def _secid_for_symbol(symbol: str) -> str:
        """Build an eastmoney secid for a stock/ETF symbol (unprefixed code)."""
        code = symbol.strip()
        if code and code[0] in ("5", "6", "9"):
            return f"1.{code}"
        return f"0.{code}"

    async def _fetch_one_quote(
        self, client: httpx.AsyncClient, symbol: str
    ) -> dict[str, Any] | None:
        """Fetch a single realtime quote. Returns ``None`` on any per-symbol failure."""
        secid = self._secid_for_symbol(symbol)
        params = {"secid": secid, "fields": "f43,f57,f58,f169,f170", "fltt": 2}
        try:
            resp = await client.get(_EASTMONEY_STOCK_URL, params=params)
        except httpx.HTTPError:
            logger.warning("eastmoney stock get failed for %s", symbol)
            return None
        if resp.status_code != 200:
            logger.warning(
                "eastmoney stock get status %s for %s", resp.status_code, symbol
            )
            return None
        try:
            payload = resp.json()
        except ValueError:
            return None
        data = (payload or {}).get("data") or {}
        if not data:
            return None
        return {
            "symbol": symbol,
            "code": str(data.get("f57") or symbol),
            "name": str(data.get("f58") or ""),
            "price": data.get("f43"),
            "change": data.get("f169"),
            "change_pct": data.get("f170"),
        }

    async def _fetch_kline(
        self,
        symbol: str,
        period: str = "daily",
        count: int = 120,
    ) -> dict[str, Any]:
        """Fetch K-line candlestick data.

        NOTE: STUB - actual endpoint TBD.
        """
        client = await self._get_client()
        # TODO: Replace with actual THS K-line API
        response = await client.get(
            "/api/kline",
            params={
                "code": symbol,
                "period": period,
                "count": count,
            },
        )
        response.raise_for_status()
        return response.json()

    async def _fetch_indices(
        self, codes: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Fetch major index quotes via the eastmoney-backed GlobalIndexProvider.

        Returns a list of unified rows directly so ``SkillResult.data`` is a
        list (``MarketService.get_global_indices`` checks
        ``isinstance(result.data, list)``). On :class:`DataUnavailable` the
        exception propagates; ``execute`` wraps it into ``SkillResult(success=False)``.
        """
        if codes is None:
            codes = [
                "000001",
                "399001",
                "000300",
                "399006",
                "000688",
                "HSI",
                "N225",
                "KOSPI",
                "IXIC",
                "SPX",
                "DJI",
            ]
        return await GlobalIndexProvider().get_indices(codes)

    async def _fetch_sector_data(
        self,
        sector_type: str = "industry",
        sort_by: str = "change_pct",
        limit: int = 50,
    ) -> dict[str, Any]:
        """Fetch sector/industry performance data.

        NOTE: STUB - actual endpoint TBD.
        """
        client = await self._get_client()
        response = await client.get(
            "/api/sectors",
            params={
                "type": sector_type,
                "sort": sort_by,
                "limit": limit,
            },
        )
        response.raise_for_status()
        return response.json()

    async def _fetch_fund_nav(self, code: str) -> dict[str, Any]:
        """Fetch fund NAV data.

        NOTE: STUB - actual endpoint TBD.
        """
        client = await self._get_client()
        response = await client.get(f"/api/fund/{code}/nav")
        response.raise_for_status()
        return response.json()
