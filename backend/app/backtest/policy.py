"""Personal trading-system policy checks for backtests."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.backtest.indicators import moving_average, volume_ratio
from app.backtest.models import BacktestConfig, PortfolioSnapshot, SignalBar

SignalLevel = Literal["observe", "weak_buy", "middle_buy", "strong_buy", "risk_blocked"]


@dataclass(frozen=True)
class DimensionCheck:
    name: str
    passed: bool
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BuySignalChecklist:
    signal_level: SignalLevel
    recommended_action: str
    passed_count: int
    account_allowed: bool
    account_reasons: list[str]
    dimensions: list[DimensionCheck]

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_level": self.signal_level,
            "recommended_action": self.recommended_action,
            "passed_count": self.passed_count,
            "account_allowed": self.account_allowed,
            "account_reasons": self.account_reasons,
            "dimensions": [asdict(item) for item in self.dimensions],
        }


class TradingSystemPolicy:
    """Deterministic version of the user's personal trading discipline."""

    def __init__(self, config: BacktestConfig):
        self.config = config

    def evaluate_buy(
        self,
        index: int,
        bars: list[SignalBar],
        snapshot: PortfolioSnapshot,
    ) -> BuySignalChecklist:
        dimensions = [
            self._trend_repair(index, bars),
            self._healthy_volume(index, bars),
            self._funds_return(index, bars),
            self._logic_catalyst(),
            self._portfolio_allowed(snapshot),
        ]
        passed_count = sum(1 for item in dimensions if item.passed)
        account_allowed, account_reasons = self._account_allowed(snapshot)
        if not account_allowed:
            return BuySignalChecklist(
                signal_level="risk_blocked",
                recommended_action="禁止买入/禁止加仓",
                passed_count=passed_count,
                account_allowed=False,
                account_reasons=account_reasons,
                dimensions=dimensions,
            )

        signal_level: SignalLevel
        recommended_action: str
        if passed_count <= 2:
            signal_level = "observe"
            recommended_action = "观察"
        elif passed_count == 3:
            signal_level = "weak_buy"
            recommended_action = "小仓试错"
        elif passed_count == 4:
            signal_level = "middle_buy"
            recommended_action = "按计划建仓/补仓"
        else:
            signal_level = "strong_buy"
            recommended_action = "按计划建仓/补仓"

        return BuySignalChecklist(
            signal_level=signal_level,
            recommended_action=recommended_action,
            passed_count=passed_count,
            account_allowed=True,
            account_reasons=account_reasons,
            dimensions=dimensions,
        )

    def _trend_repair(self, index: int, bars: list[SignalBar]) -> DimensionCheck:
        closes = [bar.close for bar in bars[: index + 1]]
        ma_values = moving_average(closes, self.config.buy_ma_window)
        recent = bars[max(0, index - 2): index + 1]
        recent_lows = [bar.low for bar in recent]
        previous_lows = [bar.low for bar in bars[max(0, index - 5): max(0, index - 2)]]
        not_new_low = bool(previous_lows) and min(recent_lows) >= min(previous_lows)
        stood_above = self._stood_above_ma(index, closes, ma_values)
        short_breakout = len(closes) >= 3 and closes[index] > max(closes[max(0, index - 2): index])
        passed_conditions = [not_new_low, stood_above, short_breakout]
        passed = sum(1 for item in passed_conditions if item) >= 2
        return DimensionCheck(
            name="趋势修复",
            passed=passed,
            reason="满足至少2项趋势修复条件" if passed else "趋势修复不足，仍偏观察",
            details={
                "three_days_not_new_low": not_new_low,
                "stood_above_ma": stood_above,
                "short_breakout": short_breakout,
            },
        )

    def _healthy_volume(self, index: int, bars: list[SignalBar]) -> DimensionCheck:
        volumes = [bar.volume for bar in bars[: index + 1]]
        ratios = volume_ratio(volumes, self.config.buy_volume_window)
        current_ratio = ratios[index]
        recent = bars[max(0, index - 2): index + 1]
        gently_expanding = current_ratio is not None and self.config.buy_volume_ratio <= current_ratio <= 2.5
        no_heavy_selloff = all(bar.close >= bar.open or bar.volume <= volumes[index] for bar in recent)
        passed = gently_expanding and no_heavy_selloff
        return DimensionCheck(
            name="量能健康",
            passed=passed,
            reason="缩量企稳后温和放量" if passed else "量能结构未形成健康闭环",
            details={"volume_ratio": current_ratio, "no_heavy_selloff": no_heavy_selloff},
        )

    def _funds_return(self, index: int, bars: list[SignalBar]) -> DimensionCheck:
        if index < 5:
            return DimensionCheck(name="资金回流", passed=False, reason="历史数据不足以判断连续资金回流")
        amounts = [bar.amount if bar.amount is not None else bar.close * bar.volume for bar in bars]
        recent_avg = sum(amounts[index - 2: index + 1]) / 3
        prior_avg = sum(amounts[index - 5: index - 2]) / 3
        close_strength = bars[index].close > bars[index - 1].close > bars[index - 2].close
        passed = recent_avg > prior_avg and close_strength
        return DimensionCheck(
            name="资金回流",
            passed=passed,
            reason="成交额连续改善且价格同步转强" if passed else "资金回流连续性不足",
            details={"recent_amount_avg": recent_avg, "prior_amount_avg": prior_avg},
        )

    def _logic_catalyst(self) -> DimensionCheck:
        passed = (
            self.config.prosperity.score >= self.config.prosperity.min_score_to_buy
            and bool(self.config.prosperity.reasons)
        )
        return DimensionCheck(
            name="逻辑/催化验证",
            passed=passed,
            reason="景气度与催化描述通过" if passed else "缺少景气度或新增催化验证",
            details={
                "prosperity_score": self.config.prosperity.score,
                "min_score_to_buy": self.config.prosperity.min_score_to_buy,
                "reasons": self.config.prosperity.reasons,
            },
        )

    def _portfolio_allowed(self, snapshot: PortfolioSnapshot) -> DimensionCheck:
        next_position = min(self.config.target_position_pct, self.config.max_single_position_pct)
        total_after_buy = max(snapshot.position_pct, next_position)
        correlated_after_buy = self.config.current_correlated_growth_exposure_pct + max(
            next_position - snapshot.position_pct,
            0.0,
        )
        passed = (
            total_after_buy <= self.config.max_account_position_pct
            and next_position <= self.config.max_single_position_pct
            and correlated_after_buy <= self.config.max_correlated_growth_exposure_pct
        )
        return DimensionCheck(
            name="组合允许",
            passed=passed,
            reason="仓位、单标的和高相关暴露均未越线" if passed else "组合仓位或高相关暴露越线",
            details={
                "current_position_pct": snapshot.position_pct,
                "target_position_pct": self.config.target_position_pct,
                "max_account_position_pct": self.config.max_account_position_pct,
                "max_single_position_pct": self.config.max_single_position_pct,
                "correlated_after_buy": correlated_after_buy,
            },
        )

    def _account_allowed(self, snapshot: PortfolioSnapshot) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        position_room = self.config.max_account_position_pct - snapshot.position_pct
        if position_room <= 0:
            reasons.append("总仓位已达到90%上限，必须保留10%现金")
        account_drawdown = snapshot.peak_return_pct - snapshot.cumulative_return_pct
        if account_drawdown >= self.config.account_drawdown_redline_pct:
            reasons.append("账户回撤红线触发，禁止新增风险")
        if snapshot.position_pct >= self.config.max_single_position_pct:
            reasons.append("单只标的仓位已达到上限")
        return (not reasons, reasons or ["账户风控允许"])

    def _stood_above_ma(self, index: int, closes: list[float], ma_values: list[float | None]) -> bool:
        start = index - self.config.buy_stand_days + 1
        if start < 0:
            return False
        return all(
            ma_values[i] is not None and closes[i] > ma_values[i]
            for i in range(start, index + 1)
        )

