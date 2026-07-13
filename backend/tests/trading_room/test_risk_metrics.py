"""Deterministic account, holding, and theme risk metrics."""

import pytest


@pytest.mark.parametrize(
    ("equity", "expected_state", "buy_allowed"),
    [
        (95_000, "RISK_REVIEW", False),
        (92_500, "REDUCE_OR_EXIT_CANDIDATE", False),
        (90_000, "REDUCE_OR_EXIT_CANDIDATE", False),
    ],
)
def test_account_drawdown_boundaries(equity, expected_state, buy_allowed):
    from app.trading_room.risk_metrics import PortfolioRiskInput, RiskMetricsEngine

    result = RiskMetricsEngine.compute(
        PortfolioRiskInput(equity=equity, peak_equity=100_000, cash=30_000, positions=[])
    )

    assert result.account_drawdown_pct == pytest.approx((100_000 - equity) / 1000)
    assert result.state.value == expected_state
    assert result.new_buy_allowed is buy_allowed


def test_logic_failure_and_effective_trend_break_outrank_percentage_stop():
    from app.trading_room.risk_metrics import PositionRiskInput, PortfolioRiskInput, RiskMetricsEngine

    result = RiskMetricsEngine.compute(
        PortfolioRiskInput(
            equity=100_000,
            peak_equity=100_000,
            cash=50_000,
            positions=[
                PositionRiskInput(
                    fund_code="001513",
                    market_value=20_000,
                    cost_basis=22_000,
                    peak_market_value=24_000,
                    theme_weights={"communication": 0.7},
                    logic_failed=True,
                    effective_trend_break=True,
                    percentage_stop_triggered=False,
                )
            ],
        )
    )

    holding = result.holdings[0]
    assert holding.state.value == "REDUCE_OR_EXIT_CANDIDATE"
    assert holding.dominant_trigger == "logic_failure"
    assert holding.return_pct == pytest.approx(-9.0909, rel=1e-3)
    assert holding.drawdown_from_peak_pct == pytest.approx(16.6667, rel=1e-3)


def test_theme_exposure_and_optional_single_symbol_loss_width():
    from app.trading_room.risk_metrics import PositionRiskInput, PortfolioRiskInput, RiskMetricsEngine

    result = RiskMetricsEngine.compute(
        PortfolioRiskInput(
            equity=100_000,
            peak_equity=100_000,
            cash=40_000,
            positions=[
                PositionRiskInput(
                    fund_code="001513",
                    market_value=30_000,
                    cost_basis=25_000,
                    peak_market_value=32_000,
                    theme_weights={"communication": 0.6, "software": 0.4},
                    configured_loss_width_pct=0.10,
                    volatility=0.25,
                ),
                PositionRiskInput(
                    fund_code="161125",
                    market_value=20_000,
                    cost_basis=18_000,
                    peak_market_value=21_000,
                    theme_weights={"nasdaq": 1.0},
                ),
            ],
        )
    )

    by_code = {item.fund_code: item for item in result.holdings}
    assert result.theme_exposure_pct["communication"] == pytest.approx(0.18)
    assert result.theme_exposure_pct["nasdaq"] == pytest.approx(0.20)
    assert by_code["001513"].single_symbol_account_risk_pct == pytest.approx(0.03)
    assert by_code["161125"].single_symbol_account_risk_pct is None

