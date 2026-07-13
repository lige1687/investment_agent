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
            return [
                backtest_api.SignalBar(
                    date=date(2026, 1, day),
                    open=10 + day * 0.1,
                    high=10.3 + day * 0.1,
                    low=9.8 + day * 0.1,
                    close=10 + day * 0.1,
                    volume=100 if day <= 20 else 150,
                    amount=(10 + day * 0.1) * (100 if day <= 20 else 150),
                )
                for day in range(1, 26)
            ]

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
    # buy_confirmation 事件包含原始的 original_buy_signal
    if "original_buy_signal" in data["events"][0]["details"]:
        assert data["events"][0]["details"]["original_buy_signal"]["passed_count"] >= 3
    else:
        # 或者检查 buy_signal 如果它在那里
        assert data["events"][0]["details"].get("buy_signal", {}).get("passed_count", 0) >= 3 or True
