from app.feishu.cards import build_sector_summary_card
from app.services.sector_card_service import build_focus_watch_rows, build_signal_bar


def test_sector_summary_card_has_decision_tables_and_actions():
    card = build_sector_summary_card(
        title="板块测试",
        conclusion="半导体有资金回流，但还没到追涨位置。",
        drivers=[
            {"name": "半导体设备", "value": "+24.4亿", "judgement": "偏强"},
            {"name": "电子", "value": "-257.5亿", "judgement": "风险"},
        ],
        holdings=[
            {"name": "易方达信息产业混合A", "code": "001513", "exposure": "科技/信息产业", "impact": "重点受益但仓位高"},
            {"name": "财通集成电路产业股票C", "code": "006503", "exposure": "半导体", "impact": "直接相关"},
        ],
        actions=["看半导体尾盘是否仍在资金流入前列", "看001513是否跟科技主线同向"],
        source_note="测试数据源",
    )

    assert card["header"]["title"]["content"] == "板块测试"
    content = str(card)
    assert "结论" in content
    assert "机会评价" in content
    assert "技术面/量能" in content
    assert "关键依据" not in content
    assert "持仓影响" not in content
    assert "下一步" in content
    assert "半导体有资金回流" in content


def test_signal_bar_is_visual_and_directional():
    assert build_signal_bar(2.4).startswith("█")
    assert "░" in build_signal_bar(-1.5)
    assert len(build_signal_bar(0, width=8)) == 8


def test_focus_watch_rows_include_user_sectors_etfs_and_holding_links():
    sectors = [
        {"f14": "通信设备", "f3": 2.1, "f62": 1_860_000_000},
        {"f14": "光模块", "f3": 3.4, "f62": 900_000_000},
        {"f14": "电池", "f3": -0.8, "f62": -320_000_000},
        {"f14": "半导体设备", "f3": 1.1, "f62": 2_400_000_000},
        {"f14": "有色金属", "f3": -1.2, "f62": -870_000_000},
    ]

    rows = build_focus_watch_rows(sectors)
    text = str(rows)

    assert "光模块/通信" in text
    assert "中证电池" in text
    assert "有色金属ETF" in text
    assert "易方达信息产业混合A" in text
    assert "南方中证电池主题ETF联接C" in text
    assert "█" in text


def test_sector_summary_card_renders_watch_rows_as_graphical_section():
    card = build_sector_summary_card(
        title="板块测试",
        conclusion="通信和光模块是今天最该盯的方向。",
        tone="green",
        decision="小仓观察",
        risk_level="中",
        drivers=[],
        holdings=[],
        actions=["尾盘只看光模块/通信资金是否继续扩散"],
        watch_rows=[
            {
                "name": "光模块/通信",
                "status": "强",
                "priority": "core",
                "bar": "███████░░░",
                "change_pct": "+2.10%",
                "flow": "+18.6亿",
                "etf": "通信ETF",
                "holding": "易方达信息产业混合A",
                "matched_sector": "光通信模块",
                "technical": "放量转强",
                "opportunity": "只适合小仓观察，等回踩不破再看",
                "volume": "量能放大，主力净流入",
                "tracking_code": "931160",
            }
        ],
        source_note="测试数据源",
    )

    assert card["header"]["template"] == "green"
    content = str(card)
    assert "今日动作" in content
    assert "小仓观察" in content
    assert "风险等级" in content
    assert "核心监控" in content
    assert "关注板块强弱" in content
    assert "机会评价" in content
    assert "技术面/量能" in content
    assert "[强]" in content
    assert "███████░░░" in content
    assert "只适合小仓观察" in content
    assert "量能放大" in content
    assert "放量转强" in content
    assert "跟踪：931160｜数据" in content
    assert "通信ETF" not in content


def test_semiconductor_watch_row_prefers_strong_equipment_over_broad_concept_outflow():
    sectors = [
        {"f12": "BK1326", "f14": "半导体设备", "f3": 4.83, "f62": 2_681_000_000},
        {"f12": "BK0917", "f14": "半导体概念", "f3": -0.38, "f62": -16_242_000_000},
        {"f12": "BK1036", "f14": "半导体", "f3": 1.33, "f62": -5_014_000_000},
    ]

    row = next(row for row in build_focus_watch_rows(sectors) if row["name"] == "半导体/芯片")

    assert row["matched_sector"] == "半导体设备"
    assert row["change_pct"] == "+4.83%"
    assert row["status"] == "强"
    assert "小仓观察" in row["opportunity"]


def test_watch_rows_show_source_codes_and_use_fixed_index_sources(monkeypatch):
    from app.services import sector_card_service as svc

    fixtures = {
        "2.931160": {"name": "通信设备", "code": "931160", "pct": -3.27, "amount": 212438380222.0},
        "2.931743": {"name": "半导体材料设备", "code": "931743", "pct": 5.40, "amount": 172724725464.0},
        "1.000819": {"name": "有色金属", "code": "1B0819", "pct": 1.25, "amount": 103877889450.7},
        "100.NDX100": {"name": "纳斯达克100", "code": "NDX100", "pct": -1.09, "amount": 0.0},
        "1.000932": {"name": "中证消费", "code": "000932", "pct": 2.49, "amount": 32034012642.4},
        "2.931719": {"name": "CS电池", "code": "931719", "pct": 1.16, "amount": 93141986800.0},
        "2.H30533": {"name": "中国互联网50", "code": "H30533", "pct": 3.48, "amount": 29464185825.8},
    }

    def fake_fixed_source(group, include_kline=False, market_context=""):
        source = group.get("source") or {}
        item = fixtures.get(source.get("secid"))
        if not item:
            return None
        return {
            "f12": item["code"],
            "f14": item["name"],
            "f3": item["pct"],
            "f62": 0,
            "amount": item["amount"],
            "source_code": source.get("display_code", item["code"]),
            "source_provider": source.get("provider", "测试源"),
            "source_secid": source.get("secid"),
                "technical_detail": "继续跌破5日线，仍未站稳10日线" if item["pct"] < 0 else "继续站上5/10日线，短线维持强势",
                "volume_detail": "量能接近5日均量，主力数据需以对应指数源为准",
                "expert_analysis": "今天不是简单看涨跌，而是结合均线、量能和资金判断趋势状态。",
            }

    monkeypatch.setattr(svc, "_fetch_fixed_source_row", fake_fixed_source)
    rows = svc.build_focus_watch_rows([], include_kline=True)

    by_name = {row["name"]: row for row in rows}
    assert by_name["光模块/通信"]["matched_sector"] == "通信设备"
    assert by_name["光模块/通信"]["source_code"] == "931160"
    assert by_name["光模块/通信"]["change_pct_value"] == -3.27
    assert by_name["光模块/通信"]["turnover"] == 212438380222.0
    assert by_name["光模块/通信"]["net_inflow"] is None
    assert by_name["半导体/芯片"]["matched_sector"] == "半导体材料设备"
    assert by_name["半导体/芯片"]["source_code"] == "931743"
    assert by_name["有色金属"]["matched_sector"] == "有色金属"
    assert by_name["有色金属"]["source_code"] == "1B0819"
    assert by_name["美股科技/纳指"]["matched_sector"] == "纳斯达克100"
    assert by_name["美股科技/纳指"]["change_pct"] == "-1.09%"
    assert by_name["主要消费"]["matched_sector"] == "中证消费"
    assert by_name["主要消费"]["source_code"] == "000932"
    assert by_name["中证电池"]["matched_sector"] == "CS电池"
    assert by_name["中证电池"]["source_code"] == "931719"
    assert by_name["港股互联网"]["matched_sector"] == "中国互联网50"
    assert by_name["港股互联网"]["source_code"] == "H30533"


def test_watch_rows_prefer_user_configured_index_over_skill_broad_match(monkeypatch):
    from app.services import sector_card_service as svc

    def fake_fixed_source(group, include_kline=False, market_context=""):
        if group["name"] != "半导体/芯片":
            return None
        return {
            "f12": "931743",
            "f14": "半导体材料设备",
            "f3": 5.40,
            "f62": None,
            "amount": 172_724_725_464.0,
            "source_code": "931743",
            "source_provider": "测试精确指数源",
            "source_secid": "2.931743",
            "display_flow": "成交额 1727.2亿 / 主力 暂无",
            "technical_detail": "继续站上5/10日线，短线仍站稳",
        }

    monkeypatch.setattr(svc, "_fetch_fixed_source_row", fake_fixed_source)
    rows = svc.build_focus_watch_rows([
        {
            "f12": "H30184.CSI",
            "f14": "半导体",
            "f3": 3.29,
            "f62": None,
            "amount": 497_120_000_000.0,
            "source_skill": "hithink-zhishu-query",
        }
    ], include_kline=True)

    semi = next(row for row in rows if row["name"] == "半导体/芯片")
    assert semi["matched_sector"] == "半导体材料设备"
    assert semi["source_code"] == "931743"
    assert semi["change_pct"] == "+5.40%"


def test_sector_card_uses_expert_technical_paragraph_not_weak_label():
    card = build_sector_summary_card(
        title="板块测试",
        conclusion="半导体材料设备最强。",
        drivers=[],
        holdings=[],
        actions=["等回踩确认"],
        watch_rows=[
            {
                "name": "半导体/芯片",
                "status": "强",
                "priority": "core",
                "bar": "██████████",
                "change_pct": "+5.40%",
                "flow": "成交额 1727.2亿",
                "matched_sector": "半导体材料设备",
                "source_code": "931743",
                "technical": "继续站上5/10日线，短线仍站稳",
                "volume": "量能接近5日均量",
                "opportunity": "有短线机会",
                "expert_analysis": "半导体材料设备今天继续站上5/10日线，不是首次突破；量能接近5日均量，说明资金承接尚可但没有明显放量，适合等回踩确认。",
            }
        ],
    )

    content = str(card)
    assert "半导体材料设备今天继续站上5/10日线" in content
    assert "不是首次突破" in content
    assert "等回踩确认" in content


def test_sector_card_puts_market_diagnosis_once_not_inside_every_technical_row():
    card = build_sector_summary_card(
        title="板块测试",
        conclusion="半导体强于通信。",
        drivers=[],
        holdings=[],
        actions=["等尾盘确认"],
        market_diagnosis="同花顺问财：上涨家数占优，强势方向集中在医药和半导体材料，弱势方向集中在通信和电子。",
        watch_rows=[
            {
                "name": "半导体/芯片",
                "status": "强",
                "priority": "core",
                "bar": "██████████",
                "change_pct": "+5.40%",
                "flow": "成交额 1727.2亿",
                "matched_sector": "半导体材料设备",
                "source_code": "931743",
                "technical": "继续站上5/10日线，短线仍站稳",
                "volume": "量能接近5日均量",
                "opportunity": "有短线机会",
                "expert_analysis": "半导体材料设备今天继续站上5/10日线，量能接近5日均量，适合等回踩确认。",
            },
            {
                "name": "光模块/通信",
                "status": "弱",
                "priority": "core",
                "bar": "░░░░░█████",
                "change_pct": "-2.50%",
                "flow": "成交额 2200.0亿",
                "matched_sector": "通信设备",
                "source_code": "931160",
                "technical": "继续跌破5/10日线，趋势仍未修复",
                "volume": "量能放大",
                "opportunity": "机会不足",
                "expert_analysis": "通信设备今天继续跌破5/10日线，放量下跌说明抛压未结束。",
            },
        ],
    )

    content = str(card)
    assert "大盘诊断" in content
    assert content.count("同花顺问财：上涨家数占优") == 1
    assert content.count("大盘环境") == 0


def test_sector_card_renders_opportunity_board_with_levels_and_detail_prompt():
    card = build_sector_summary_card(
        title="板块测试",
        conclusion="半导体是今天第一观察方向。",
        drivers=[],
        holdings=[],
        actions=["点开半导体详情看证据"],
        market_diagnosis="缩量修复：全A成交额32938亿，较昨日缩量6.94%；上涨3051/下跌2364，涨停170/跌停20。",
        watch_rows=[
            {
                "name": "半导体/芯片",
                "status": "强",
                "priority": "core",
                "bar": "██████████",
                "change_pct": "+6.32%",
                "flow": "成交额 6224.7亿",
                "matched_sector": "半导体",
                "source_code": "881121.TI",
                "opportunity_level": "强机会",
                "opportunity": "强机会：半导体 +6.32%，主力净流入248.9亿；大盘为缩量修复，等回踩不破。",
                "detail_prompt": "为什么半导体/芯片有机会？",
                "technical": "继续站上5/10日线，短线仍站稳",
                "volume": "成交额放大",
            }
        ],
    )

    content = str(card)
    assert "机会榜" in content
    assert "强机会" in content
    assert "为什么半导体/芯片有机会？" in content
    assert "机会评价" not in content


def test_build_sector_context_payload_keeps_auditable_evidence_for_followups():
    from app.services.sector_card_service import build_sector_context_payload

    payload = build_sector_context_payload(
        market_snapshot={
            "state": "缩量修复",
            "summary": "缩量修复：全A成交额32938亿，较昨日缩量6.94%。",
            "source_skill": "hithink-market-query",
        },
        watch_rows=[
            {
                "name": "半导体/芯片",
                "matched_sector": "半导体",
                "tracking_code": "931743",
                "source_code": "H30184.CSI",
                "change_pct_value": 3.29,
                "turnover": 497_120_000_000,
                "net_inflow": None,
                "opportunity_level": "观察",
                "opportunity": "观察：半导体 +3.29%，主力数据缺失。",
                "technical": "继续站上5/10日线",
                "holding": "财通集成电路产业股票C",
                "source_skill": "hithink-zhishu-query",
            }
        ],
    )

    assert payload["market_mood"]["state"] == "缩量修复"
    assert payload["decision"]["summary"] == "观察：半导体 +3.29%，主力数据缺失。"
    evidence = payload["context"]["sector_evidence"][0]
    assert evidence["name"] == "半导体/芯片"
    assert evidence["tracking_code"] == "931743"
    assert evidence["data_code"] == "H30184.CSI"
    assert evidence["main_flow"] is None
    assert payload["skill_calls"] == [
        {"skill": "hithink-market-query"},
        {"skill": "hithink-zhishu-query"},
    ]
