"""Yangjibao browser-plug-api client.

Real API: http://browser-plug-api.yangjibao.com
Auth: md5(signPath + token + timestamp + secret) signature
  - Request-Time: unix timestamp
  - Request-Sign: md5 hex
  - Authorization: token (from QR scan)
"""
import hashlib
import logging
import time
from typing import Optional
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


def _yjb_sign(path: str, timestamp: int, token: str, secret: str) -> str:
    """Generate signature: md5(signPath + token + timestamp + secret).

    signPath = path without query string (e.g. /fund_hold).
    """
    sign_path = path.split("?")[0] if "?" in path else path
    sign_str = f"{sign_path}{token}{timestamp}{secret}"
    return hashlib.md5(sign_str.encode()).hexdigest()


class YangjibaoClient:
    """HTTP client for 养基宝 browser-plug-api."""

    def __init__(self, token: Optional[str] = None):
        self._base_url = settings.yangjibao_api_base_url.rstrip("/")
        self._secret = settings.yangjibao_api_secret
        self._token = token

    @property
    def token(self) -> Optional[str]:
        return self._token

    @token.setter
    def token(self, value: Optional[str]):
        self._token = value

    def _build_headers(self, path: str) -> dict:
        """Build signed request headers. Sign is ALWAYS required."""
        headers = {"Content-Type": "application/json"}
        token = self._token or ""
        ts = int(time.time())
        sign = _yjb_sign(path, ts, token, self._secret)
        headers["Request-Time"] = str(ts)
        headers["Request-Sign"] = sign
        if token:
            headers["Authorization"] = token
        return headers

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make a signed request to Yangjibao."""
        url = f"{self._base_url}{path}"
        headers = self._build_headers(path)
        headers.update(kwargs.pop("headers", {}))

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.request(method, url, headers=headers, **kwargs)
                    resp.raise_for_status()
                    data = resp.json()
                    # Unwrap if has data field
                    if isinstance(data, dict) and "data" in data and data.get("code") == 200:
                        return data["data"]
                    return data
            except httpx.HTTPStatusError as e:
                if attempt < 2:
                    await httpx.sleep(0.35 * (attempt + 1))
                    continue
                raise
            except httpx.RequestError as e:
                if attempt < 2:
                    await httpx.sleep(0.35 * (attempt + 1))
                    continue
                raise

    async def get(self, path: str, **kwargs) -> dict:
        return await self._request("GET", path, **kwargs)

    # ── QR Code Login ──

    async def get_qr_code(self) -> dict:
        """GET /qr_code → { id, url }"""
        data = await self.get("/qr_code")
        qr_id = data.get("id", "")
        qr_url = data.get("url", "")
        if not qr_id or not qr_url:
            raise ValueError(f"QR code response missing id/url: {data}")
        return {"qr_id": qr_id, "qr_url": qr_url}

    async def check_qr_status(self, qr_id: str) -> dict:
        """GET /qr_code_state/{qr_id} → { state: 1|2|3, token? }

        state: 1=pending, 2=confirmed, 3=expired
        """
        data = await self.get(f"/qr_code_state/{qr_id}")
        state_code = data.get("state")
        state_map = {"1": "pending", "2": "confirmed", "3": "expired"}
        state = state_map.get(str(state_code), "unknown")
        result = {"state": state}
        if state == "confirmed":
            token = data.get("token", "")
            result["access_token"] = token
        return result

    # ── Portfolio Data (authenticated) ──

    async def get_user_accounts(self) -> list[dict]:
        """GET /user_account → { list: [{ id, ... }] }"""
        data = await self.get("/user_account")
        accounts = data.get("list", []) if isinstance(data, dict) else []
        return accounts if isinstance(accounts, list) else []

    async def get_fund_holdings(self, account_id: str) -> list[dict]:
        """GET /fund_hold?account_id={id} → [holdings]"""
        data = await self.get(f"/fund_hold?account_id={account_id}")
        if isinstance(data, list):
            return data
        return data.get("list", data.get("holdings", [])) if isinstance(data, dict) else []

    async def get_all_holdings(self) -> list[dict]:
        """Fetch all holdings across all accounts."""
        accounts = await self.get_user_accounts()
        all_holdings = []
        seen = set()

        for acc in accounts:
            acc_id = acc.get("id", "")
            if not acc_id:
                continue
            holdings = await self.get_fund_holdings(acc_id)
            for h in holdings:
                code = str(h.get("code", "")).replace(r"\D", "")[:6] if hasattr(h, 'get') else ""
                if len(code) == 6 and code not in seen:
                    seen.add(code)
                    all_holdings.append(h)

        logger.info(f"Yangjibao: {len(accounts)} accounts, {len(all_holdings)} unique holdings")
        return all_holdings
