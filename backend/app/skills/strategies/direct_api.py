"""Strategy 1: Direct API access to THS (Tonghuashun) HTTP APIs.

Fast and free. Used for real-time market data, K-line, indices, and sector data.
"""
import logging
from typing import Any
import httpx
from app.config import settings
from app.skills.base import SkillRequest, SkillResult, SkillStrategy

logger = logging.getLogger(__name__)

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
            return SkillResult(success=False, error=f"No handler for {request.skill_name}", strategy_used="direct_api")

        try:
            data = await handler(**request.params)
            return SkillResult(success=True, data=data, strategy_used="direct_api")
        except httpx.HTTPError as e:
            logger.error(f"Direct API error for {request.skill_name}: {e}")
            return SkillResult(success=False, error=str(e), strategy_used="direct_api")
        except Exception as e:
            logger.error(f"Unexpected error in direct_api for {request.skill_name}: {e}")
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

    async def _fetch_quotes(self, symbols: list[str]) -> dict[str, Any]:
        """Fetch real-time quotes for given symbols.

        NOTE: This is a STUB implementation. The actual THS API endpoint
        and authentication method need to be verified via packet capture.
        """
        client = await self._get_client()
        # TODO: Replace with actual THS API endpoint after verification
        # Expected endpoint pattern: /api/quotes?codes=510050,159915
        response = await client.get(
            "/api/quotes",
            params={"codes": ",".join(symbols)},
        )
        response.raise_for_status()
        return response.json()

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

    async def _fetch_indices(self, codes: list[str] | None = None) -> dict[str, Any]:
        """Fetch major index quotes.

        Default indices: SSE Composite, CSI 300, ChiNext, STAR 50
        """
        if codes is None:
            codes = ["000001", "000300", "399006", "000688"]

        return await self._fetch_quotes(codes)

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
