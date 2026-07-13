"""Deterministic portfolio and holding risk calculations."""

from pydantic import BaseModel, ConfigDict, Field

from app.trading_room.schemas import RiskState


class PositionRiskInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    fund_code: str
    market_value: float = Field(ge=0)
    cost_basis: float = Field(ge=0)
    peak_market_value: float = Field(ge=0)
    theme_weights: dict[str, float] = {}
    volatility: float | None = Field(default=None, ge=0)
    configured_loss_width_pct: float | None = Field(default=None, gt=0, le=1)
    logic_failed: bool = False
    effective_trend_break: bool = False
    percentage_stop_triggered: bool = False


class PortfolioRiskInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    equity: float = Field(gt=0)
    peak_equity: float = Field(gt=0)
    cash: float = Field(ge=0)
    positions: list[PositionRiskInput]


class HoldingRiskMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    fund_code: str
    allocation_pct: float
    return_pct: float | None
    drawdown_from_peak_pct: float | None
    volatility: float | None
    single_symbol_account_risk_pct: float | None
    state: RiskState
    dominant_trigger: str | None


class PortfolioRiskMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_drawdown_pct: float
    total_position_pct: float
    cash_pct: float
    theme_exposure_pct: dict[str, float]
    state: RiskState
    new_buy_allowed: bool
    holdings: tuple[HoldingRiskMetrics, ...]


class RiskMetricsEngine:
    @staticmethod
    def compute(inputs: PortfolioRiskInput) -> PortfolioRiskMetrics:
        account_drawdown = max(0.0, (inputs.peak_equity - inputs.equity) / inputs.peak_equity * 100)
        if account_drawdown >= 7.5:
            account_state = RiskState.REDUCE_OR_EXIT_CANDIDATE
        elif account_drawdown >= 5.0:
            account_state = RiskState.RISK_REVIEW
        else:
            account_state = RiskState.NORMAL

        total_position_value = sum(position.market_value for position in inputs.positions)
        total_position_pct = total_position_value / inputs.equity
        cash_pct = inputs.cash / inputs.equity
        theme_exposure: dict[str, float] = {}
        holdings: list[HoldingRiskMetrics] = []

        for position in inputs.positions:
            allocation = position.market_value / inputs.equity
            for theme, weight in position.theme_weights.items():
                if weight > 0:
                    theme_exposure[theme] = theme_exposure.get(theme, 0.0) + allocation * weight

            return_pct = (
                (position.market_value - position.cost_basis) / position.cost_basis * 100
                if position.cost_basis > 0
                else None
            )
            peak_drawdown = (
                max(0.0, (position.peak_market_value - position.market_value) / position.peak_market_value * 100)
                if position.peak_market_value > 0
                else None
            )
            if position.logic_failed:
                trigger = "logic_failure"
            elif position.effective_trend_break:
                trigger = "effective_trend_break"
            elif position.percentage_stop_triggered:
                trigger = "percentage_stop"
            else:
                trigger = None

            holding_state = (
                RiskState.REDUCE_OR_EXIT_CANDIDATE if trigger else RiskState.NORMAL
            )
            holdings.append(
                HoldingRiskMetrics(
                    fund_code=position.fund_code,
                    allocation_pct=allocation,
                    return_pct=return_pct,
                    drawdown_from_peak_pct=peak_drawdown,
                    volatility=position.volatility,
                    single_symbol_account_risk_pct=(
                        allocation * position.configured_loss_width_pct
                        if position.configured_loss_width_pct is not None
                        else None
                    ),
                    state=holding_state,
                    dominant_trigger=trigger,
                )
            )

        state = account_state
        if any(item.state is RiskState.REDUCE_OR_EXIT_CANDIDATE for item in holdings):
            state = RiskState.REDUCE_OR_EXIT_CANDIDATE
        return PortfolioRiskMetrics(
            account_drawdown_pct=account_drawdown,
            total_position_pct=total_position_pct,
            cash_pct=cash_pct,
            theme_exposure_pct=theme_exposure,
            state=state,
            new_buy_allowed=account_drawdown < 5.0,
            holdings=tuple(holdings),
        )

