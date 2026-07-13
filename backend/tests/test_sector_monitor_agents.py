from app.services.sector_monitor_agents import (
    build_market_mood_snapshot,
    decide_sector_opportunities,
)


def test_market_mood_snapshot_uses_turnover_change_and_breadth():
    snapshot = build_market_mood_snapshot({
        "指数简称": "同花顺全A(沪深京)",
        "最新涨跌幅:前复权": 1.2355,
        "成交额[20260630]": 3_293_805_400_000.0,
        "成交额[20260629]": 3_539_325_200_000.0,
        "上涨家数[20260630]": 3051.0,
        "下跌家数[20260630]": 2364.0,
        "涨停家数[20260630]": 170.0,
        "跌停家数[20260630]": 20.0,
    })

    assert snapshot["state"] == "缩量修复"
    assert snapshot["turnover_change_pct"] == -6.94
    assert "全A成交额32938亿" in snapshot["summary"]
    assert "较昨日缩量6.94%" in snapshot["summary"]
    assert "上涨3051/下跌2364" in snapshot["summary"]
    assert "涨停170/跌停20" in snapshot["summary"]


def test_decision_agent_consumes_normalized_evidence_without_skill_calls():
    market = {
        "state": "缩量修复",
        "turnover_change_pct": -6.94,
        "summary": "缩量修复，科技线主导。",
    }
    rows = [
        {
            "name": "半导体/芯片",
            "matched_sector": "半导体",
            "source_code": "881121.TI",
            "change_pct_value": 6.32,
            "net_inflow": 24_893_604_000.0,
            "turnover": 622_472_580_000.0,
            "technical": "继续站上5/10日线，短线仍站稳",
            "holding": "财通集成电路产业股票C",
            "source_skill": "hithink-sector-selector",
        },
        {
            "name": "有色金属",
            "matched_sector": "有色金属",
            "source_code": "000819.SH",
            "change_pct_value": -0.70,
            "net_inflow": 0.0,
            "turnover": 105_632_662_000.0,
            "technical": "继续跌破5/10日线，趋势仍未修复",
            "holding": "南方有色金属ETF联接A",
            "source_skill": "hithink-industry-query",
        },
    ]

    decisions = decide_sector_opportunities(rows, market)

    assert decisions[0]["name"] == "半导体/芯片"
    assert decisions[0]["opportunity_level"] == "强机会"
    assert "主力净流入248.9亿" in decisions[0]["one_liner"]
    assert "缩量修复" in decisions[0]["one_liner"]
    assert decisions[0]["source_skill"] == "hithink-sector-selector"
    assert decisions[1]["name"] == "有色金属"
    assert decisions[1]["opportunity_level"] == "回避"
