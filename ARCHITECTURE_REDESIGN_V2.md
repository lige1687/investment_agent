# 🏗️ 系统架构重设计 (Architecture Redesign v2.0)

## 核心需求重新定位

### 用户真实需求
```
我要的不是"分析工具"
我要的是"实时监控系统" + "当日决策助手"

具体需求：
1. 实时监控我的持仓版块
2. 如果有异动，立即告诉我
3. 基于异动给出当天的买卖建议
4. 建议要有"权威性"（清晰的数据依据）
5. 发现新机会时，告诉我理由
6. 给我审阅权，让我决定是否观察
7. 要有分级的观察列表（持仓>观察>忽略）
```

### 这意味着什么？
```
❌ 不需要: 离线分析、历史回测、"过去可能怎样"
✅ 需要: 实时监控、异动检测、"现在应该怎么办"

❌ 不需要: 自动决策
✅ 需要: 智能建议 + 用户决策

❌ 不需要: 静态的基金推荐列表
✅ 需要: 动态的、分级的、实时更新的观察列表
```

---

## 架构设计（从零开始重新思考）

### 第一层：数据实时流处理层

#### 需要什么？
```
实时行情数据流:
  版块价格 → 每分钟更新
  资金流向 → 每分钟更新
  成交量能 → 每分钟更新
  基金净值 → 每分钟更新（闭市后）

个人持仓数据：
  持仓基金 → 实时
  持仓价格 → 实时
  浮盈浮亏 → 实时计算
```

#### 架构方案
```python
# backend/app/realtime/stream_processor.py

class RealtimeStreamProcessor:
    """实时数据流处理"""
    
    async def start_monitoring(self):
        """
        启动实时监控
        
        数据流：
        行情数据 (1分钟)
            ↓
        异动检测 (实时)
            ↓
        信号生成 (实时)
            ↓
        告警推送 (秒级)
        """
        
        # 创建数据管道
        self.price_stream = AsyncIterator()      # 价格流
        self.flow_stream = AsyncIterator()       # 资金流
        self.volume_stream = AsyncIterator()     # 量能流
        self.holding_stream = AsyncIterator()    # 持仓流
        
        # 并行处理多个数据流
        tasks = [
            self._monitor_price_changes(),
            self._monitor_fund_flow(),
            self._monitor_volume_surge(),
            self._monitor_holding_change(),
            self._detect_anomalies(),
        ]
        
        await asyncio.gather(*tasks)
```

### 第二层：异动检测引擎

#### 异动是什么？
```
异动 ≠ 小幅波动

异动定义（触发检测的条件）：
┌─────────────────────────────────────────┐
│ 1. 价格异动                             │
│    ├─ 日内涨幅突然 >2%（在无新闻的情况） │
│    ├─ 突破重要支撑/阻力位               │
│    └─ 创出历史新高/新低                 │
│                                         │
│ 2. 资金异动                             │
│    ├─ 主力净流入 >10亿/分钟             │
│    ├─ 单笔大单 >5亿                     │
│    └─ 资金流向反向（从流出→流入）      │
│                                         │
│ 3. 量能异动                             │
│    ├─ 成交量 >5日均量的2倍              │
│    ├─ 换手率突增                        │
│    └─ 日内成交额创历史新高              │
│                                         │
│ 4. 技术异动                             │
│    ├─ 突破均线 (5/10/20日线)            │
│    ├─ 形成明显的K线形态                 │
│    └─ 技术指标共振                      │
│                                         │
│ 5. 综合异动                             │
│    ├─ 价格 + 资金 + 量能 同向           │
│    └─ 触发"黄金买点"                    │
└─────────────────────────────────────────┘
```

#### 检测引擎实现
```python
# backend/app/realtime/anomaly_detector.py

class AnomalyDetector:
    """异动检测引擎"""
    
    def detect_price_anomaly(self, sector: Sector) -> Optional[Anomaly]:
        """
        检测价格异动
        
        返回:
        {
            "type": "PRICE_SURGE",
            "severity": "HIGH",  # LOW/MEDIUM/HIGH/CRITICAL
            "change": 2.5,  # 涨幅%
            "reason": "突破20日线，放量跟随",
            "timestamp": "2026-07-02 14:35:00",
        }
        """
        
        current_price = sector.current_price
        prev_close = sector.prev_close
        change_pct = (current_price - prev_close) / prev_close * 100
        
        # 检测突增
        if change_pct > 2.0:  # 突增2%
            # 检查是否有新闻催化
            if not self._has_news_catalyst(sector):
                # 检查技术面
                ma5 = self._get_ma(sector, 5)
                ma20 = self._get_ma(sector, 20)
                
                if current_price > ma20 and current_price > ma5:
                    return Anomaly(
                        type="PRICE_SURGE_BREAKOUT",
                        severity="HIGH",
                        change=change_pct,
                        reason=f"突破20日线{(current_price-ma20)/ma20*100:.1f}%，技术面转强",
                    )
        
        return None
    
    def detect_fund_flow_anomaly(self, sector: Sector) -> Optional[Anomaly]:
        """
        检测资金异动
        
        关键：检测"反向"或"剧增"
        """
        
        current_inflow = sector.current_net_inflow
        prev_inflow = sector.prev_day_inflow
        
        # 检测反向
        if prev_inflow < 0 and current_inflow > 0:
            return Anomaly(
                type="FUND_REVERSAL",
                severity="MEDIUM",
                inflow=current_inflow,
                reason=f"资金从净流出转为净流入 {current_inflow:.1f}亿",
            )
        
        # 检测剧增
        if current_inflow > 10.0 and current_inflow > prev_inflow * 2:
            return Anomaly(
                type="FUND_SURGE",
                severity="HIGH",
                inflow=current_inflow,
                reason=f"主力资金突然净流入 {current_inflow:.1f}亿，是5日均值的{current_inflow/(self._get_avg_inflow()*5):.1f}倍",
            )
        
        return None
    
    def detect_combined_anomaly(self, sector: Sector) -> Optional[Anomaly]:
        """
        检测综合异动（最重要）
        
        当价格 + 资金 + 量能同向时，这是最强的信号
        """
        
        price_anomaly = self.detect_price_anomaly(sector)
        flow_anomaly = self.detect_fund_flow_anomaly(sector)
        volume_anomaly = self.detect_volume_anomaly(sector)
        
        # 所有指标同向
        if price_anomaly and flow_anomaly and volume_anomaly:
            return Anomaly(
                type="GOLDEN_BUY_POINT",
                severity="CRITICAL",
                reason="价格突破 + 资金净流入 + 量能放大 = 黄金买点",
                components=[price_anomaly, flow_anomaly, volume_anomaly],
            )
        
        return None
```

### 第三层：权威信号生成

#### "权威性"是什么？
```
权威 ≠ 准确率高
权威 = 清晰的逻辑链 + 多源数据印证 + 历史成功率可查

权威信号的组成：
┌────────────────────────────────────────────┐
│ 信号 = 数据 + 逻辑 + 历史验证               │
│                                            │
│ 例如：半导体STRONG信号                     │
│ ─────────────────────────────────────────  │
│ 数据来源：                                 │
│  1. 东财实时行情 (价格/资金/量能)          │
│  2. 同花顺问财 (机构资金/大单)             │
│  3. 个股持仓分析 (前十大成分股涨幅)        │
│                                            │
│ 逻辑链：                                   │
│  1. 价格：突破20日线，今日涨2.8%           │
│  2. 资金：主力净流入8.2亿（创3月新高）    │
│  3. 量能：成交额120亿（1.8倍5日均量）     │
│  4. 持仓：九大成分股中8只上涨              │
│  5. 外部：行业政策利好                    │
│                                            │
│ 历史验证：                                 │
│  类似信号历史成功率：73% (25次中18次成功)  │
│  平均持续时间：5-8天                       │
│  平均涨幅：+8.5%                           │
│                                            │
│ 风险提示：                                 │
│  如果回踩不破20日线 = 趋势确认（继续持有）│
│  如果跌破20日线     = 中线走弱（考虑减仓）│
└────────────────────────────────────────────┘
```

#### 信号生成逻辑
```python
# backend/app/realtime/authority_signal_engine.py

class AuthoritySignalEngine:
    """权威信号生成"""
    
    async def generate_signal(self, sector: Sector, anomaly: Anomaly) -> Signal:
        """
        基于异动生成权威信号
        """
        
        # 1. 收集多源数据
        data_sources = await asyncio.gather(
            self._get_eastmoney_data(sector),
            self._get_iwencai_data(sector),
            self._get_component_stocks(sector),
            self._get_policy_news(sector),
        )
        
        # 2. 构建逻辑链
        logic_chain = self._build_logic_chain(
            anomaly=anomaly,
            price_data=data_sources[0],
            fund_data=data_sources[1],
            stocks_data=data_sources[2],
            policy=data_sources[3],
        )
        
        # 3. 查询历史成功率
        historical_validation = await self._validate_against_history(
            pattern=logic_chain.pattern,
            sector=sector,
        )
        
        # 4. 生成权威信号
        return Signal(
            sector=sector,
            type="BUY" | "SELL" | "WATCH",
            confidence=self._calculate_confidence(
                logic_chain,
                historical_validation,
            ),
            reasoning=self._explain_signal(logic_chain),
            data_sources=data_sources,
            historical_success_rate=historical_validation.success_rate,
            risk_warning=self._generate_risk_warning(logic_chain),
            timestamp=datetime.now(),
        )
    
    def _build_logic_chain(self, **kwargs) -> LogicChain:
        """
        构建清晰的逻辑链
        
        输出格式便于用户理解：
        为什么我们推荐买？
        1. 价格理由：突破20日线 (技术面转强)
        2. 资金理由：主力净流入8.2亿 (机构开始入场)
        3. 量能理由：成交放大1.8倍 (确认有效买盘)
        4. 持仓理由：8/9成分股上涨 (板块共识强)
        5. 催化理由：新政策出台 (基本面支撑)
        
        综合评分：7.4/10 (STRONG)
        """
        
        reasons = []
        
        # 价格理由
        if kwargs['anomaly'].type == "PRICE_SURGE_BREAKOUT":
            reasons.append({
                "dimension": "技术面",
                "description": f"突破20日线，涨幅{kwargs['anomaly'].change:.1f}%",
                "strength": "HIGH",
            })
        
        # 资金理由
        if kwargs['anomaly'].type == "FUND_SURGE":
            reasons.append({
                "dimension": "资金面",
                "description": f"主力净流入{kwargs['anomaly'].inflow:.1f}亿",
                "strength": "HIGH",
            })
        
        # 量能理由
        reasons.append({
            "dimension": "热度面",
            "description": f"成交量{kwargs['anomaly'].volume_ratio:.1f}倍5日均量",
            "strength": "MEDIUM",
        })
        
        # 持仓理由
        strong_stocks = len([s for s in kwargs['stocks_data'] if s['change'] > 0])
        total_stocks = len(kwargs['stocks_data'])
        reasons.append({
            "dimension": "持仓面",
            "description": f"{strong_stocks}/{total_stocks}成分股上涨",
            "strength": "MEDIUM",
        })
        
        # 政策理由
        if kwargs['policy']:
            reasons.append({
                "dimension": "基本面",
                "description": f"利好政策：{kwargs['policy'].title}",
                "strength": "LOW",
            })
        
        return LogicChain(
            pattern=f"综合异动 {len(reasons)} 维度同向",
            reasons=reasons,
        )
```

### 第四层：当日建议生成

#### 当日建议的特点
```
实时性：基于当日盘口动向
决策性：立即可执行的操作建议
原子性：不依赖昨日决策，每日独立判断
```

#### 建议类型
```python
# backend/app/realtime/daily_advice_engine.py

class DailyAdviceEngine:
    """当日建议生成"""
    
    async def generate_daily_advice(self, portfolio: Portfolio) -> DailyAdvice:
        """
        生成当日建议
        
        注意：这是"当日"建议，基于当日盘口
        明天重新评估，完全独立
        """
        
        advice = DailyAdvice()
        
        # 对于每个持仓版块
        for holding in portfolio.holdings:
            sector = holding.sector
            
            # 检测当日异动
            anomalies = await self._detect_anomalies(sector)
            
            for anomaly in anomalies:
                # 根据异动生成信号
                signal = await self._generate_signal(sector, anomaly)
                
                # 根据信号生成建议
                if signal.type == "BUY":
                    advice.add_action(
                        DailyAction(
                            type="INCREASE_POSITION",
                            sector=sector,
                            reason=f"{anomaly.reason} - {signal.confidence:.0%}确信",
                            amount="追加 10-20%",
                            entry_point="当前价",
                            target_price=self._calculate_target(signal),
                            stop_loss=self._calculate_stop_loss(signal),
                        )
                    )
                
                elif signal.type == "SELL":
                    advice.add_action(
                        DailyAction(
                            type="REDUCE_POSITION",
                            sector=sector,
                            reason=f"{anomaly.reason} - 建议止盈或减仓",
                            amount="减仓 30-50%",
                        )
                    )
        
        return advice
```

---

## 第五层：新机会发现与观察列表

### 分级观察列表架构

```
┌────────────────────────────────────────────┐
│            观察列表三级体系                 │
├────────────────────────────────────────────┤
│                                            │
│ 【第一级】持仓版块                        │
│ ─────────────────────────────────────────  │
│ 优先级：最高（100）                       │
│ 监控频率：实时（每分钟）                   │
│ 内容：你已经持有基金的相关版块             │
│ 样例：半导体 (持仓:001513)                 │
│        光模块 (持仓:006503)                 │
│ 提醒：异动立即推送                        │
│                                            │
│ 【第二级】观察版块                        │
│ ─────────────────────────────────────────  │
│ 优先级：中等（50）                        │
│ 监控频率：常规（每天分析）                 │
│ 内容：有潜力但还没买的版块                 │
│ 样例：医药生物 (信号评分:6.8)              │
│        人工智能 (等待机会)                  │
│ 提醒：形成明确机会时推送                   │
│ 操作：用户可以确认加入观察/升级为持仓      │
│                                            │
│ 【第三级】忽略版块                        │
│ ─────────────────────────────────────────  │
│ 优先级：低（10）                          │
│ 监控频率：不监控                           │
│ 内容：不感兴趣或风险较高的版块             │
│ 提醒：不推送                               │
│                                            │
└────────────────────────────────────────────┘
```

### 新机会发现流程

```python
# backend/app/realtime/opportunity_discovery.py

class OpportunityDiscovery:
    """新机会发现"""
    
    async def daily_scan_opportunities(self) -> List[Opportunity]:
        """
        每天扫描全市场，发现新机会
        
        流程：
        1. 扫描全市场版块 (每个版块)
        2. 检测是否有异动信号
        3. 过滤已持仓和已观察的版块
        4. 生成新机会并推送用户审阅
        """
        
        opportunities = []
        
        # 获取全市场版块列表
        all_sectors = await self._get_all_sectors()
        
        # 持仓和已观察版块（跳过）
        skip_sectors = await self._get_skip_list()
        
        for sector in all_sectors:
            if sector.code in skip_sectors:
                continue
            
            # 检测异动
            anomaly = await self._detect_anomaly(sector)
            if not anomaly:
                continue
            
            # 生成权威信号
            signal = await self._generate_signal(sector, anomaly)
            
            # 只推荐STRONG信号的新机会
            if signal.confidence < 0.7:
                continue
            
            # 生成机会对象（待用户审阅）
            opportunity = Opportunity(
                sector=sector,
                signal=signal,
                discovery_time=datetime.now(),
                status="PENDING_REVIEW",  # 等待用户审阅
                auto_approved=False,
            )
            
            opportunities.append(opportunity)
        
        return opportunities
    
    async def present_opportunity_for_review(self, opp: Opportunity) -> None:
        """
        将机会呈现给用户审阅
        
        用户可以：
        1. ✅ 同意 → 加入观察列表（第二级）
        2. ⏸️  稍候 → 保留审阅中状态
        3. ❌ 拒绝 → 加入黑名单或第三级
        """
        
        card = {
            "title": f"🎯 发现新机会：{opp.sector.name}",
            "score": f"{opp.signal.confidence:.0%}",
            "reasons": opp.signal.reasoning,
            "data": opp.signal.data_sources,
            "actions": [
                {"text": "✅ 加入观察", "action": "add_to_watch"},
                {"text": "⏸️  稍候", "action": "pending"},
                {"text": "❌ 不感兴趣", "action": "reject"},
            ],
        }
        
        await self._send_feishu_card(card)
```

---

## 系统交互流程图

```
【早上6:00】系统启动
    ↓
【盘前】加载持仓和观察列表
    ↓
【9:30-15:00】实时监控
    ├─ 监控持仓版块 (第一级)
    │   ↓
    │ 检测异动 → 生成信号 → 立即推送
    │
    ├─ 定时扫描全市场 (第二级)
    │   ↓
    │ 发现新机会 → 呈现审阅 → 等待用户确认
    │
    └─ 定时评估观察版块 (第二级)
        ↓
        信号形成 → 升级为买入建议
    
【收盘后】生成当日总结
    ├─ 当日买卖建议总结
    ├─ 新发现的机会列表（待审阅）
    └─ 观察列表状态更新

【夜间】更新数据，准备明天

【用户操作】
    当看到新机会时：
    ├─ 审阅理由
    ├─ 决定是否加入观察
    ├─ 如果加入，移入第二级
    └─ 下次该版块有信号时会主动提醒

    当观察版块形成买入信号时：
    ├─ 收到买入建议
    ├─ 可以追加或者转出观察
    └─ 系统追踪这笔交易
```

---

## 功能模块拆分

```
Backend 架构：

┌────────────────────────────────────────────────────┐
│              数据实时流处理层                      │
│  (Stream Processor)                               │
│  - WebSocket 接收行情                             │
│  - 实时计算各类指标                               │
└────────────────────────────────────────────────────┘
                      ↓
┌────────────────────────────────────────────────────┐
│              异动检测引擎                          │
│  (Anomaly Detector)                              │
│  - 价格异动检测                                   │
│  - 资金异动检测                                   │
│  - 量能异动检测                                   │
│  - 综合异动检测                                   │
└────────────────────────────────────────────────────┘
                      ↓
┌────────────────────────────────────────────────────┐
│              权威信号生成                          │
│  (Authority Signal Engine)                       │
│  - 多源数据融合                                   │
│  - 逻辑链构建                                     │
│  - 历史验证                                       │
│  - 风险提示                                       │
└────────────────────────────────────────────────────┘
                      ↓
┌──────────────┬───────────────┬──────────────────┐
│              │               │                  │
↓              ↓               ↓                  ↓
持仓监控     当日建议      新机会发现      观察列表管理
(Portfolio   (Daily         (Opportunity   (Watch List
 Monitor)    Advice)        Discovery)     Manager)
```

---

## 前端交互设计

### 主界面布局
```
┌─────────────────────────────────────────────────────┐
│ 📊 版块监控与决策系统                              │
├─────────────────────────────────────────────────────┤
│                                                      │
│ 【持仓监控】(第一级 - 优先级最高)                  │
│ ┌──────────────────────────────────────────────────┐
│ │ 半导体  ↑ +3.2% | 🔴异动 NEW!                    │
│ │ 建议: 追加20% 目标价 3.74 止损 2.93               │
│ │                                                  │
│ │ 光模块  ↑ +2.8% | 📈 正常监控                    │
│ │ 建议: 继续持有 目标价 4.20                        │
│ └──────────────────────────────────────────────────┘
│
│ 【当日建议】
│ ┌──────────────────────────────────────────────────┐
│ │ ✅ BUY  半导体 - 黄金买点 (73%成功率)            │
│ │ ✅ HOLD 光模块 - 趋势确认，继续持有              │
│ │ ⚠️  WATCH 有色金属 - 信号不确定                  │
│ └──────────────────────────────────────────────────┘
│
│ 【观察列表】(第二级 - 待审阅)
│ ┌──────────────────────────────────────────────────┐
│ │ 🎯 新机会：医药生物                              │
│ │    信号强度：68% | 理由：放量突破...              │
│ │    操作：[✅加入观察] [⏸️稍候] [❌不感兴趣]      │
│ │                                                  │
│ │ 📌 已观察：人工智能                              │
│ │    信号强度：45% | 状态：等待机会                │
│ └──────────────────────────────────────────────────┘
│
│ 【风险预警】
│ ┌──────────────────────────────────────────────────┐
│ │ 🔴 CRITICAL 港股互联网 - 连续跌破支撑位           │
│ │ 🟡 WARNING 电池版块 - 资金流出加速               │
│ └──────────────────────────────────────────────────┘
│
└─────────────────────────────────────────────────────┘
```

### 机会审阅卡片
```
┌────────────────────────────────────┐
│ 🎯 新机会审阅                      │
├────────────────────────────────────┤
│                                    │
│ 版块：医药生物                     │
│ 信号强度：68% ★★★★★              │
│ 发现时间：今天 14:35               │
│                                    │
│ 📊 为什么推荐？                    │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│ 1. 技术面：突破50日线，放量确认     │
│ 2. 资金面：主力净流入 5.2亿         │
│ 3. 热度面：成交放大1.5倍            │
│ 4. 持仓面：7/10主要成分股上涨       │
│ 5. 基本面：新药获批利好             │
│                                    │
│ 📈 历史成功率                      │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│ 类似信号：18/25 成功率 72%         │
│ 平均涨幅：+7.2%                    │
│ 平均周期：5-8天                    │
│                                    │
│ ⚠️  风险提示                       │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│ - 政策风险：新药审批存在不确定性     │
│ - 技术风险：如果跌破50日线则确认转弱 │
│                                    │
│ [✅加入观察] [⏸️  稍候] [❌不感兴趣] │
│                                    │
└────────────────────────────────────┘
```

---

## 实现优先级

### Phase 1 (Week 1-2): 核心监控
```
□ 实时数据流接收 (WebSocket)
□ 基础异动检测 (价格/资金/量能)
□ 持仓版块监控仪表板
```

### Phase 2 (Week 3-4): 信号与建议
```
□ 权威信号生成引擎
□ 当日建议生成
□ 风险预警系统
```

### Phase 3 (Week 5): 新机会
```
□ 全市场扫描引擎
□ 新机会发现与呈现
□ 用户审阅流程
```

### Phase 4 (Week 6): 观察列表管理
```
□ 分级观察列表系统
□ 自动状态更新
□ 持仓转出时的合并逻辑
```

---

## 核心差异点 vs 旧系统

| 方面 | 旧系统 | 新系统 |
|------|-------|-------|
| **监控对象** | 全市场所有版块 | 持仓 + 观察 + 忽略 |
| **监控频率** | 离线分析 | 实时（分钟级） |
| **决策时机** | 事后分析 | 实时异动触发 |
| **建议有效期** | 长期 | 当日有效 |
| **信号来源** | 单一数据源 | 多源融合 |
| **权威性** | 历史回测 | 多维逻辑链 + 历史验证 |
| **用户参与** | 被动接收 | 主动审阅决策 |
| **新机会** | 推荐清单 | 待审批列表 |

---

## 成功指标

```
✅ 实时性：异动→推送 < 30秒
✅ 准确性：当日建议成功率 > 75%
✅ 权威性：每个信号都有清晰理由链
✅ 用户体验：新机会审阅 < 5秒理解
✅ 决策支持：当日有明确的买卖建议
```

---

**这就是真正的"实时监控 + 当日决策系统"**

不再是"分析工具"，而是"交易助手"。

