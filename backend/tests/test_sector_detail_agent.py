import pytest

from app.services.agent_context_service import ContextSnapshot


@pytest.mark.asyncio
async def test_sector_detail_agent_explains_snapshot_evidence_without_pseudo_data():
    from app.agents.sector_detail_agent import SectorDetailAgent

    snapshot = ContextSnapshot(
        id=7,
        source="feishu_card",
        intent="sector_monitor",
        question="板块监控测试卡",
        context={
            "market_mood": {
                "state": "震荡观察",
                "summary": "震荡观察：全A成交额35393亿，较昨日放量0.00%。",
            },
            "sector_evidence": [
                {
                    "name": "半导体/芯片",
                    "matched_sector": "半导体材料设备",
                    "tracking_code": "931743",
                    "data_code": "931743",
                    "change_pct": 2.69,
                    "turnover": 172_724_725_464.0,
                    "main_flow": None,
                    "opportunity_level": "观察",
                    "opportunity": "观察：半导体材料设备 +2.69%，主力数据缺失，成交额1727亿。",
                    "technical": "继续站上5/10日线，短线仍站稳",
                    "volume": "量能接近5日均量，主力数据缺失/不明显",
                    "related_holdings": "财通集成电路产业股票C、华宝上证科创板芯片ETF联接C",
                    "source_skill": "hithink-industry-query",
                }
            ],
        },
        decision={"summary": "半导体进入观察榜，但不是追涨信号。"},
        skill_calls=[{"skill": "hithink-market-query"}, {"skill": "hithink-industry-query"}],
    )

    async def fake_skill(skill_name: str, query: str, limit: int = 10, timeout: int = 30):
        if skill_name == "news-search":
            return {
                "success": True,
                "datas": [
                    {
                        "标题": "半导体设备国产替代进程加速",
                        "extra": {"real_publish_source": "证券时报"},
                        "发布时间": "2026-07-01",
                        "链接": "https://example.com/news/semiconductor-equipment",
                    }
                ],
            }
        if skill_name == "report-search":
            return {
                "success": True,
                "datas": [
                    {
                        "标题": "半导体设备行业深度：先进制程资本开支回暖",
                        "extra": {"organization": "中金公司"},
                        "发布日期": "2026-06-28",
                        "链接": "https://example.com/report/semiconductor-equipment",
                    }
                ],
            }
        return {
            "success": True,
            "datas": [
                {
                    "指数简称": "半导体材料设备",
                    "最新涨跌幅:前复权": 2.8,
                    "成交额[20260701]": 180_000_000_000.0,
                }
            ],
        }

    result = await SectorDetailAgent(run_skill=fake_skill).explain(
        question="为什么半导体有机会？",
        snapshot=snapshot,
    )

    assert result["intent"] == "sector_detail"
    assert result["sector"]["name"] == "半导体/芯片"
    assert result["sector"]["tracking_code"] == "931743"
    assert "不是追涨" in result["answer"]
    assert "主力数据缺失" in result["answer"]
    assert "财通集成电路产业股票C" in result["answer"]
    assert "权威信息源" in result["answer"]
    assert "证券时报" in result["answer"]
    assert "中金公司" in result["answer"]
    assert "2026-07-01" in result["answer"]
    assert "研报｜半导体设备行业深度" in result["answer"]
    assert "https://example.com/news/semiconductor-equipment" in result["answer"]
    assert "https://example.com/report/semiconductor-equipment" in result["answer"]
    assert "暂无匹配" not in result["answer"]
    assert "。。" not in result["answer"]
    assert result["used_skills"] == ["hithink-industry-query", "hithink-zhishu-query", "news-search", "report-search"]
    assert "hithink-industry-query" in result["prompt_meta"]["template"]
