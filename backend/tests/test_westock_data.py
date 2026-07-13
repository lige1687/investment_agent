from datetime import date

import pytest

from app.backtest.westock_data import WestockDataClient, parse_kline_markdown


def test_parse_kline_markdown_converts_westock_table_to_signal_bars():
    markdown = """
| date | open | last | high | low | volume | amount | exchange |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-06-30 | 4.95 | 5.02 | 5.02 | 4.94 | 20297213 | 10142732805 | 10.18 |
| 2026-06-29 | 4.90 | 4.96 | 4.97 | 4.87 | 14848057 | 7294620000 | 7.14 |
"""

    bars = parse_kline_markdown(markdown)

    assert len(bars) == 2
    assert bars[0].date == date(2026, 6, 29)
    assert bars[0].close == 4.96
    assert bars[0].volume == 14848057
    assert bars[1].date == date(2026, 6, 30)
    assert bars[1].amount == 10142732805


def test_parse_kline_markdown_rejects_error_json_output():
    with pytest.raises(ValueError, match="westock-data returned an error"):
        parse_kline_markdown('{"success": false, "error": {"message": "bad symbol"}}')


@pytest.mark.asyncio
async def test_westock_client_invokes_npx_kline_command_with_expected_arguments():
    calls = []

    async def fake_runner(args, timeout):
        calls.append((args, timeout))
        return """
| date | open | last | high | low | volume | amount | exchange |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-06-30 | 4.95 | 5.02 | 5.02 | 4.94 | 20297213 | 10142732805 | 10.18 |
"""

    client = WestockDataClient(runner=fake_runner)

    bars = await client.fetch_kline("sh510300", period="day", limit=5)

    assert len(bars) == 1
    args, timeout = calls[0]
    assert args == [
        "npx",
        "-y",
        "westock-data-skillhub@1.0.3",
        "kline",
        "sh510300",
        "--period",
        "day",
        "--limit",
        "5",
    ]
    assert timeout == 30
