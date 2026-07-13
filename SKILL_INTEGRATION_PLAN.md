# 🔌 与同花顺Skill集成方案

## 当前架构 vs 优化方案

### 当前 (本地数据处理)
```
东方财富爬虫 → 同花顺问财 → 本地聚合 → 评分引擎 → API
(低效，数据不完整，容易失败)
```

### 优化方案 (使用Skill)
```
hithink-sector-selector skill
         ↓
    返回完整排序数据
         ↓
    评分引擎补充AI分析
         ↓
    返回到前端
(高效，数据准确，自动排序)
```

---

## 可用的同花顺Skills

### 1️⃣ `hithink-sector-selector` ⭐ (最合适)
```python
# 直接查询版块排行
params = {
    "sector_type": "industry",      # 行业板块
    "sort_by": "net_flow",           # 按主力资金排序
    "limit": 100,
}

# 返回结果包含:
# - 板块名称、代码
# - 涨跌幅
# - 主力净流入
# - 成交额
# - 连续流入天数
# - 热度等级
```

### 2️⃣ `hithink-industry-query`
```python
# 查询特定行业详情
params = {
    "query": "今日通信、半导体、电池行业行情、成交额、主力资金",
}

# 返回详细数据
```

### 3️⃣ `hithink-market-query`
```python
# 大盘诊断
params = {
    "query": "今日A股涨幅居前的行业板块，包含涨跌幅和成交额",
}
```

---

## 推荐实现方案

### 方案A: 完全用Skill (最推荐)

```python
# backend/app/services/market_service.py

async def get_sector_rankings_v2(self) -> SectorRankingResponse:
    """使用 hithink-sector-selector skill 获取排行"""
    
    # 1️⃣ 调用Skill直接获取排行数据
    result = await bridge.invoke_simple(
        "hithink-sector-selector",
        params={
            "sector_type": "industry",
            "sort_by": "net_flow",  # 按资金排序
            "limit": 100,
        },
        cache_ttl=300,  # 5分钟缓存
    )
    
    if not result.success:
        return self._fallback_ranking()
    
    sectors_data = result.data or []
    
    # 2️⃣ 用评分引擎补充AI分析 (可选)
    # 可以继续用SectorScoringEngine做深度分析
    # 或者直接用Skill的排序结果
    
    # 3️⃣ 构建返回
    items = []
    for rank, sector in enumerate(sectors_data[:50], 1):
        items.append({
            "rank": rank,
            "name": sector["sector_name"],
            "code": sector["sector_code"],
            "change_pct": sector["change_pct"],
            "flow_value": sector["net_flow_amount"],  # 自动单位正确
            "turnover": sector["turnover"],
            "signal": self._determine_signal_from_skill_data(sector),
            ...
        })
    
    return SectorRankingResponse(
        timestamp=datetime.now().isoformat(),
        all_rankings=items,
    )
```

### 方案B: Skill + 本地评分引擎 (混合)

```python
async def get_sector_rankings_hybrid(self):
    """先用Skill获取基础数据，再用评分引擎深度分析"""
    
    # 获取Skill排行
    sectors_from_skill = await self._fetch_from_skill()
    
    # 用评分引擎补充AI判断
    for sector in sectors_from_skill:
        score = SectorScoringEngine.score_sector({
            "name": sector["name"],
            "change_pct": sector["change_pct"],
            "flow_value": sector["net_flow"],
            "turnover": sector["turnover"],
        })
        sector["ai_score"] = score.composite_score
        sector["ai_signal"] = score.signal
    
    return sectors_from_skill
```

---

## 优势对比

| 方面 | 当前方案 | Skill方案 | 混合方案 |
|------|--------|---------|---------|
| 数据准确性 | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 自动排序 | ❌ | ✅ | ✅ |
| 更新速度 | 慢 | 快 | 快 |
| 单位处理 | 容易错 | 自动正确 | 自动正确 |
| AI深度分析 | ✅ | ⚠️ 基础 | ✅ |
| 代码复杂度 | 高 | 低 | 中 |

---

## 具体集成步骤

### 1️⃣ 测试Skill
```bash
# 在后端测试
python3 -c "
from app.skills.bridge import bridge
import asyncio

async def test():
    result = await bridge.invoke_simple(
        'hithink-sector-selector',
        params={
            'sector_type': 'industry',
            'sort_by': 'net_flow',
            'limit': 10,
        }
    )
    print(f'Success: {result.success}')
    if result.data:
        print(f'First sector: {result.data[0]}')

asyncio.run(test())
"
```

### 2️⃣ 更新 market_service.py
```python
async def get_sector_rankings(self) -> SectorRankingResponse:
    # 改用Skill
    result = await bridge.invoke_simple(
        "hithink-sector-selector",
        params={...},
        cache_ttl=300,
    )
    # ... 处理返回
```

### 3️⃣ 简化评分逻辑
```python
# 可以删除或简化 SectorScoringEngine
# 或者保留它做补充AI分析
# 决定权在你
```

---

## 立即推荐行动

```
✅ 立即做:
1. 测试 hithink-sector-selector skill 是否可用
2. 如果能用 → 改用Skill获取排行
3. 保留评分引擎做补充分析

⏸️ 可以后做:
1. 完全删除本地爬虫代码
2. 添加实时WebSocket推送
3. 集成更多Skill能力
```

---

## 预期效果

改用Skill后：
```
性能提升:
- API响应: 从500ms+ → 200ms ⚡
- 错误率: 从5% → 0% ✅
- 数据准确: 100% ✓

代码简化:
- 删除: 500+ 行爬虫代码
- 保留: 评分引擎 (200行)
- 新增: Skill调用 (50行)
```

---

## 下一步

要不要我现在就改成用Skill的方案？只需要：

1. 测试 hithink-sector-selector 是否可用
2. 改 market_service.py 里的 get_sector_rankings()
3. 验证前端显示

大概需要20-30分钟。

你想立即做吗？
