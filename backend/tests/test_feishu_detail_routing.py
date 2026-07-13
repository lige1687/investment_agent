from app.api.v1.feishu import should_route_to_sector_detail


def test_should_route_sector_detail_questions_only():
    assert should_route_to_sector_detail("为什么半导体有机会？")
    assert should_route_to_sector_detail("通信今天为啥要观察")
    assert should_route_to_sector_detail("有色金属为什么要回避？")
    assert not should_route_to_sector_detail("我的持仓今天建议是什么？")
    assert not should_route_to_sector_detail("推荐几个基金对比一下")
