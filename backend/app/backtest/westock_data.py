"""westock-data CLI adapter for signal asset K-line data."""
from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Awaitable, Callable

from app.backtest.models import SignalBar

WESTOCK_PACKAGE = "westock-data-skillhub@1.0.3"
Runner = Callable[[list[str], int], Awaitable[str]]


def parse_kline_markdown(output: str) -> list[SignalBar]:
    """Parse westock-data kline Markdown table output into chronological bars."""
    text = output.strip()
    if not text:
        return []
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("westock-data returned invalid JSON output") from exc
        if payload.get("success") is False:
            raise ValueError(f"westock-data returned an error: {payload.get('error')}")

    rows = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    data_rows = [
        row for row in rows
        if "---" not in row and "date" not in row.lower()
    ]
    bars: list[SignalBar] = []
    for row in data_rows:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        if len(cells) < 7:
            continue
        bars.append(SignalBar(
            date=date.fromisoformat(cells[0]),
            open=float(cells[1]),
            close=float(cells[2]),
            high=float(cells[3]),
            low=float(cells[4]),
            volume=float(cells[5]),
            amount=float(cells[6]),
        ))
    return sorted(bars, key=lambda item: item.date)


class WestockDataClient:
    """Small async wrapper around the westock-data SkillHub npm CLI."""

    def __init__(self, runner: Runner | None = None):
        self._runner = runner or _run_command

    async def fetch_kline(
        self,
        symbol: str,
        period: str = "day",
        limit: int = 200,
        timeout: int = 30,
    ) -> list[SignalBar]:
        args = [
            "npx",
            "-y",
            WESTOCK_PACKAGE,
            "kline",
            symbol,
            "--period",
            period,
            "--limit",
            str(limit),
        ]
        output = await self._runner(args, timeout)
        return parse_kline_markdown(output)


async def _run_command(args: list[str], timeout: int) -> str:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise TimeoutError(f"westock-data command timed out after {timeout}s") from exc

    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        detail = stderr_text.strip() or stdout_text.strip()
        raise RuntimeError(f"westock-data command failed: {detail[:1000]}")
    return stdout_text

