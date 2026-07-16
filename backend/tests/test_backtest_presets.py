from datetime import date

from fastapi.testclient import TestClient

from app.api.v1 import backtest as backtest_api
from app.backtest.presets import get_backtest_preset, list_backtest_presets
from app.main import app


def test_list_backtest_presets_includes_yifangda_info_industry_mapping():
    presets = list_backtest_presets()

    preset_ids = {preset.preset_id for preset in presets}
    assert "yifangda_info_industry_communication" in preset_ids

    preset = get_backtest_preset("yifangda_info_industry_communication")
    assert preset.fund_code == "001513"
    assert preset.signal_provider == "westock"
    assert preset.signal_period == "day"
    assert preset.config.prosperity.score >= 7
    assert "景气度" in " ".join(preset.config.prosperity.reasons)


def test_get_backtest_presets_api_returns_minimal_mapping_fields():
    client = TestClient(app)

    response = client.get("/api/v1/backtest/presets")

    assert response.status_code == 200
    data = response.json()
    first = data["presets"][0]
    assert {"preset_id", "fund_code", "fund_name", "signal_symbol", "signal_name"} <= set(first)


def test_run_preset_api_uses_preset_data_sources(monkeypatch):
    """Preset config uses default expma_window=15, buy_volume_window=20.

    Data: 20 flat bars (close=10, vol=100) -> index 20 crossover (close=12,
    vol=150, volume_ratio=1.5>=1.2) -> T+1/T+2 stay at 12 (confirmed) ->
    T+3 execution at index 23 (2026-01-24).
    """
    class FakeFundNavClient:
        async def fetch_nav(self, fund_code, start_date=None, end_date=None, page_size=10000, timeout=15):
            assert fund_code == "001513"
            assert page_size == 100
            return [
                backtest_api.FundNavPoint(date=date(2026, 1, day), nav=1.0)
                for day in range(1, 26)
            ]

    class FakeWestockClient:
        async def fetch_kline(self, symbol, period="day", limit=200, timeout=30):
            assert period == "day"
            bars = []
            # 20 flat bars: EXPMA converges to 10.0, volume_ratio computable
            # from index 20 onward (buy_volume_window=20).
            for day in range(1, 21):
                bars.append(backtest_api.SignalBar(
                    date=date(2026, 1, day),
                    open=10, high=10.2, low=9.8, close=10.0,
                    volume=100, amount=1000,
                ))
            # index 20 (day 21): volume breakout above EXPMA -> buy trigger
            bars.append(backtest_api.SignalBar(
                date=date(2026, 1, 21),
                open=10, high=12.2, low=9.8, close=12.0,
                volume=150, amount=1800,
            ))
            # T+1/T+2/T+3/T+4: stay above EXPMA (observation confirmed)
            for day in range(22, 26):
                bars.append(backtest_api.SignalBar(
                    date=date(2026, 1, day),
                    open=12, high=12.2, low=11.8, close=12.0,
                    volume=100, amount=1200,
                ))
            return bars

    monkeypatch.setattr(backtest_api, "EastmoneyFundNavClient", lambda: FakeFundNavClient())
    monkeypatch.setattr(backtest_api, "WestockDataClient", lambda: FakeWestockClient())
    client = TestClient(app)

    response = client.post(
        "/api/v1/backtest/run-preset",
        json={
            "preset_id": "yifangda_info_industry_communication",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "initial_cash": 100000,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["config"]["fund_code"] == "001513"
    assert data["metrics"]["trade_count"] >= 1
    # buy_confirmation event is emitted after the 2-day observation window
    assert any(e["event_type"] == "buy_confirmation" for e in data["events"])
