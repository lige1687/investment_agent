from datetime import date

import pytest

from app.backtest.fees import FundFeeModel, RedemptionFeeTier
from app.backtest.indicators import expma, moving_average, volume_ratio
from app.backtest.models import FundNavPoint, SignalBar


def test_expma_uses_first_value_as_seed_and_smooths_subsequent_values():
    values = [10.0, 12.0, 14.0]

    result = expma(values, window=3)

    assert result == [10.0, 11.0, 12.5]


def test_moving_average_returns_none_until_window_is_available():
    values = [10.0, 12.0, 14.0, 16.0]

    result = moving_average(values, window=3)

    assert result == [None, None, 12.0, 14.0]


def test_volume_ratio_compares_current_volume_to_prior_window_average():
    volumes = [100.0, 100.0, 100.0, 180.0]

    result = volume_ratio(volumes, window=3)

    assert result == [None, None, None, 1.8]


def test_fund_fee_model_calculates_buy_shares_after_subscription_fee():
    model = FundFeeModel(subscription_fee_rate=0.0015)

    shares, fee = model.calculate_buy_shares(cash=10_000.0, nav=2.0)

    assert fee == pytest.approx(15.0)
    assert shares == pytest.approx(4_992.5)


def test_fund_fee_model_uses_matching_redemption_fee_tier():
    model = FundFeeModel(
        redemption_fee_tiers=[
            RedemptionFeeTier(max_holding_days=7, fee_rate=0.015),
            RedemptionFeeTier(max_holding_days=30, fee_rate=0.005),
            RedemptionFeeTier(max_holding_days=None, fee_rate=0.0),
        ]
    )

    cash, fee = model.calculate_sell_cash(shares=1_000.0, nav=2.0, holding_days=10)

    assert fee == pytest.approx(10.0)
    assert cash == pytest.approx(1_990.0)


def test_backtest_market_points_expose_datetime_free_daily_inputs():
    nav = FundNavPoint(date=date(2026, 1, 2), nav=1.234)
    bar = SignalBar(
        date=date(2026, 1, 2),
        open=10.0,
        high=11.0,
        low=9.8,
        close=10.8,
        volume=1_000_000,
        amount=10_800_000,
    )

    assert nav.nav == 1.234
    assert bar.close == 10.8
