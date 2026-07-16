from datetime import date

from fastapi.testclient import TestClient

from app.api.v1 import backtest as backtest_api
from app.main import app


def test_run_backtest_api_returns_metrics_trades_and_events():
    """New two-layer observation model: volume breakout above EXPMA -> 2-day
    observation -> confirmed -> T+3 fill.

    Data: 3 flat bars (close=10, vol=100) -> index 3 crossover (close=12,
    vol=150, volume_ratio=1.5>=1.2) -> T+1/T+2 stay at 12 (confirmed) ->
    T+3 execution at index 6 (2026-01-07).
    """
    client = TestClient(app)

    response = client.post(
        "/api/v1/backtest/run",
        json={
            "config": {
                "fund_code": "001513",
                "fund_name": "易方达信息产业混合A",
                "signal_code": "sh510300",
                "signal_name": "通信设备ETF",
                "initial_cash": 100000,
                "target_position_pct": 0.2,
                "expma_window": 3,
                "buy_volume_window": 3,
                "buy_volume_ratio": 1.2,
                "buy_stand_days": 2,
                "profit_drawdown_trigger_pct": 5,
                "prosperity": {
                    "score": 8,
                    "min_score_to_buy": 7,
                    "reasons": ["业绩预期改善"],
                },
            },
            "fund_nav": [
                {"date": "2026-01-01", "nav": 1.0},
                {"date": "2026-01-02", "nav": 1.0},
                {"date": "2026-01-03", "nav": 1.0},
                {"date": "2026-01-04", "nav": 1.0},
                {"date": "2026-01-05", "nav": 1.0},
                {"date": "2026-01-06", "nav": 1.0},
                {"date": "2026-01-07", "nav": 1.0},
            ],
            "signal_bars": [
                {"date": "2026-01-01", "open": 10, "high": 10.2, "low": 9.8, "close": 10.0, "volume": 100, "amount": 1000},
                {"date": "2026-01-02", "open": 10, "high": 10.2, "low": 9.8, "close": 10.0, "volume": 100, "amount": 1000},
                {"date": "2026-01-03", "open": 10, "high": 10.2, "low": 9.8, "close": 10.0, "volume": 100, "amount": 1000},
                {"date": "2026-01-04", "open": 10, "high": 12.2, "low": 9.8, "close": 12.0, "volume": 150, "amount": 1800},
                {"date": "2026-01-05", "open": 12, "high": 12.2, "low": 11.8, "close": 12.0, "volume": 100, "amount": 1200},
                {"date": "2026-01-06", "open": 12, "high": 12.2, "low": 11.8, "close": 12.0, "volume": 100, "amount": 1200},
                {"date": "2026-01-07", "open": 12, "high": 12.2, "low": 11.8, "close": 12.0, "volume": 100, "amount": 1200},
            ],
            "fee_model": {"subscription_fee_rate": 0.001},
            "strategy_text": "总仓位上限 90%，弱买点：只观察，首次建仓：只上计划资金的一半。",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["metrics"]["trade_count"] == 1
    assert data["trades"][0]["action"] == "buy"
    # 经过观察期确认后，返回 buy_confirmation 事件
    assert len(data["events"]) >= 1
    assert data["events"][0]["event_type"] == "buy_confirmation"
    assert data["signal_bars"][0]["date"] == "2026-01-01"
    assert data["signal_bars"][-1]["close"] == 12.0
    assert data["strategy_profile"]["source"] == "custom_text"
    assert "弱买点只观察" in data["strategy_profile"]["recognized_rules"]
    assert data["disclaimer"] == "过去表现不代表未来收益，本结果仅供参考，不构成投资建议"


def test_run_backtest_api_test_mode_returns_non_trade_system_checks():
    client = TestClient(app)
    payload = {
        "config": {
            "fund_code": "001513",
            "fund_name": "易方达信息产业混合A",
            "signal_code": "sh510300",
            "signal_name": "通信设备ETF",
            "initial_cash": 100000,
            "target_position_pct": 0,
            "buy_ma_window": 20,
            "buy_volume_window": 3,
            "buy_volume_ratio": 1.2,
            "buy_stand_days": 2,
            "prosperity": {"score": 0, "min_score_to_buy": 7, "reasons": []},
        },
        "fund_nav": [
            {"date": "2026-01-01", "nav": 1.0},
            {"date": "2026-01-02", "nav": 1.0},
            {"date": "2026-01-03", "nav": 1.0},
            {"date": "2026-01-04", "nav": 1.0},
            {"date": "2026-01-05", "nav": 1.0},
            {"date": "2026-01-06", "nav": 1.0},
            {"date": "2026-01-07", "nav": 1.0},
            {"date": "2026-01-08", "nav": 1.0},
            {"date": "2026-01-09", "nav": 1.0},
        ],
        "signal_bars": [
            {"date": "2026-01-01", "open": 10, "high": 10.2, "low": 9.8, "close": 10.0, "volume": 100, "amount": 1000},
            {"date": "2026-01-02", "open": 10, "high": 10.1, "low": 9.7, "close": 9.9, "volume": 100, "amount": 990},
            {"date": "2026-01-03", "open": 9.9, "high": 10.0, "low": 9.6, "close": 9.8, "volume": 100, "amount": 980},
            {"date": "2026-01-04", "open": 9.8, "high": 9.9, "low": 9.6, "close": 9.75, "volume": 70, "amount": 682},
            {"date": "2026-01-05", "open": 9.75, "high": 10.0, "low": 9.65, "close": 9.9, "volume": 65, "amount": 643},
            {"date": "2026-01-06", "open": 9.9, "high": 10.1, "low": 9.7, "close": 10.0, "volume": 60, "amount": 600},
            {"date": "2026-01-07", "open": 10.0, "high": 10.4, "low": 9.9, "close": 10.3, "volume": 140, "amount": 1442},
            {"date": "2026-01-08", "open": 10.3, "high": 10.5, "low": 10.1, "close": 10.4, "volume": 120, "amount": 1248},
            {"date": "2026-01-09", "open": 10.4, "high": 10.6, "low": 10.2, "close": 10.5, "volume": 110, "amount": 1155},
        ],
        "test_mode": True,
    }

    response = client.post("/api/v1/backtest/run", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["metrics"]["trade_count"] == 0
    system_checks = [event for event in data["events"] if event["event_type"] == "system_check"]
    assert system_checks
    assert system_checks[0]["decision"]["action"] == "observe"
    assert system_checks[0]["details"]["trigger_signals"]
    assert system_checks[0]["skill_route"]["system"] == "batch-trading"
    assert system_checks[0]["audit"]["final_decider"]


def test_run_backtest_api_hides_non_trade_system_checks_when_test_mode_is_off():
    client = TestClient(app)

    response = client.post(
        "/api/v1/backtest/run",
        json={
            "config": {
                "fund_code": "001513",
                "fund_name": "易方达信息产业混合A",
                "signal_code": "sh510300",
                "signal_name": "通信设备ETF",
                "initial_cash": 100000,
                "target_position_pct": 0.2,
                "prosperity": {"score": 0, "min_score_to_buy": 7, "reasons": []},
            },
            "fund_nav": [
                {"date": "2026-01-01", "nav": 1.0},
                {"date": "2026-01-02", "nav": 1.0},
                {"date": "2026-01-03", "nav": 1.0},
            ],
            "signal_bars": [
                {"date": "2026-01-01", "open": 10, "high": 10.2, "low": 9.8, "close": 10.0, "volume": 100, "amount": 1000},
                {"date": "2026-01-02", "open": 10, "high": 10.1, "low": 9.7, "close": 9.9, "volume": 100, "amount": 990},
                {"date": "2026-01-03", "open": 9.9, "high": 10.0, "low": 9.6, "close": 9.8, "volume": 100, "amount": 980},
            ],
            "test_mode": False,
        },
    )

    assert response.status_code == 200
    assert all(event["event_type"] != "system_check" for event in response.json()["events"])


def test_run_backtest_api_can_fetch_signal_bars_from_westock(monkeypatch):
    """Verify signal bars fetched from westock produce a buy under the
    two-layer observation model (volume breakout above EXPMA -> T+3 fill).
    """
    class FakeWestockClient:
        async def fetch_kline(self, symbol, period="day", limit=200, timeout=30):
            assert symbol == "sh510300"
            assert period == "day"
            assert limit == 7
            return [
                backtest_api.SignalBar(date=date(2026, 1, 1), open=10, high=10.2, low=9.8, close=10.0, volume=100, amount=1000),
                backtest_api.SignalBar(date=date(2026, 1, 2), open=10, high=10.2, low=9.8, close=10.0, volume=100, amount=1000),
                backtest_api.SignalBar(date=date(2026, 1, 3), open=10, high=10.2, low=9.8, close=10.0, volume=100, amount=1000),
                backtest_api.SignalBar(date=date(2026, 1, 4), open=10, high=12.2, low=9.8, close=12.0, volume=150, amount=1800),
                backtest_api.SignalBar(date=date(2026, 1, 5), open=12, high=12.2, low=11.8, close=12.0, volume=100, amount=1200),
                backtest_api.SignalBar(date=date(2026, 1, 6), open=12, high=12.2, low=11.8, close=12.0, volume=100, amount=1200),
                backtest_api.SignalBar(date=date(2026, 1, 7), open=12, high=12.2, low=11.8, close=12.0, volume=100, amount=1200),
            ]

    monkeypatch.setattr(backtest_api, "WestockDataClient", lambda: FakeWestockClient())
    client = TestClient(app)

    response = client.post(
        "/api/v1/backtest/run",
        json={
            "config": {
                "fund_code": "001513",
                "fund_name": "易方达信息产业混合A",
                "signal_code": "sh510300",
                "signal_name": "通信设备ETF",
                "initial_cash": 100000,
                "target_position_pct": 0.2,
                "expma_window": 3,
                "buy_volume_window": 3,
                "buy_volume_ratio": 1.2,
                "buy_stand_days": 2,
                "prosperity": {
                    "score": 8,
                    "min_score_to_buy": 7,
                    "reasons": ["业绩预期改善"],
                },
            },
            "fund_nav": [
                {"date": "2026-01-01", "nav": 1.0},
                {"date": "2026-01-02", "nav": 1.0},
                {"date": "2026-01-03", "nav": 1.0},
                {"date": "2026-01-04", "nav": 1.0},
                {"date": "2026-01-05", "nav": 1.0},
                {"date": "2026-01-06", "nav": 1.0},
                {"date": "2026-01-07", "nav": 1.0},
            ],
            "signal_data_source": {
                "provider": "westock",
                "symbol": "sh510300",
                "period": "day",
                "limit": 7,
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["metrics"]["trade_count"] == 1
    assert data["trades"][0]["action"] == "buy"


def test_run_backtest_api_can_fetch_fund_nav_and_align_with_signal_bars(monkeypatch):
    """Verify fund NAV fetched from eastmoney aligns with westock signal bars
    and produces a buy under the two-layer observation model.
    """
    class FakeFundNavClient:
        async def fetch_nav(self, fund_code, start_date=None, end_date=None, page_size=10000, timeout=15):
            assert fund_code == "001513"
            assert start_date == date(2026, 1, 1)
            assert end_date == date(2026, 1, 31)
            return [
                backtest_api.FundNavPoint(date=date(2026, 1, day), nav=1.0)
                for day in range(1, 8)
            ]

    class FakeWestockClient:
        async def fetch_kline(self, symbol, period="day", limit=200, timeout=30):
            return [
                backtest_api.SignalBar(date=date(2026, 1, 1), open=10, high=10.2, low=9.8, close=10.0, volume=100, amount=1000),
                backtest_api.SignalBar(date=date(2026, 1, 2), open=10, high=10.2, low=9.8, close=10.0, volume=100, amount=1000),
                backtest_api.SignalBar(date=date(2026, 1, 3), open=10, high=10.2, low=9.8, close=10.0, volume=100, amount=1000),
                backtest_api.SignalBar(date=date(2026, 1, 4), open=10, high=12.2, low=9.8, close=12.0, volume=150, amount=1800),
                backtest_api.SignalBar(date=date(2026, 1, 5), open=12, high=12.2, low=11.8, close=12.0, volume=100, amount=1200),
                backtest_api.SignalBar(date=date(2026, 1, 6), open=12, high=12.2, low=11.8, close=12.0, volume=100, amount=1200),
                backtest_api.SignalBar(date=date(2026, 1, 7), open=12, high=12.2, low=11.8, close=12.0, volume=100, amount=1200),
            ]

    monkeypatch.setattr(backtest_api, "EastmoneyFundNavClient", lambda: FakeFundNavClient())
    monkeypatch.setattr(backtest_api, "WestockDataClient", lambda: FakeWestockClient())
    client = TestClient(app)

    response = client.post(
        "/api/v1/backtest/run",
        json={
            "config": {
                "fund_code": "001513",
                "fund_name": "易方达信息产业混合A",
                "signal_code": "sh510300",
                "signal_name": "通信设备ETF",
                "initial_cash": 100000,
                "target_position_pct": 0.2,
                "expma_window": 3,
                "buy_volume_window": 3,
                "buy_volume_ratio": 1.2,
                "buy_stand_days": 2,
                "prosperity": {
                    "score": 8,
                    "min_score_to_buy": 7,
                    "reasons": ["业绩预期改善"],
                },
            },
            "fund_nav_data_source": {
                "provider": "eastmoney",
                "fund_code": "001513",
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
            },
            "signal_data_source": {
                "provider": "westock",
                "symbol": "sh510300",
                "period": "day",
                "limit": 7,
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["metrics"]["trade_count"] == 1
    assert data["equity_curve"][0]["date"] == "2026-01-01"
    assert data["equity_curve"][-1]["date"] == "2026-01-07"
