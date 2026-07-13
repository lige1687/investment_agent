"""Deterministic theme exposure and style-drift confidence engine."""

from datetime import date
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from app.trading_room.schemas import DataConfidence


class ReportedExposure(BaseModel):
    model_config = ConfigDict(frozen=True)

    fund_code: str
    report_period_end: date | None
    published_at: date | None
    theme_weights: dict[str, float]


class StyleInference(BaseModel):
    model_config = ConfigDict(frozen=True)

    window_end: date
    window_days: int
    betas: dict[str, float]
    r_squared: float = Field(ge=0, le=1)
    dominant_theme: str


class FundExposureSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    fund_code: str
    as_of: date
    method: Literal["index_tracked", "reported_plus_inferred"]
    theme_weights: dict[str, float]
    confidence: DataConfidence
    can_support_immediate_action: bool
    reasons: tuple[str, ...] = ()
    reported: ReportedExposure | None = None
    inferred: StyleInference | None = None
    tracked_index: str | None = None


class ExposureEngine:
    """Combines public reports with 60-day NAV style inference."""

    @staticmethod
    def index_tracked(
        *,
        fund_code: str,
        tracked_index: str,
        theme_weights: dict[str, float],
        as_of: date,
    ) -> FundExposureSnapshot:
        return FundExposureSnapshot(
            fund_code=fund_code,
            as_of=as_of,
            method="index_tracked",
            theme_weights=theme_weights,
            confidence=DataConfidence.HIGH,
            can_support_immediate_action=True,
            tracked_index=tracked_index,
            reasons=("tracked_index",),
        )

    @staticmethod
    def assess_active(
        *,
        reported: ReportedExposure,
        inferred: StyleInference | None,
        as_of: date,
    ) -> FundExposureSnapshot:
        reasons: list[str] = []
        confidence = DataConfidence.LOW

        if reported.report_period_end is None:
            reasons.append("report_period_end")
        elif inferred is None:
            reasons.append("missing_style_inference")
        else:
            report_age = (as_of - reported.report_period_end).days
            reported_dominant = max(
                reported.theme_weights,
                key=reported.theme_weights.get,
                default="",
            )
            inferred_weight = reported.theme_weights.get(inferred.dominant_theme, 0.0)
            full_agreement = reported_dominant == inferred.dominant_theme
            partial_agreement = inferred_weight >= 0.15
            drift_conflict = not full_agreement and not partial_agreement

            if report_age < 0:
                reasons.append("future_report_period")
            elif drift_conflict:
                reasons.append("drift_conflict")
            elif inferred.r_squared < 0.70:
                reasons.append("low_r_squared")
            elif report_age <= 60 and inferred.r_squared >= 0.80 and full_agreement:
                confidence = DataConfidence.HIGH
                reasons.append("reported_and_inferred_agree")
            elif report_age <= 120 and (full_agreement or partial_agreement):
                confidence = DataConfidence.MEDIUM
                reasons.append("reported_and_inferred_partly_agree")
            else:
                reasons.append("stale_report_period")

        combined = dict(reported.theme_weights)
        if inferred is not None and inferred.dominant_theme not in combined:
            combined[inferred.dominant_theme] = max(
                0.0,
                inferred.betas.get(inferred.dominant_theme, 0.0),
            )

        return FundExposureSnapshot(
            fund_code=reported.fund_code,
            as_of=as_of,
            method="reported_plus_inferred",
            theme_weights=combined,
            confidence=confidence,
            can_support_immediate_action=confidence in {
                DataConfidence.HIGH,
                DataConfidence.MEDIUM,
            },
            reasons=tuple(reasons),
            reported=reported,
            inferred=inferred,
        )

    @staticmethod
    def infer_style(
        *,
        fund_returns: list[float],
        theme_returns: dict[str, list[float]],
        window_end: date,
    ) -> StyleInference:
        window = 60
        if len(fund_returns) < window or not theme_returns:
            raise ValueError("60 observations and at least one theme are required")
        if any(len(values) < window for values in theme_returns.values()):
            raise ValueError("every theme needs 60 observations")

        names = list(theme_returns)
        y = np.asarray(fund_returns[-window:], dtype=float)
        factors = np.column_stack(
            [np.asarray(theme_returns[name][-window:], dtype=float) for name in names]
        )
        if not np.isfinite(y).all() or not np.isfinite(factors).all():
            raise ValueError("returns must be finite")

        design = np.column_stack([np.ones(window), factors])
        coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
        fitted = design @ coefficients
        residual_sum = float(np.square(y - fitted).sum())
        total_sum = float(np.square(y - y.mean()).sum())
        r_squared = 1.0 if total_sum == 0 and residual_sum == 0 else 1 - residual_sum / total_sum
        r_squared = min(1.0, max(0.0, r_squared))
        betas = {name: float(coefficients[index + 1]) for index, name in enumerate(names)}
        dominant = max(betas, key=betas.get)
        return StyleInference(
            window_end=window_end,
            window_days=window,
            betas=betas,
            r_squared=r_squared,
            dominant_theme=dominant,
        )

    @staticmethod
    def aggregate_reported_holdings(rows: list[dict]) -> dict[str, float]:
        """Deduplicate provider rows by security before theme aggregation."""

        securities: dict[str, tuple[str, float]] = {}
        for row in rows:
            code = str(row.get("security_code") or "").strip()
            theme = str(row.get("theme") or "").strip()
            try:
                weight = float(row.get("weight"))
            except (TypeError, ValueError):
                continue
            if not code or not theme or not np.isfinite(weight) or weight < 0:
                continue
            current = securities.get(code)
            if current is None or weight > current[1]:
                securities[code] = (theme, weight)

        totals: dict[str, float] = {}
        for theme, weight in securities.values():
            totals[theme] = totals.get(theme, 0.0) + weight
        return totals

