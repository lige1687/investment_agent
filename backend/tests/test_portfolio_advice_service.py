from app.services.portfolio_advice_service import compose_portfolio_advice


def test_compose_portfolio_advice_gives_detailed_sector_actions_and_reasons():
    watch_rows = [
        {
            "name": "半导体/芯片",
            "priority": "core",
            "status": "强",
            "matched_sector": "半导体设备",
            "change_pct": "+4.80%",
            "flow": "+26.8亿",
            "technical": "日K站上5/10日线",
            "volume": "量能接近5日均量，主力净流入",
            "opportunity": "有短线机会，但只适合回踩不破后小仓观察",
            "holding": "财通集成电路产业股票C、华宝上证科创板芯片ETF联接C",
            "score": 7.4,
        },
        {
            "name": "光模块/通信",
            "priority": "core",
            "status": "弱",
            "matched_sector": "5G概念",
            "change_pct": "-2.60%",
            "flow": "-321.0亿",
            "technical": "日K跌破5/10日线",
            "volume": "量能接近5日均量，主力净流出",
            "opportunity": "机会不足，先等止跌和资金回流",
            "holding": "易方达信息产业混合A",
            "score": -34.7,
        },
    ]

    answer = compose_portfolio_advice(
        message="我的持仓今天建议是啥？",
        watch_rows=watch_rows,
        portfolio={"total_value": 100000, "total_pnl_pct": 12.3},
        skill_notes=["市场情绪偏分歧，行业轮动集中在半导体设备。"],
    )

    assert "总判断" in answer
    assert "大盘情绪" in answer
    assert "分板块建议" in answer
    assert "半导体/芯片" in answer
    assert "小仓观察" in answer
    assert "回踩" in answer
    assert "光模块/通信" in answer
    assert "不补仓" in answer
    assert "日K跌破5/10日线" in answer
    assert "财经Skill要点" in answer
    assert "市场情绪偏分歧" in answer


def test_compose_portfolio_advice_marks_skill_degraded_when_no_skill_notes():
    answer = compose_portfolio_advice(
        message="今天怎么操作？",
        watch_rows=[
            {
                "name": "中证电池",
                "priority": "core",
                "status": "流",
                "matched_sector": "新能源车",
                "change_pct": "-1.20%",
                "flow": "-120.0亿",
                "technical": "日K跌破5/10日线",
                "volume": "主力净流出",
                "opportunity": "资金仍在流出，不适合主动加仓",
                "holding": "南方中证电池主题ETF联接C",
                "score": -13.2,
            }
        ],
        portfolio={"total_value": 100000, "total_pnl_pct": 12.3},
        skill_notes=[],
    )

    assert "财经Skill要点" in answer
    assert "暂未拿到可用skill结果" in answer
    assert "仅供参考，不构成投资建议" in answer


def test_compose_portfolio_advice_can_reference_recent_context_snapshot():
    answer = compose_portfolio_advice(
        message="为什么半导体有机会？",
        watch_rows=[
            {
                "name": "半导体/芯片",
                "priority": "core",
                "status": "强",
                "matched_sector": "半导体",
                "change_pct": "+3.29%",
                "flow": "成交额 4971.2亿 / 主力 暂无",
                "technical": "继续站上5/10日线",
                "volume": "主力资金数据缺失/不明显",
                "opportunity": "观察：半导体 +3.29%，主力数据缺失。",
                "holding": "财通集成电路产业股票C",
                "score": 3.2,
            }
        ],
        portfolio={"total_value": 100000, "total_pnl_pct": 12.3},
        skill_notes=[],
        recent_context="## 最近证据快照\n- 半导体/芯片：跟踪代码 931743，数据代码 H30184.CSI，主力数据缺失",
    )

    assert "最近证据" in answer
    assert "跟踪代码 931743" in answer
    assert "数据代码 H30184.CSI" in answer


def test_compose_portfolio_advice_filters_unmatched_live_rows_when_context_exists():
    answer = compose_portfolio_advice(
        message="为什么半导体有机会？",
        watch_rows=[
            {
                "name": "半导体/芯片",
                "priority": "core",
                "status": "平",
                "matched_sector": "暂无匹配",
                "change_pct": "+0.00%",
                "flow": "+0.0亿",
                "technical": "震荡观察",
                "volume": "主力资金不明显",
                "opportunity": "信号一般，只观察不交易",
                "holding": "财通集成电路产业股票C",
                "score": 0,
            }
        ],
        portfolio={"total_value": 100000, "total_pnl_pct": 12.3},
        skill_notes=[],
        recent_context="## 最近证据快照\n- 半导体/芯片：半导体材料设备，涨跌 2.69，跟踪代码 931743，数据代码 931743，主力数据缺失",
    )

    assert "最近证据" in answer
    assert "半导体材料设备" in answer
    assert "暂无匹配" not in answer
    assert "本次追问优先基于最近证据快照" in answer
