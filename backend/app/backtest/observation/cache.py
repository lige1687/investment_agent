"""Persistent cache for observation judgments (spec §3.1 Pass 2).

The cache makes LLM-backed backtests reproducible: the first run computes
judgments via the LLM and stores them; subsequent runs with the same data
hit the cache and make zero LLM calls.

Cache key = SHA-256 of (symbol, trigger kind/index/date, window-bars hash,
judge/prompt version).  Changing the prompt version or the window data
busts the cache automatically.

Storage: a versioned JSON file under ``backend/data/``.  This matches the
"acceptable for Phase 1" option from the task spec -- a new SQLite table
would be heavier and the backtest module has no existing ORM store.  The
file is read/written atomically (write-to-temp then rename).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from typing import Optional

from app.backtest.models import SignalBar
from app.backtest.observation.schemas import ObservationJudgment
from app.backtest.trigger_scanner import TriggerPoint

logger = logging.getLogger(__name__)

#: Default cache file path (relative to backend root).
_DEFAULT_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "data",
    "observation_cache.json",
)


def compute_cache_key(
    symbol: str,
    trigger: TriggerPoint,
    window_bars: list[SignalBar],
    judge_version: str,
) -> str:
    """Compute a deterministic SHA-256 cache key for one trigger judgment.

    The key incorporates:
    - symbol (reference ETF code)
    - trigger kind / index / date
    - a hash of the window bars' OHLCV data (so different data ≠ hit)
    - the judge/prompt version string (so prompt changes bust the cache)
    """
    bars_data = [
        [
            bar.date.isoformat(),
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
            bar.amount,
        ]
        for bar in window_bars
    ]
    key_payload = json.dumps(
        {
            "symbol": symbol,
            "kind": trigger.kind,
            "index": trigger.index,
            "date": trigger.date.isoformat(),
            "window_bars": bars_data,
            "judge_version": judge_version,
        },
        sort_keys=True,
    )
    return hashlib.sha256(key_payload.encode("utf-8")).hexdigest()


class ObservationCache:
    """JSON-file-backed persistent cache for ObservationJudgment values."""

    def __init__(self, path: Optional[str] = None):
        self._path = path or _DEFAULT_CACHE_PATH

    async def get(self, key: str) -> ObservationJudgment | None:
        """Return the cached judgment for *key*, or ``None`` on miss."""
        data = self._load()
        raw = data.get(key)
        if raw is None:
            return None
        return self._deserialize(raw)

    async def set(self, key: str, judgment: ObservationJudgment) -> None:
        """Store *judgment* under *key*."""
        data = self._load()
        data[key] = self._serialize(judgment)
        self._save(data)

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict) -> None:
        directory = os.path.dirname(self._path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        # Atomic write: temp file in same dir, then rename
        fd, tmp_path = tempfile.mkstemp(
            dir=directory or ".", suffix=".tmp", prefix=".cache_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, sort_keys=True)
            os.replace(tmp_path, self._path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize(judgment: ObservationJudgment) -> dict:
        return {
            "decision": judgment.decision,
            "confirmed": judgment.confirmed,
            "reason": judgment.reason,
            "gate": judgment.gate,
        }

    @staticmethod
    def _deserialize(raw: dict) -> ObservationJudgment:
        return ObservationJudgment(
            decision=raw["decision"],
            confirmed=raw["confirmed"],
            reason=raw["reason"],
            gate=raw.get("gate"),
        )
