"""Live fund-announcement provider backed by the approved Iwencai skill API."""

from __future__ import annotations

import re
import secrets
from collections import defaultdict
from typing import Any

import httpx


class AnnouncementProviderError(RuntimeError):
    """Safe provider error whose message never includes credentials or raw bodies."""


class IwencaiAnnouncementProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://openapi.iwencai.com",
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client

    async def search_fund(
        self,
        *,
        fund_code: str,
        fund_name: str,
        share_class: str,
        size: int = 30,
    ) -> list[dict[str, Any]]:
        if not self._api_key:
            raise AnnouncementProviderError("iwencai_api_key_missing")
        query = (
            f"{fund_name} {fund_code} 暂停申购 限制大额申购 调整大额申购 "
            "恢复申购 开放申购 公告"
        )
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "X-Claw-Call-Type": "normal",
            "X-Claw-Skill-Id": "announcement-search",
            "X-Claw-Skill-Version": "1.0.0",
            "X-Claw-Plugin-Id": "none",
            "X-Claw-Plugin-Version": "none",
            "X-Claw-Trace-Id": secrets.token_hex(32),
        }
        payload = {
            "query": query,
            "channels": ["announcement"],
            "app_id": "AIME_SKILL",
            "size": max(1, min(size, 50)),
        }
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            response = await client.post(
                f"{self._base_url}/v1/comprehensive/search",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            raw = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AnnouncementProviderError("announcement_search_unavailable") from exc
        finally:
            if owns_client:
                await client.aclose()
        if raw.get("status_code") != 0:
            raise AnnouncementProviderError("announcement_search_rejected")
        return normalize_announcement_results(
            raw, fund_code=fund_code, share_class=share_class
        )


def normalize_announcement_results(
    raw: dict[str, Any],
    *,
    fund_code: str,
    share_class: str,
) -> list[dict[str, Any]]:
    """Normalize only fields required by deterministic effective-state restore."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, item in enumerate(raw.get("data") or []):
        if not isinstance(item, dict):
            continue
        uid = str(item.get("uid") or item.get("id") or index)
        grouped[uid].append(item)

    records: list[dict[str, Any]] = []
    for items in grouped.values():
        representative = items[0]
        codes = {
            str(info.get("code") or "")
            for item in items
            for info in (item.get("stock_infos") or [])
            if isinstance(info, dict)
        }
        combined = "\n".join(
            str(item.get("source_original") or item.get("summary") or "")
            for item in items
        )
        title = str(representative.get("title") or "")
        if fund_code not in codes:
            continue

        action = _parse_action(title, combined)
        effective_date = _parse_effective_date(combined)
        if action is None or effective_date is None:
            continue
        customer_scope = (
            "institutional" if "机构客户" in title + combined
            else "retail" if "个人客户" in title + combined
            else "all"
        )
        share_classes = _parse_share_classes(title + combined, share_class)
        published_at = str(
            representative.get("publish_date")
            or representative.get("published_at")
            or f"{effective_date} 00:00:00"
        )
        records.append(
            {
                "fund_code": fund_code,
                "share_classes": share_classes,
                "customer_scope": customer_scope,
                "action": action,
                "effective_date": effective_date,
                "published_at": published_at,
                "purchase_limit": _parse_purchase_limit(combined) if action == "LIMITED" else None,
                "title": title,
                "url": str(representative.get("url") or ""),
                "source": "同花顺问财",
            }
        )
    return records


def _parse_action(title: str, text: str) -> str | None:
    value = title + "\n" + text
    if any(term in title for term in ("调整大额申购", "暂停大额申购", "限制大额申购", "大额申购限制")):
        return "LIMITED"
    if ("恢复" in title or "取消" in title) and (
        "大额申购" in title or "申购限制" in title
    ):
        return "OPEN"
    if "暂停申购" in title and "暂停大额申购" not in title and "大额申购限制" not in title:
        return "SUSPENDED"
    if any(term in value for term in ("调整大额申购", "暂停大额申购", "限制大额申购", "大额申购限制")):
        return "LIMITED"
    if "开放日常申购" in title or "恢复申购" in title:
        return "OPEN"
    return None


def _parse_effective_date(text: str) -> str | None:
    patterns = (
        r"自\s*(20\d{2})年(\d{1,2})月(\d{1,2})日(?:起)?",
        r"(?:恢复大额申购日|暂停大额申购起始日|申购起始日)\s*\|?\s*"
        r"(20\d{2})年(\d{1,2})月(\d{1,2})日",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            year, month, day = (int(value) for value in match.groups())
            return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def _parse_share_classes(text: str, requested: str) -> list[str]:
    found = [value for value in ("A", "B", "C", "I", "E") if f"{value}类" in text]
    return found or [requested]


def _parse_purchase_limit(text: str) -> float | None:
    match = re.search(r"金额不超过\s*([\d,.]+)\s*(亿元|万元|元)", text)
    if match:
        return _scaled_number(match.group(1), match.group(2))
    match = re.search(
        r"限制申购金额[^\d]{0,60}([\d][\d,.]*)\s*(亿元|万元|元)?", text
    )
    if match:
        return _scaled_number(match.group(1), match.group(2) or "元")
    return None


def _scaled_number(raw: str, unit: str) -> float:
    value = float(raw.replace(",", ""))
    multiplier = {"元": 1, "万元": 10_000, "亿元": 100_000_000}[unit]
    return value * multiplier
