"""Dynamic theme-exposure confidence tests."""

from datetime import date, timedelta


def test_index_fund_uses_tracked_index_with_high_confidence():
    from app.trading_room.exposure import ExposureEngine
    from app.trading_room.schemas import DataConfidence

    snapshot = ExposureEngine.index_tracked(
        fund_code="161125",
        tracked_index="NASDAQ-100",
        theme_weights={"nasdaq": 1.0},
        as_of=date(2026, 7, 13),
    )

    assert snapshot.method == "index_tracked"
    assert snapshot.confidence is DataConfidence.HIGH
    assert snapshot.can_support_immediate_action is True


def test_missing_public_report_period_is_low_confidence_even_with_current_nav():
    from app.trading_room.exposure import ExposureEngine, ReportedExposure, StyleInference
    from app.trading_room.schemas import DataConfidence

    reported = ReportedExposure(
        fund_code="001513",
        report_period_end=None,
        published_at=date(2026, 7, 1),
        theme_weights={"communication": 0.55},
    )
    inferred = StyleInference(
        window_end=date(2026, 7, 13),
        window_days=60,
        betas={"communication": 0.9},
        r_squared=0.9,
        dominant_theme="communication",
    )

    snapshot = ExposureEngine.assess_active(
        reported=reported,
        inferred=inferred,
        as_of=date(2026, 7, 13),
    )

    assert snapshot.confidence is DataConfidence.LOW
    assert snapshot.can_support_immediate_action is False
    assert "report_period_end" in snapshot.reasons


def test_active_exposure_confidence_thresholds_and_drift_conflict():
    from app.trading_room.exposure import ExposureEngine, ReportedExposure, StyleInference
    from app.trading_room.schemas import DataConfidence

    as_of = date(2026, 7, 13)
    inference = StyleInference(
        window_end=as_of,
        window_days=60,
        betas={"communication": 0.8, "nasdaq": 0.1},
        r_squared=0.82,
        dominant_theme="communication",
    )
    high = ExposureEngine.assess_active(
        reported=ReportedExposure(
            fund_code="001513",
            report_period_end=as_of - timedelta(days=45),
            published_at=as_of - timedelta(days=20),
            theme_weights={"communication": 0.55, "software": 0.20},
        ),
        inferred=inference,
        as_of=as_of,
    )
    medium = ExposureEngine.assess_active(
        reported=ReportedExposure(
            fund_code="001513",
            report_period_end=as_of - timedelta(days=90),
            published_at=as_of - timedelta(days=50),
            theme_weights={"communication": 0.20, "software": 0.45},
        ),
        inferred=StyleInference(**{**inference.model_dump(), "r_squared": 0.72}),
        as_of=as_of,
    )
    conflict = ExposureEngine.assess_active(
        reported=ReportedExposure(
            fund_code="001513",
            report_period_end=as_of - timedelta(days=30),
            published_at=as_of - timedelta(days=10),
            theme_weights={"consumer": 0.65},
        ),
        inferred=inference,
        as_of=as_of,
    )

    assert high.confidence is DataConfidence.HIGH
    assert medium.confidence is DataConfidence.MEDIUM
    assert conflict.confidence is DataConfidence.LOW
    assert "drift_conflict" in conflict.reasons


def test_rolling_regression_uses_60_observations_and_finds_dominant_theme():
    from app.trading_room.exposure import ExposureEngine

    communication = [((index % 11) - 5) / 100 for index in range(60)]
    nasdaq = [((index % 7) - 3) / 120 for index in range(60)]
    fund = [0.8 * communication[i] + 0.2 * nasdaq[i] for i in range(60)]

    result = ExposureEngine.infer_style(
        fund_returns=fund,
        theme_returns={"communication": communication, "nasdaq": nasdaq},
        window_end=date(2026, 7, 13),
    )

    assert result.window_days == 60
    assert result.dominant_theme == "communication"
    assert result.r_squared > 0.99
    assert result.betas["communication"] > result.betas["nasdaq"]


def test_duplicate_holdings_are_normalized_before_theme_aggregation():
    from app.trading_room.exposure import ExposureEngine

    result = ExposureEngine.aggregate_reported_holdings(
        [
            {"security_code": "000063", "theme": "communication", "weight": 0.08},
            {"security_code": "000063", "theme": "communication", "weight": 0.08},
            {"security_code": "300308", "theme": "communication", "weight": 0.06},
        ]
    )

    assert result == {"communication": 0.14}

