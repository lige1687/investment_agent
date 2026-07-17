"""SectorRegimeProvider: per-sector regime assessment for the sell side.

The provider classifies the market regime (bull/neutral/bear) and take-profit
tightness (loose/normal/tight) for one signal-ETF sector.  It calls the
``batch-trading-market-regime`` skill via SkillBridge, passing the signal-ETF's
trend / drawdown / volume as the *target-sector relative strength* input so the
account-level skill yields a per-sector judgment.

If the skill is unavailable or raises, a **deterministic** signal-ETF trend read
(MA20/60 relationship + drawdown depth) is used as fallback
(``source="fallback_trend"``).  The provider never raises.

Results are cached (``RegimeCache``) keyed by (symbol + as_of date + skill
version) so re-runs are reproducible and zero-skill-call.

Design constraints (spec §11.3, plan Task 4):
- Every skill call goes through SkillBridge (``app.skills.bridge``).
- The skill gives **direction only** (regime state + tightness); it never
  invents trade sizes or amounts.
- Reproducibility: cache key includes the skill SHA-256 version so a skill
  change busts the cache automatically.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from app.backtest.models import BacktestConfig, SignalBar

logger = logging.getLogger(__name__)

RegimeState = Literal["bull", "neutral", "bear"]
RegimeTightness = Literal["loose", "normal", "tight"]

#: Skill name invoked via SkillBridge.
_REGIME_SKILL_NAME = "batch-trading-market-regime"

#: Default cache file path (relative to backend root).
_DEFAULT_REGIME_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "data",
    "regime_cache.json",
)

#: Bump when the parsing / fallback logic changes to bust the cache.
_PROVIDER_VERSION = "regime-provider-v1"


@dataclass(frozen=True)
class SectorRegime:
    """Per-sector regime assessment result.

    - state: bull / neutral / bear
    - take_profit_tightness: loose (let profits run) / normal / tight
    - reason: human-readable explanation
    - skill_versions: list of skill/version strings that influenced the result
    - source: "skill" (skill succeeded) or "fallback_trend" (deterministic fallback)
    """

    state: RegimeState
    take_profit_tightness: RegimeTightness
    reason: str
    skill_versions: list[str] = field(default_factory=list)
    source: str = "fallback_trend"


# ── skill version ───────────────────────────────────────────────────────────


def _skill_version() -> str:
    """Compute a version string for the market-regime skill.

    Hashes the SKILL.md content so a skill change busts the cache.  If the
    file is unavailable (e.g. in CI / tests) returns a stable default.
    """
    candidates = [
        os.path.expanduser("~/.codex/skills/batch-trading-market-regime/SKILL.md"),
        os.path.expanduser(
            "~/.openclaw/workspace/skills/batch-trading-market-regime/SKILL.md"
        ),
    ]
    for path in candidates:
        try:
            with open(path, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()[:12]
                return f"market-regime-{digest}"
        except (FileNotFoundError, OSError):
            continue
    return "market-regime-unknown"


# ── cache key ───────────────────────────────────────────────────────────────


def _regime_cache_key(symbol: str, as_of_date, skill_version: str) -> str:
    """SHA-256 cache key for one (symbol, date, skill-version) regime assessment."""
    payload = json.dumps(
        {
            "symbol": symbol,
            "as_of_date": as_of_date.isoformat(),
            "skill_version": skill_version,
            "provider_version": _PROVIDER_VERSION,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── RegimeCache ─────────────────────────────────────────────────────────────


class RegimeCache:
    """JSON-file-backed persistent cache for SectorRegime values.

    Mirrors the ObservationCache pattern: atomic write (temp + rename),
    deterministic key, survives across runs for reproducibility.
    """

    def __init__(self, path: Optional[str] = None):
        self._path = path or _DEFAULT_REGIME_CACHE_PATH

    async def get(self, key: str) -> SectorRegime | None:
        data = self._load()
        raw = data.get(key)
        if raw is None:
            return None
        return self._deserialize(raw)

    async def set(self, key: str, regime: SectorRegime) -> None:
        data = self._load()
        data[key] = self._serialize(regime)
        self._save(data)

    # -- file I/O --

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
        fd, tmp_path = tempfile.mkstemp(
            dir=directory or ".", suffix=".tmp", prefix=".regime_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, sort_keys=True)
            os.replace(tmp_path, self._path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    @staticmethod
    def _serialize(regime: SectorRegime) -> dict:
        return {
            "state": regime.state,
            "take_profit_tightness": regime.take_profit_tightness,
            "reason": regime.reason,
            "skill_versions": list(regime.skill_versions),
            "source": regime.source,
        }

    @staticmethod
    def _deserialize(raw: dict) -> SectorRegime:
        return SectorRegime(
            state=raw["state"],
            take_profit_tightness=raw["take_profit_tightness"],
            reason=raw["reason"],
            skill_versions=list(raw.get("skill_versions", [])),
            source=raw.get("source", "fallback_trend"),
        )


# ── SectorRegimeProvider ────────────────────────────────────────────────────


class SectorRegimeProvider:
    """Assesses per-sector market regime via skill + deterministic fallback.

    Parameters
    ----------
    skill_bridge : optional
        Object with an async ``invoke_simple(skill_name, params, cache_ttl)``
        method (the SkillBridge interface).  If ``None``, the global
        ``app.skills.bridge.bridge`` is lazily imported on first use.
        Tests inject a fake so no real skill/CLI call is made.
    cache : optional
        A ``RegimeCache`` for persistent reproducibility.  If ``None``,
        no caching (each call hits the skill / fallback).
    """

    def __init__(
        self,
        skill_bridge: Any | None = None,
        cache: RegimeCache | None = None,
    ):
        self._skill_bridge = skill_bridge
        self._cache = cache

    async def assess(
        self,
        symbol: str,
        signal_bars: list[SignalBar],
        as_of_index: int,
        config: BacktestConfig,
    ) -> SectorRegime:
        """Assess the sector regime as of ``signal_bars[as_of_index]``.

        Never raises: on skill failure, falls back to a deterministic
        signal-ETF trend read.
        """
        skill_ver = _skill_version()
        skill_versions = [skill_ver, _PROVIDER_VERSION]
        as_of_date = signal_bars[as_of_index].date

        # Check cache
        cache_key = _regime_cache_key(symbol, as_of_date, skill_ver)
        if self._cache is not None:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        # Try skill
        regime = await self._try_skill(
            symbol, signal_bars, as_of_index, config, skill_versions
        )
        if regime is None:
            regime = self._fallback_trend(
                symbol, signal_bars, as_of_index, config, skill_versions
            )

        # Store in cache
        if self._cache is not None:
            await self._cache.set(cache_key, regime)

        return regime

    # ------------------------------------------------------------------
    # Skill path
    # ------------------------------------------------------------------

    async def _try_skill(
        self,
        symbol: str,
        signal_bars: list[SignalBar],
        as_of_index: int,
        config: BacktestConfig,
        skill_versions: list[str],
    ) -> SectorRegime | None:
        """Call the regime skill; return None on any failure (caller falls back)."""
        params = self._build_params(symbol, signal_bars, as_of_index, config)
        try:
            result = await self._get_bridge().invoke_simple(
                _REGIME_SKILL_NAME,
                params=params,
                cache_ttl=0,  # we use our own RegimeCache for reproducibility
            )
        except Exception as exc:
            logger.warning("SectorRegimeProvider: skill call failed: %s", exc)
            return None

        if not result.success or not result.data:
            logger.warning(
                "SectorRegimeProvider: skill returned failure: %s",
                getattr(result, "error", "unknown"),
            )
            return None

        return self._parse_skill_output(result.data, skill_versions)

    def _get_bridge(self):
        """Lazily resolve the global SkillBridge (never called when injected)."""
        if self._skill_bridge is None:
            from app.skills.bridge import bridge

            self._skill_bridge = bridge
        return self._skill_bridge

    @staticmethod
    def _build_params(
        symbol: str,
        signal_bars: list[SignalBar],
        as_of_index: int,
        config: BacktestConfig,
    ) -> dict:
        """Build the skill params with signal-ETF sector context.

        The skill's SKILL.md lists "target-sector relative strength" under
        "Sector structure and style" (weight 15).  We splice the signal-ETF's
        trend / drawdown / volume into ``sector_context`` so the account-level
        skill yields a per-sector judgment.
        """
        bars = signal_bars[: as_of_index + 1]
        closes = [b.close for b in bars]
        current_price = closes[-1] if closes else 0.0

        ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else current_price
        ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else ma20

        peak = max(closes) if closes else current_price
        drawdown_pct = (peak - current_price) / peak * 100 if peak > 0 else 0.0

        volumes = [b.volume for b in bars]
        vol_ratio: float | None = None
        window = config.buy_volume_window
        if len(volumes) > window:
            baseline = sum(volumes[-(window + 1) : -1]) / window
            vol_ratio = volumes[-1] / baseline if baseline > 0 else None

        return {
            "symbol": symbol,
            "signal_name": config.signal_name,
            "as_of_date": signal_bars[as_of_index].date.isoformat(),
            "sector_context": {
                "current_price": round(current_price, 4),
                "ma20": round(ma20, 4),
                "ma60": round(ma60, 4),
                "price_above_ma20": current_price > ma20,
                "ma20_above_ma60": ma20 > ma60,
                "drawdown_from_peak_pct": round(drawdown_pct, 2),
                "volume_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
            },
            "instruction": (
                "Assess the market regime for this sector (represented by the "
                "signal ETF). Use sector_context as the 'target-sector relative "
                "strength' input under 'Sector structure and style'. "
                "Output the standard template with Market state and "
                "Take-profit tightness."
            ),
        }

    @staticmethod
    def _parse_skill_output(
        data: Any,
        skill_versions: list[str],
    ) -> SectorRegime | None:
        """Parse the skill's text output into a SectorRegime.

        Returns None if the output is empty or completely unparseable.
        """
        text = data if isinstance(data, str) else str(data)
        if not text.strip():
            return None

        state = _parse_state(text)
        tightness = _parse_tightness(text)

        return SectorRegime(
            state=state,
            take_profit_tightness=tightness,
            reason=f"Skill 判定：market state={state}, take-profit tightness={tightness}",
            skill_versions=list(skill_versions),
            source="skill",
        )

    # ------------------------------------------------------------------
    # Fallback path (deterministic)
    # ------------------------------------------------------------------

    @staticmethod
    def _fallback_trend(
        symbol: str,
        signal_bars: list[SignalBar],
        as_of_index: int,
        config: BacktestConfig,
        skill_versions: list[str],
    ) -> SectorRegime:
        """Deterministic signal-ETF trend read (MA20/60 + drawdown depth).

        Never raises.  Used when the skill is unavailable.
        """
        bars = signal_bars[: as_of_index + 1]
        closes = [b.close for b in bars]
        if not closes:
            return SectorRegime(
                state="neutral",
                take_profit_tightness="normal",
                reason="无数据，默认 neutral",
                skill_versions=list(skill_versions),
                source="fallback_trend",
            )

        current_price = closes[-1]
        ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else current_price
        ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else ma20

        peak = max(closes)
        drawdown_pct = (peak - current_price) / peak * 100 if peak > 0 else 0.0

        if current_price > ma20 > ma60 and drawdown_pct < 10:
            return SectorRegime(
                state="bull",
                take_profit_tightness="loose",
                reason=(
                    f"Signal-ETF 趋势完好（price>MA20>MA60，回撤{drawdown_pct:.1f}%），"
                    f"fallback bull"
                ),
                skill_versions=list(skill_versions),
                source="fallback_trend",
            )
        if current_price < ma20 < ma60 or drawdown_pct > 20:
            return SectorRegime(
                state="bear",
                take_profit_tightness="tight",
                reason=(
                    f"Signal-ETF 趋势破位（price<MA20<MA60 或回撤{drawdown_pct:.1f}%），"
                    f"fallback bear"
                ),
                skill_versions=list(skill_versions),
                source="fallback_trend",
            )
        return SectorRegime(
            state="neutral",
            take_profit_tightness="normal",
            reason=(
                f"Signal-ETF 趋势不明（price={current_price:.2f}, "
                f"MA20={ma20:.2f}, MA60={ma60:.2f}, 回撤{drawdown_pct:.1f}%），"
                f"fallback neutral"
            ),
            skill_versions=list(skill_versions),
            source="fallback_trend",
        )


# ── output parsing helpers ──────────────────────────────────────────────────


def _parse_state(text: str) -> RegimeState:
    """Extract regime state from skill output text."""
    lower = text.lower()
    # Check bull first (avoid matching "bear" inside other words)
    if "bull" in lower or "strong trend" in lower:
        return "bull"
    if "bear" in lower or "weak market" in lower or "systemic" in lower:
        return "bear"
    # Consolidation / range-bound -> neutral
    return "neutral"


def _parse_tightness(text: str) -> RegimeTightness:
    """Extract take-profit tightness from skill output text."""
    lower = text.lower()
    if "loose" in lower or "let profits run" in lower:
        return "loose"
    if "tight" in lower:
        return "tight"
    # "neutral", "swing", "take profit in batches" -> normal
    return "normal"
