# 🛣️ 实现路线图：从版块监控到智能投顾

## 📅 总体时间规划

```
现在 (Week 1)          Week 2-3           Week 4-5           Week 6+
│                      │                  │                  │
├─ 版块监控完成 ✅     │                  │                  │
├─ 基金映射库         ├─ 买卖信号       ├─ 实时监控       ├─ 智能投顾完成
│  (数据收集)         │  (决策引擎)     │  (预警系统)     │  (全功能上线)
└─ 相关性计算         └─ API 集成       └─ 通知推送       └─ 性能优化
```

---

## 🎯 PHASE 1: 基金-版块映射库 (1-2周)

### 目标
```
建立完整的版块→基金转换库
使用户看到强势版块时，立即知道买哪只基金
```

### 任务分解

#### Task 1.1: 基金持仓数据采集
```python
# backend/app/services/fund_holding_service.py

class FundHoldingService:
    """采集和管理基金持仓数据"""
    
    async def fetch_all_fund_holdings(self):
        """
        从多个数据源爬取基金持仓
        
        数据源优先级:
        1. 基金公司官网 (最准确)
        2. 天天基金网
        3. 东财基金数据库
        4. 新浪基金数据
        
        缓存策略: 季度更新一次 (3个月)
        """
        # 实现细节...
        pass
    
    async def extract_fund_sectors(self, fund_code: str) -> dict:
        """
        提取基金的版块权重
        
        返回:
        {
            "001513": {
                "name": "易方达信息产业",
                "sectors": {
                    "半导体": 15.3,
                    "通信设备": 12.5,
                    "软件开发": 8.2,
                    ...
                },
                "last_update": "2026-06-30"
            }
        }
        """
        pass
```

#### Task 1.2: 版块-基金映射表构建
```python
# backend/app/services/sector_fund_mapping.py

class SectorFundMapping:
    """版块与基金的映射关系"""
    
    def build_mapping(self):
        """
        构建映射表
        
        输出:
        mapping = {
            "半导体": {
                "etf": [
                    {
                        "code": "006503",
                        "name": "财通集成电路",
                        "weight": 50.2,  # 该版块在基金中的权重
                    }
                ],
                "active_funds": [
                    {
                        "code": "001513",
                        "name": "易方达信息产业",
                        "weight": 15.3,  # 持仓权重
                        "style": "科技成长",
                    }
                ]
            },
            "光模块": {
                "related_sectors": ["通信设备", "5G"],
                "etf": [...],
                "active_funds": [...]
            }
        }
        """
        pass
    
    def get_related_funds(self, sector_code: str, top_n: int = 10):
        """
        获取与某版块相关的基金
        
        返回按相关性排序的基金列表
        """
        pass
```

#### Task 1.3: 历史相关性计算
```python
# backend/app/services/correlation_engine.py

class CorrelationEngine:
    """计算版块与基金的历史相关性"""
    
    def calculate_correlation(self, sector_code: str, fund_code: str) -> dict:
        """
        计算相关性系数
        
        方法:
        1. 获取过去1年的日净值数据 (基金 + 版块)
        2. 计算皮尔逊相关系数
        3. 按时间窗口计算 (1个月、3个月、6个月、1年)
        
        返回:
        {
            "fund_code": "001513",
            "sector_code": "半导体",
            "correlation_1m": 0.88,      # 最近1月相关性
            "correlation_3m": 0.92,
            "correlation_6m": 0.85,
            "correlation_1y": 0.89,
            "avg_correlation": 0.88,     # 用于排序
            "tracking_error": 2.5,       # 跟踪误差
        }
        """
        pass
    
    def batch_calculate_correlations(self):
        """
        批量计算所有基金与所有版块的相关性
        
        缓存策略: 每周计算一次
        存储: 数据库或Redis
        """
        pass
```

#### Task 1.4: 数据库设计
```sql
-- 基金持仓表
CREATE TABLE fund_holdings (
    id INT PRIMARY KEY AUTO_INCREMENT,
    fund_code VARCHAR(10),
    sector_code VARCHAR(20),
    sector_name VARCHAR(50),
    weight FLOAT,  -- 持仓权重
    stock_count INT,  -- 该版块有几只股
    last_update DATE,
    INDEX (fund_code, sector_code)
);

-- 基金-版块相关性表
CREATE TABLE sector_fund_correlation (
    id INT PRIMARY KEY AUTO_INCREMENT,
    fund_code VARCHAR(10),
    sector_code VARCHAR(20),
    correlation_1m FLOAT,
    correlation_3m FLOAT,
    correlation_6m FLOAT,
    correlation_1y FLOAT,
    avg_correlation FLOAT,
    tracking_error FLOAT,
    calculated_date DATE,
    INDEX (fund_code, sector_code, avg_correlation DESC)
);

-- 版块-基金推荐表
CREATE TABLE sector_fund_recommendation (
    id INT PRIMARY KEY AUTO_INCREMENT,
    sector_code VARCHAR(20),
    fund_code VARCHAR(10),
    recommendation_rank INT,  -- 排名
    score FLOAT,  -- 综合评分
    reason VARCHAR(255),
    last_update DATETIME,
    INDEX (sector_code, score DESC)
);
```

#### Task 1.5: API 设计
```python
# backend/app/api/v1/funds.py

@router.get("/sectors/{sector_code}/recommended-funds")
async def get_recommended_funds(sector_code: str, limit: int = 10):
    """
    获取某版块推荐的基金
    
    返回:
    {
        "sector": "半导体",
        "signal": "STRONG",  # 来自版块监控看板
        "funds": [
            {
                "rank": 1,
                "code": "006503",
                "name": "财通集成电路",
                "type": "ETF",
                "correlation": 0.95,
                "holding_weight": 50.2,
                "recent_return": 5.2,
                "liquidity_score": 9.5,
                "pe_percentile": 35,
                "recommendation_level": "STRONG_BUY"
            }
        ]
    }
    """
    pass

@router.get("/funds/{fund_code}/sector-exposure")
async def get_fund_sector_exposure(fund_code: str):
    """
    获取基金的版块暴露
    
    返回:
    {
        "fund_code": "001513",
        "name": "易方达信息产业",
        "sectors": [
            {
                "sector": "半导体",
                "weight": 15.3,
                "signal": "STRONG",  # 来自版块评分
                "expected_impact": "+2.5%"  # 预期贡献涨幅
            }
        ]
    }
    """
    pass
```

---

## 🎯 PHASE 2: 买卖决策引擎 (2-3周)

### 目标
```
自动生成买卖信号
从版块信号 → 基金推荐 → 仓位建议 → 止损止盈
```

### Task 2.1: 买入决策规则
```python
# backend/app/services/buy_signal_engine.py

class BuySignalEngine:
    """生成买入信号"""
    
    def generate_buy_signals(self) -> List[BuySignal]:
        """
        扫描所有版块，生成买入建议
        
        规则:
        IF 版块信号 == STRONG (评分 > 7.0)
        AND 版块资金净流入 > 5亿
        AND 持续上升天数 >= 2天
        THEN
            查询相关基金
            筛选相关性 > 0.85 的基金
            筛选PE分位 < 60% 的基金
            按得分排序
            生成买入建议
        """
        strong_sectors = self._get_strong_sectors()
        
        buy_signals = []
        for sector in strong_sectors:
            # 获取相关基金
            funds = self._get_related_funds(sector.code, min_correlation=0.85)
            
            # 过滤和排序
            filtered_funds = self._filter_and_rank_funds(funds)
            
            # 生成建议
            for fund in filtered_funds[:3]:  # 只推荐top3
                signal = BuySignal(
                    sector=sector,
                    fund=fund,
                    entry_price=fund.current_price,
                    position_size=self._calculate_position(fund),
                    stop_loss=self._calculate_stop_loss(fund),
                    take_profit=self._calculate_take_profit(fund),
                    confidence=self._calculate_confidence(fund),
                    reasoning=self._explain_buy_decision(fund),
                )
                buy_signals.append(signal)
        
        return buy_signals
    
    def _calculate_position(self, fund: Fund) -> float:
        """
        计算建议仓位
        
        逻辑:
        确信度高 (信号强 + 相关性高 + 估值便宜):
            → 可建 30-50%
        确信度中 (信号强 + 两个条件满足):
            → 可建 20-30%
        确信度低 (信号强 + 一个条件满足):
            → 可建 10-20%
        """
        confidence = self._calculate_confidence(fund)
        
        if confidence >= 0.8:
            return 0.40  # 40%
        elif confidence >= 0.6:
            return 0.25  # 25%
        else:
            return 0.15  # 15%
```

### Task 2.2: 卖出决策规则
```python
# backend/app/services/sell_signal_engine.py

class SellSignalEngine:
    """生成卖出信号"""
    
    def scan_sell_signals(self, portfolio: Portfolio) -> List[SellSignal]:
        """
        扫描持仓，生成卖出建议
        """
        sell_signals = []
        
        for holding in portfolio.holdings:
            # 检查止盈条件
            if self._check_take_profit(holding):
                sell_signals.append(SellSignal(
                    fund=holding.fund,
                    reason="止盈",
                    sell_ratio=0.50,  # 卖出一半
                    priority="HIGH"
                ))
            
            # 检查止损条件
            elif self._check_stop_loss(holding):
                sell_signals.append(SellSignal(
                    fund=holding.fund,
                    reason="止损",
                    sell_ratio=1.0,  # 全部卖出
                    priority="CRITICAL"
                ))
            
            # 检查版块转弱
            elif self._check_sector_weakening(holding):
                sell_signals.append(SellSignal(
                    fund=holding.fund,
                    reason="版块信号转弱",
                    sell_ratio=0.30,  # 减仓30%
                    priority="MEDIUM"
                ))
        
        return sell_signals
    
    def _check_take_profit(self, holding) -> bool:
        """
        止盈条件检查
        
        条件:
        1. 累计涨幅 >= 15%
        2. 版块从STRONG转WATCH
        3. 基金相对强弱开始下降
        """
        unrealized_return = holding.unrealized_return
        sector_score = self._get_sector_score(holding.related_sector)
        relative_strength = self._get_relative_strength(holding.fund)
        
        return (unrealized_return >= 0.15 and 
                sector_score < 6.0 and 
                relative_strength < 0)
```

### Task 2.3: 前端展示
```typescript
// frontend/src/components/investment/InvestmentAdvice.tsx

interface InvestmentDecision {
  action: "BUY" | "SELL" | "HOLD"
  funds: {
    code: string
    name: string
    reason: string
    positionSize: number
    entryPrice: number
    stopLoss: number
    takeProfit: number
    confidence: number
  }[]
  alerts: string[]
}

export function InvestmentAdvice() {
  return (
    <Card>
      <Tabs>
        <Tab label="买入建议">
          {/* 显示BUY信号 */}
          <BuyRecommendations />
        </Tab>
        <Tab label="卖出建议">
          {/* 显示SELL信号 */}
          <SellRecommendations />
        </Tab>
        <Tab label="风险预警">
          {/* 显示预警 */}
          <RiskAlerts />
        </Tab>
      </Tabs>
    </Card>
  )
}
```

---

## 🎯 PHASE 3: 实时监控预警 (1周)

### 目标
```
实时跟踪持仓风险
及时发现止盈/止损机会
```

### Task 3.1: WebSocket 实时推送
```python
# backend/app/api/ws/portfolio_stream.py

@app.websocket("/ws/portfolio/{user_id}")
async def portfolio_stream(websocket: WebSocket, user_id: str):
    """
    推送实时持仓数据
    
    推送频率: 每1分钟
    推送内容:
    - 版块评分变化
    - 持仓净值变化
    - 预警触发
    """
    await websocket.accept()
    
    while True:
        # 获取最新数据
        portfolio = await get_portfolio(user_id)
        
        # 计算变化
        changes = {
            "timestamp": datetime.now().isoformat(),
            "holdings": [
                {
                    "code": h.code,
                    "current_price": h.current_price,
                    "return": h.unrealized_return,
                    "sector_score": get_sector_score(h.related_sector),
                    "alerts": check_alerts(h),
                }
                for h in portfolio.holdings
            ]
        }
        
        # 推送
        await websocket.send_json(changes)
        
        # 等待1分钟
        await asyncio.sleep(60)
```

### Task 3.2: 风险预警系统
```python
# backend/app/services/risk_alert_engine.py

class RiskAlertEngine:
    """实时风险预警"""
    
    async def check_alerts(self):
        """
        定时检查所有持仓，触发预警
        
        预警类型:
        1. 红色预警 (止损线触发)
            - 版块连续3天下跌 + 资金流出
            - 基金单日跌幅 > 5%
            → 立即通知，建议止损
        
        2. 黄色预警 (需要关注)
            - 版块评分下降1分以上
            - 相关性快速下降
            - 大额赎回压力
            → 提示用户关注
        
        3. 绿色提示 (可考虑止盈)
            - 版块从STRONG转WATCH
            - 基金创历史新高
            → 提示用户考虑止盈
        """
        
        for holding in get_all_holdings():
            # 检查止损
            if holding.unrealized_return <= -0.10:
                await send_alert(
                    level="RED",
                    message=f"{holding.fund.name} 已跌幅-10%，建议止损",
                    action="STOP_LOSS"
                )
            
            # 检查预警
            sector_score = self._get_sector_score(holding.related_sector)
            if sector_score < 5.0:
                await send_alert(
                    level="YELLOW",
                    message=f"相关版块{holding.related_sector}信号转弱",
                    action="REDUCE_POSITION"
                )
            
            # 检查止盈
            if holding.unrealized_return >= 0.15 and sector_score < 6.0:
                await send_alert(
                    level="GREEN",
                    message=f"{holding.fund.name} 已涨幅+15%，可考虑止盈",
                    action="TAKE_PROFIT"
                )
```

### Task 3.3: 通知集成
```python
# 飞书通知
async def send_feishu_alert(alert: Alert):
    """发送飞书卡片通知"""
    card = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"🚨 {alert.message}\n\n操作建议: {alert.action}"
                    }
                }
            ]
        }
    }
    await send_feishu_message(card)

# 微信通知
async def send_wechat_alert(alert: Alert):
    """发送微信提醒"""
    message = f"{alert.message}\n建议: {alert.action}"
    await send_wechat_message(message)

# App 推送
async def send_app_notification(alert: Alert):
    """App推送通知"""
    notification = {
        "title": "投资提醒",
        "body": alert.message,
        "action": alert.action,
        "priority": alert.level
    }
    await push_notification(notification)
```

---

## 🎯 PHASE 4: 智能投顾 (2周)

### 目标
```
一站式投资决策支持
从"分析工具" 升级到 "投资顾问"
```

### 核心功能
```python
# backend/app/services/ai_advisor.py

class AIAdvisor:
    """智能投资顾问"""
    
    async def generate_portfolio_advice(self) -> PortfolioAdvice:
        """
        生成完整的组合建议
        """
        # 分析当前市场环境
        market_condition = await self._analyze_market()
        
        # 分析当前持仓
        portfolio = await self._analyze_portfolio()
        
        # 生成买入建议
        buy_recommendations = await self._generate_buy_advice(market_condition)
        
        # 生成卖出建议
        sell_recommendations = await self._generate_sell_advice(portfolio)
        
        # 提供组合优化建议
        rebalancing = await self._suggest_rebalancing(portfolio)
        
        # 综合决策
        return PortfolioAdvice(
            market_outlook=market_condition,
            current_portfolio=portfolio,
            buy_signals=buy_recommendations,
            sell_signals=sell_recommendations,
            rebalancing=rebalancing,
            overall_action="BUY" | "HOLD" | "SELL",
            confidence=0.75,
            reasoning="详细分析理由"
        )
```

---

## 📊 成功指标

### 定量指标
```
1. 决策效率
   - 从需求到建议: < 2分钟 ✅
   
2. 决策准确率
   - 买入信号成功率: > 70% ✅
   - 止损有效性: > 85% ✅
   
3. 收益提升
   - 年化收益: 从20% → 30% ✅
   
4. 风险降低
   - 最大回撤: 从25% → 10% ✅
```

### 定性指标
```
✅ 用户信心提升
✅ 决策更加理性
✅ 风险更加可控
✅ 交易更加频繁但更科学
```

---

## 🚀 下一步行动

### 本周 (Week 1)
```
□ 确认数据源 (基金持仓API)
□ 开始爬取基金数据
□ 设计数据库表结构
□ 启动 Phase 1 开发
```

### 下周 (Week 2)
```
□ 完成基金持仓采集
□ 计算版块-基金相关性
□ 构建映射推荐库
□ 开始 Phase 2 开发
```

### Week 3-4
```
□ 完成买卖决策规则
□ 前端展示集成
□ 回测验证信号准确率
□ 启动 Phase 3 开发
```

### Week 5+
```
□ 实时监控系统上线
□ 各种通知渠道集成
□ 智能投顾功能完善
□ 整体系统上线运营
```

---

**准备开始 Phase 1 吗？** 🚀

