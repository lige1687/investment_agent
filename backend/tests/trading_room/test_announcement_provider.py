"""Iwencai announcement search normalization for live execution preflight."""

from datetime import date, datetime, timezone

from app.trading_room.announcement_provider import normalize_announcement_results
from app.trading_room.execution_preflight import ExecutionPreflight
from app.trading_room.schemas import TradeAvailability


RAW = {
    "status_code": 0,
    "data": [
        {
            "uid": "institutional-resume",
            "title": "易方达信息产业混合恢复机构客户大额申购业务的公告",
            "url": "https://example.test/institutional-resume.pdf",
            "publish_date": "2026-03-09 00:00:00",
            "stock_infos": [{"code": "001513"}, {"code": "019018"}],
            "source_original": "基金主代码 | 001513 | 自2026年3月10日起恢复办理机构客户大额申购业务。",
        },
        {
            "uid": "all-limit",
            "title": "易方达信息产业混合调整大额申购业务限制的公告",
            "url": "https://example.test/all-limit.pdf",
            "publish_date": "2026-06-25 00:00:00",
            "stock_infos": [{"code": "001513"}, {"code": "019018"}],
            "source_original": (
                "基金主代码 | 001513 | 自2026年6月25日起调整A类基金份额和C类基金份额"
                "的大额申购限制，单日单个基金账户申购金额不超过1万元（含）。"
                "本基金恢复大额申购业务的具体时间将另行公告。"
            ),
        },
        {
            "uid": "wrong-fund",
            "title": "另一只基金暂停申购",
            "url": "https://example.test/wrong.pdf",
            "publish_date": "2026-07-01 00:00:00",
            "stock_infos": [{"code": "999999"}],
            "source_original": "暂停申购",
        },
    ],
}


def test_normalizer_restores_exact_fund_share_scope_date_and_limit():
    records = normalize_announcement_results(
        RAW,
        fund_code="001513",
        share_class="A",
    )

    assert len(records) == 2
    limited = next(item for item in records if item["action"] == "LIMITED")
    assert limited["purchase_limit"] == 10_000
    assert limited["effective_date"] == "2026-06-25"
    assert limited["share_classes"] == ["A", "C"]
    assert limited["customer_scope"] == "all"
    assert limited["url"].endswith("all-limit.pdf")


def test_normalized_records_feed_current_state_restoration_without_institutional_noise():
    records = normalize_announcement_results(RAW, fund_code="001513", share_class="A")
    snapshot = ExecutionPreflight.restore(
        records=records,
        fund_code="001513",
        share_class="A",
        customer_scope="retail",
        as_of=date(2026, 7, 13),
        queried_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
        channel_confirmed=False,
    )

    assert snapshot.manager_status is TradeAvailability.LIMITED
    assert snapshot.daily_purchase_limit == 10_000
    assert snapshot.announcement_url.endswith("all-limit.pdf")
    assert snapshot.maximum_action_class.value == "CONDITIONAL"


def test_full_subscription_pause_is_not_misread_as_large_purchase_limit():
    raw = {
        "status_code": 0,
        "data": [{
            "uid": "pause",
            "title": "某基金暂停申购、赎回业务的公告",
            "url": "https://example.test/pause.pdf",
            "publish_date": "2026-07-12 00:00:00",
            "stock_infos": [{"code": "001513"}],
            "source_original": "自2026年7月13日起暂停申购、赎回业务。",
        }],
    }
    records = normalize_announcement_results(raw, fund_code="001513", share_class="A")
    assert records[0]["action"] == "SUSPENDED"
    assert records[0]["purchase_limit"] is None
