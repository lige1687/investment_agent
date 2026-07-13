import pytest

from app.tasks import anomaly_detection
from app.tasks.scheduler import setup_scheduler, scheduler


@pytest.mark.asyncio
async def test_scheduler_does_not_register_intraday_fund_pnl_anomaly_job():
    if scheduler.running:
        scheduler.shutdown(wait=False)
    scheduler.remove_all_jobs()

    setup_scheduler()

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert "anomaly_scan" not in job_ids

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_scan_and_alert_skips_fund_unrealized_pnl_alerts(monkeypatch):
    sent = []

    class FakeBot:
        configured = True

        async def send_alert(self, *args, **kwargs):
            sent.append((args, kwargs))
            return True

    monkeypatch.setattr(anomaly_detection, "is_trading_day", lambda: True)
    monkeypatch.setattr(anomaly_detection, "is_market_hours", lambda: True)
    monkeypatch.setattr(anomaly_detection, "feishu_bot", FakeBot())

    result = await anomaly_detection.scan_and_alert()

    assert result == {"ok": True, "skipped": True, "reason": "fund_intraday_pnl_alerts_disabled"}
    assert sent == []
