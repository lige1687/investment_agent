# 🏗️ 模块化系统架构：功能接口 + 可插拔Skill

## 核心架构理念

```
┌──────────────────────────────────────────────────┐
│           用户交互层 (Chat/UI)                   │
│    "给我分析半导体板块" / "推荐相关基金"        │
└─────────────┬──────────────────────────────────┘
              │
┌─────────────▼──────────────────────────────────┐
│         功能接口层 (Function Interface)         │
│  ├─ 获取实时行情()                             │
│  ├─ 分析宏观环境()                             │
│  ├─ 查询事件新闻()                             │
│  ├─ 分析财务质量()                             │
│  ├─ 筛选投资标的()                             │
│  └─ 生成决策建议()                             │
│                                                 │
│  【关键】这层是稳定的，skill后续可随意替换     │
└─────────────┬──────────────────────────────────┘
              │
┌─────────────▼──────────────────────────────────┐
│      Skill适配层 (Skill Adapter/Abstraction)    │
│                                                 │
│  根据功能类型，自动选择对应skill                │
│  ├─ 需要"实时行情" → 用"行情数据查询"         │
│  ├─ 需要"宏观数据" → 用"宏观数据查询"         │
│  ├─ 需要"筛选基金" → 用"问财选基金"           │
│  └─ ...如果skill不可用，自动切换到备选         │
│                                                 │
│  【灵活】不同skill都通过同一个interface        │
└─────────────┬──────────────────────────────────┘
              │
┌─────────────▼──────────────────────────────────┐
│      Skill实现层 (Pluggable Skills)             │
│                                                 │
│  具体的31个skill                               │
│  ├─ 行情数据查询 (当前用的)                    │
│  ├─ finance-data-fetcher (可选)                │
│  ├─ 问财选基金 (当前用的)                      │
│  ├─ hithink-fund-selector (可选)               │
│  └─ ...其他skill                               │
│                                                 │
│  【可替换】只要实现接口，可随时切换             │
└──────────────────────────────────────────────────┘
```

---

## Step 1: Skill分类（31个技能）

### 🔴 第1类：实时行情数据 (4个skill)
**功能定位**：获取实时的市场行情、价格、涨跌幅、成交量等

```
技能清单：
├─ 行情数据查询 ⭐ (当前)
├─ 指数数据查询
├─ finance-radar (备选)
└─ finance-lite (备选)

标准接口（Interface）：
class RealtimeDataProvider {
    async getMarketData(target, metrics) {
        // 输入：target="半导体", metrics=["price", "change", "volume"]
        // 输出：{price: 100, change: 2.5, volume: 1000万}
    }
    
    async getTickerData(ticker) {
        // 输入：ticker="688981" (中芯国际)
        // 输出：{price, change, pe, pb, ...}
    }
    
    async getSectorStrength(sector) {
        // 输入：sector="半导体"
        // 输出：{score: 7.4, trend: "up", strength: "STRONG"}
    }
}

配置：
{
    "provider": "行情数据查询",  // 可改为其他skill
    "fallback": ["finance-radar", "finance-lite"]
}
```

### 🟠 第2类：财务基本面数据 (5个skill)
**功能定位**：财报、估值、盈利能力、增长指标

```
技能清单：
├─ 财务数据查询 ⭐ (当前)
├─ 公司经营数据查询
├─ 公司股东股本查询
├─ 基本资料查询
└─ finance-analysis (备选)

标准接口：
class FinancialDataProvider {
    async getFinancialReport(ticker, period) {
        // 输入：ticker="688981", period="2024Q1"
        // 输出：{revenue, profit, roe, eps, ...}
    }
    
    async getOperatingMetrics(ticker) {
        // 输入：ticker或sector
        // 输出：{gross_margin, net_margin, growth_rate, ...}
    }
    
    async getValuationMetrics(ticker) {
        // 输入：ticker
        // 输出：{pe_ratio, pb_ratio, ps_ratio, percentile, ...}
    }
    
    async analyzeFinancialHealth(ticker) {
        // 输入：ticker
        // 输出：{quality_score, risk_level, sustainability, ...}
    }
}

配置：
{
    "provider": "财务数据查询",
    "fallback": ["finance-analysis", "valuation-analysis"]
}
```

### 🟡 第3类：宏观背景数据 (3个skill)
**功能定位**：经济数据、政策背景、市场情绪

```
技能清单：
├─ 宏观数据查询 ⭐ (当前)
├─ 事件数据查询
└─ finance-lite (备选)

标准接口：
class MacroDataProvider {
    async getMacroIndicators() {
        // 输出：{gdp, interest_rate, inflation, liquidity, ...}
    }
    
    async getMarketSentiment() {
        // 输出：{sentiment: "BULLISH", confidence: 0.75, trend: "up"}
    }
    
    async getRiskLevel() {
        // 输出：{risk_level: "MEDIUM", factors: [...]}
    }
    
    async getImportantEvents(sector) {
        // 输入：sector="半导体"
        // 输出：[{title, date, impact, sentiment}, ...]
    }
}

配置：
{
    "provider": "宏观数据查询",
    "fallback": ["事件数据查询", "finance-lite"]
}
```

### 🟢 第4类：新闻和舆情分析 (3个skill)
**功能定位**：新闻搜索、舆情分析、事件跟踪

```
技能清单：
├─ 新闻搜索 ⭐ (当前)
├─ 事件数据查询
└─ finance-news-pro (备选)

标准接口：
class NewsAndEventProvider {
    async searchNews(query, timeRange) {
        // 输入：query="半导体政策", timeRange="last_24h"
        // 输出：[{title, source, date, url, summary}, ...]
    }
    
    async analyzeSentiment(target) {
        // 输入：target="半导体"
        // 输出：{sentiment: "POSITIVE", score: 0.75, reason: "..."}
    }
    
    async getKeyEvents(sector, timeRange) {
        // 输入：sector="半导体", timeRange="this_week"
        // 输出：[{type, title, impact, importance}, ...]
    }
    
    async trackTrending() {
        // 输出：今日热搜话题
    }
}

配置：
{
    "provider": "新闻搜索",
    "fallback": ["事件数据查询", "finance-news-pro"]
}
```

### 🔵 第5类：机构观点和评级 (2个skill)
**功能定位**：机构评级、研究报告、专家观点

```
技能清单：
├─ 机构研究与评级查询 ⭐ (当前)
└─ ai-invest-masters (备选)

标准接口：
class InstitutionalViewProvider {
    async getInstitutionalRating(target) {
        // 输入：target="688981" 或 sector="半导体"
        // 输出：{buy_ratio: 0.75, rating: "BUY", target_price: 150}
    }
    
    async getResearchReports(target, count) {
        // 输入：target, count=5
        // 输出：[{analyst, report_date, rating, price_target}, ...]
    }
    
    async getExpertConsensus(target) {
        // 输入：target
        // 输出：{consensus: "STRONG_BUY", strength: 0.8, risk: 0.3}
    }
}

配置：
{
    "provider": "机构研究与评级查询",
    "fallback": ["ai-invest-masters"]
}
```

### 🟣 第6类：筛选和推荐 (9个skill)
**功能定位**：按条件筛选投资标的、推荐最佳选择

```
技能清单：
├─ 问财选A股 ⭐
├─ 问财选基金 ⭐
├─ 问财选ETF ⭐
├─ 问财选板块 ⭐
├─ 问财选港股
├─ 问财选美股
├─ 问财选基金经理
├─ 问财选基金公司
├─ 问财选可转债
└─ stock-coach (备选)

标准接口：
class TargetSelectorProvider {
    async selectStocks(conditions, limit=10) {
        // 输入：conditions={sector:"半导体", pe_max:30, roe_min:15}
        // 输出：[{code, name, score, reason}, ...]
    }
    
    async selectFunds(conditions, limit=10) {
        // 输入：conditions={holding_ratio:">20%", performance:">20%"}
        // 输出：[{code, name, score, tracking_error, fee}, ...]
    }
    
    async selectETFs(conditions, limit=10) {
        // 输入：conditions={index:"半导体", liquidity:">1亿"}
        // 输出：[{code, name, aum, spread, liquidity}, ...]
    }
    
    async getSectorOpportunities() {
        // 输出：当前值得关注的所有板块
    }
}

配置：
{
    "stock_selector": "问财选A股",
    "fund_selector": "问财选基金",
    "etf_selector": "问财选ETF",
    "sector_selector": "问财选板块",
    "fallback": "stock-coach"
}
```

### ⚫ 第7类：通用工具 (5个skill)
**功能定位**：数据总结、内容分析、辅助工具

```
技能清单：
├─ summarize (内容总结)
├─ stock-analysis (股票分析)
├─ baidu-search (搜索)
├─ agent-reach (网络爬取)
└─ bb-browser (自动化浏览)

标准接口：
class UtilityProvider {
    async summarizeContent(content, style) {
        // 生成摘要
    }
    
    async analyzeStock(ticker, depth) {
        // 深度分析某只股票
    }
    
    async search(query) {
        // 搜索相关信息
    }
}

配置：
{
    "summarizer": "summarize",
    "analyzer": "stock-analysis"
}
```

---

## Step 2: 功能接口设计

### 核心功能模块及其接口

```python
# ============================================
# 功能模块1：实时行情监控
# ============================================
class RealtimeMarketMonitor:
    """实时监控版块和标的的行情"""
    
    async def get_sector_strength(self, sector_code):
        """获取版块强弱度"""
        # 调用：RealtimeDataProvider.getSectorStrength()
        # 返回：{score, trend, strength, change, volume}
        pass
    
    async def detect_anomaly(self, sector_code):
        """检测异动"""
        # 调用：RealtimeDataProvider.getMarketData()
        # 返回：{anomaly_detected, type, severity, confidence}
        pass
    
    async def track_ticker(self, ticker):
        """实时追踪单只标的"""
        # 返回：{price, change, pe, pb, momentum}
        pass


# ============================================
# 功能模块2：基本面分析
# ============================================
class FundamentalAnalyzer:
    """分析标的的财务质量和基本面"""
    
    async def analyze_financial_health(self, ticker):
        """财务质量评分"""
        # 调用：FinancialDataProvider
        # 返回：{score, quality, risks, highlights}
        pass
    
    async def get_valuation(self, ticker):
        """估值分析"""
        # 返回：{pe_ratio, pb_ratio, percentile, conclusion}
        pass
    
    async def get_growth_trend(self, ticker):
        """增长趋势分析"""
        # 返回：{revenue_growth, profit_growth, sustainability}
        pass


# ============================================
# 功能模块3：宏观环境分析
# ============================================
class MacroEnvironmentAnalyzer:
    """分析宏观经济背景"""
    
    async def get_environment_score(self):
        """当前市场环境友好度打分"""
        # 调用：MacroDataProvider.getMacroIndicators()
        # 返回：{score, liquidity, sentiment, risk_level}
        pass
    
    async def should_trade_now(self):
        """现在是否适合操作"""
        # 返回：{yes_or_no, reason, confidence}
        pass
    
    async def get_risk_warning(self):
        """风险预警"""
        # 返回：[{risk, level, description}]
        pass


# ============================================
# 功能模块4：新闻和事件分析
# ============================================
class NewsAndEventAnalyzer:
    """分析新闻和事件对投资的影响"""
    
    async def get_relevant_news(self, target, timeframe):
        """获取相关新闻"""
        # 调用：NewsAndEventProvider
        # 返回：[{title, date, sentiment, impact}]
        pass
    
    async def analyze_news_impact(self, target):
        """分析新闻的投资影响"""
        # 返回：{sentiment, impact_level, key_points}
        pass
    
    async def get_key_events(self, sector):
        """获取关键事件"""
        # 返回：[{event, date, impact, importance}]
        pass


# ============================================
# 功能模块5：投资选择推荐
# ============================================
class InvestmentSelector:
    """推荐具体的投资标的"""
    
    async def recommend_stocks(self, sector, conditions=None, count=5):
        """推荐相关个股"""
        # 调用：TargetSelectorProvider.selectStocks()
        # 返回：[{code, name, score, reason}]
        pass
    
    async def recommend_funds(self, sector, conditions=None, count=5):
        """推荐相关基金"""
        # 调用：TargetSelectorProvider.selectFunds()
        # 返回：[{code, name, score}]
        pass
    
    async def recommend_etfs(self, sector, conditions=None, count=5):
        """推荐相关ETF"""
        # 调用：TargetSelectorProvider.selectETFs()
        # 返回：[{code, name, aum, spread}]
        pass
    
    async def find_opportunities(self):
        """发现投资机会"""
        # 调用：TargetSelectorProvider.getSectorOpportunities()
        # 返回：[{sector, opportunity_score, reason}]
        pass


# ============================================
# 功能模块6：机构观点参考
# ============================================
class InstitutionalViewReference:
    """参考机构观点和评级"""
    
    async def get_consensus(self, target):
        """获取机构共识"""
        # 调用：InstitutionalViewProvider
        # 返回：{consensus, buy_ratio, rating, price_target}
        pass
    
    async def get_expert_opinions(self, target):
        """获取专家意见"""
        # 返回：[{analyst, rating, price_target}]
        pass


# ============================================
# 功能模块7：综合决策建议
# ============================================
class ComprehensiveAdviceGenerator:
    """综合所有分析生成权威建议"""
    
    async def generate_decision_advice(self, sector, anomaly_info):
        """生成决策建议"""
        # 综合调用上面6个模块
        # 生成最终建议
        # 返回：{
        #   rating: "⭐⭐⭐⭐⭐",
        #   recommendation: "STRONG_BUY",
        #   reasons: [...],
        #   options: [
        #     {type: "stock", targets: [...], position: "30-40%"},
        #     {type: "fund", targets: [...], position: "40-50%"},
        #     {type: "etf", targets: [...], position: "20-30%"}
        #   ],
        #   risks: [...],
        #   monitoring_points: [...]
        # }
        pass
    
    async def generate_daily_briefing(self):
        """生成每日策略摘要"""
        # 综合当日所有数据
        # 返回一份完整的每日策略简报
        pass
```

---

## Step 3: 系统架构层级

```
┌─────────────────────────────────────────────────────────┐
│                     用户交互层                         │
│                                                         │
│  用户在聊天中触发功能：                                 │
│  "给我分析一下半导体"                                 │
│  "推荐相关的基金"                                     │
│  "现在适合买入吗"                                     │
│  "半导体发生了什么"                                   │
└────────────────┬────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────┐
│                  功能层（7个核心模块）                  │
│                                                         │
│  1. RealtimeMarketMonitor      实时行情监控             │
│  2. FundamentalAnalyzer        基本面分析               │
│  3. MacroEnvironmentAnalyzer   宏观分析                 │
│  4. NewsAndEventAnalyzer       新闻事件分析             │
│  5. InvestmentSelector         投资选择                 │
│  6. InstitutionalViewReference 机构观点                 │
│  7. ComprehensiveAdviceGenerator 综合建议               │
│                                                         │
│  ←→ 这7个模块之间可以互相调用                          │
└────────────────┬────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────┐
│             Skill适配层（Data Providers）              │
│                                                         │
│  1. RealtimeDataProvider       实时行情数据             │
│  2. FinancialDataProvider      财务数据                 │
│  3. MacroDataProvider          宏观数据                 │
│  4. NewsAndEventProvider       新闻事件                 │
│  5. InstitutionalViewProvider  机构观点                 │
│  6. TargetSelectorProvider     投资筛选                 │
│  7. UtilityProvider            通用工具                 │
│                                                         │
│  【关键特性】每个Provider都有fallback机制               │
│  如果当前skill不可用，自动切换到备选skill             │
└────────────────┬────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────┐
│            Skill实现层（31个可插拔Skill）              │
│                                                         │
│  行情类：行情数据查询、finance-lite、finance-radar      │
│  财务类：财务数据查询、finance-analysis、valuation...  │
│  宏观类：宏观数据查询、事件数据查询                    │
│  新闻类：新闻搜索、finance-news-pro                    │
│  评级类：机构研究与评级查询、ai-invest-masters         │
│  筛选类：问财选* 系列 (9个)、stock-coach              │
│  工具类：summarize、stock-analysis、baidu-search       │
└─────────────────────────────────────────────────────────┘
```

---

## Step 4: 系统配置文件

```yaml
# system_config.yaml

# 实时行情数据源配置
realtime_data:
  primary: "行情数据查询"
  fallback:
    - "finance-lite"
    - "finance-radar"
  cache_ttl: 5  # 分钟

# 财务数据源配置
financial_data:
  primary: "财务数据查询"
  fallback:
    - "finance-analysis"
    - "valuation-analysis"
  cache_ttl: 1440  # 天

# 宏观数据源配置
macro_data:
  primary: "宏观数据查询"
  fallback:
    - "事件数据查询"
    - "finance-lite"
  cache_ttl: 1440

# 新闻和事件源配置
news_event:
  primary: "新闻搜索"
  fallback:
    - "事件数据查询"
    - "finance-news-pro"
  cache_ttl: 60

# 机构观点源配置
institutional_view:
  primary: "机构研究与评级查询"
  fallback:
    - "ai-invest-masters"
  cache_ttl: 1440

# 投资选择源配置
investment_selector:
  stock:
    primary: "问财选A股"
    fallback: ["stock-coach"]
  fund:
    primary: "问财选基金"
    fallback: ["hithink-fund-selector"]
  etf:
    primary: "问财选ETF"
  sector:
    primary: "问财选板块"

# 工具源配置
utilities:
  summarizer: "summarize"
  analyzer: "stock-analysis"
  searcher: "baidu-search"
  browser: "bb-browser"
```

---

## Step 5: 开发优先级

### Phase 1：基础架构（Week 1）
```
□ 定义7个功能模块的Interface
□ 设计6个DataProvider的adapter
□ 实现Skill的fallback机制
□ 编写配置文件解析器

优先级：高
依赖：无
难度：中等
```

### Phase 2：核心模块实现（Week 2-3）
```
□ 实现RealtimeMarketMonitor
  └─ 依赖：RealtimeDataProvider
  └─ 功能：异动检测、版块监控

□ 实现FundamentalAnalyzer
  └─ 依赖：FinancialDataProvider
  └─ 功能：财务分析、估值分析

□ 实现MacroEnvironmentAnalyzer
  └─ 依赖：MacroDataProvider
  └─ 功能：宏观分析、风险评估

优先级：高
难度：中等
```

### Phase 3：中层模块（Week 3-4）
```
□ 实现NewsAndEventAnalyzer
□ 实现InvestmentSelector
□ 实现InstitutionalViewReference

优先级：中
难度：中等
```

### Phase 4：综合层（Week 4-5）
```
□ 实现ComprehensiveAdviceGenerator
  └─ 综合前面6个模块
  └─ 生成最终权威建议

优先级：高
难度：高
```

### Phase 5：前端和集成（Week 5-6）
```
□ 设计聊天interface
□ 实现自动触发机制
□ 集成所有模块

优先级：高
难度：中等
```

---

## Step 6: 使用示例

### 场景1：用户询问"半导体怎么样"

```python
# 聊天中用户说：
# "给我分析一下半导体版块，现在适合买吗？"

# 系统自动触发：
async def handle_user_query(query):
    # Step 1: 识别用户意图 → 分析半导体
    sector = "semiconductor"
    
    # Step 2: 调用功能模块
    
    # 2a. 获取实时行情
    realtime_monitor = RealtimeMarketMonitor()
    sector_strength = await realtime_monitor.get_sector_strength(sector)
    
    # 2b. 分析基本面
    fundamental_analyzer = FundamentalAnalyzer()
    financial_health = await fundamental_analyzer.analyze_financial_health(sector)
    
    # 2c. 分析宏观环境
    macro_analyzer = MacroEnvironmentAnalyzer()
    env_score = await macro_analyzer.get_environment_score()
    should_trade = await macro_analyzer.should_trade_now()
    
    # 2d. 分析新闻
    news_analyzer = NewsAndEventAnalyzer()
    relevant_news = await news_analyzer.get_relevant_news(sector, "last_24h")
    
    # 2e. 机构观点
    institutional_view = InstitutionalViewReference()
    consensus = await institutional_view.get_consensus(sector)
    
    # Step 3: 综合生成建议
    advice_generator = ComprehensiveAdviceGenerator()
    final_advice = await advice_generator.generate_decision_advice(sector, {
        'sector_strength': sector_strength,
        'financial': financial_health,
        'macro': env_score,
        'news': relevant_news,
        'institutional': consensus
    })
    
    # Step 4: 返回给用户
    return format_response(final_advice)
    
# 用户收到回应：
# "📊 半导体版块分析
# 【实时行情】强势上升（+2.5%）
# 【基本面】财报质量优秀（8.5/10）
# 【宏观环境】适合操作（环境评分8.2/10）
# 【新闻背景】政策支持，市场情绪积极
# 【机构观点】普遍看好（75%买入）
# 
# 综合评分：⭐⭐⭐⭐⭐ 强烈推荐
# 
# 【推荐方案】
# 方案A：买龙头个股（中芯国际等）
# 方案B：买相关基金（006503等）
# 方案C：买行业ETF（512480等）"
```

### 场景2：用户问"推荐个基金"

```python
# 聊天中用户说：
# "帮我推荐个半导体相关的基金"

async def handle_fund_recommendation(query):
    # Step 1: 识别意图
    sector = extract_sector(query)  # "semiconductor"
    
    # Step 2: 调用投资选择模块
    selector = InvestmentSelector()
    funds = await selector.recommend_funds(
        sector=sector,
        conditions={'min_1y_performance': 15},
        count=5
    )
    
    # Step 3: 返回结果
    return format_funds_response(funds)
    
# 用户收到：
# "✨ 半导体相关基金推荐
# 
# 🏆 TOP 1: 006503 财通集成电路
#   收益率：+28.5% | 费率：0.75% | 相关性：0.95
#   理由：高度聚焦半导体，表现突出
#
# 🥈 TOP 2: 001513 易方达信息产业
#   收益率：+22.3% | 费率：0.60% | 相关性：0.88
#   理由：板块覆盖广，风险适中
#
# 🥉 TOP 3: 159928 南方科技创新
#   收益率：+18.9% | 费率：0.48% | 相关性：0.82
#   理由：ETF结构，成本最低"
```

### 场景3：后续Skill切换

```python
# 如果"问财选基金"一时不可用
# 系统自动切换到备选方案

# 配置中改一行：
system_config.yaml:
  investment_selector:
    fund:
      primary: "hithink-fund-selector"  # 改成备选
      fallback: ["问财选基金"]  # 原来的变成备选

# 代码无需任何改动，因为都通过interface调用
# TargetSelectorProvider会自动选择可用的skill
selector = TargetSelectorProvider.get_fund_selector()
funds = await selector.selectFunds(...)  # 自动用hithink-fund-selector
```

---

## 总结

这个架构的优势：

```
✅ 功能接口稳定
   - 用户不感知Skill的变化
   - 开发时只需实现功能逻辑

✅ Skill灵活可插拔
   - 改一行配置文件就能切换Skill
   - 自动fallback机制保证可用性
   - 不用改代码

✅ 模块清晰解耦
   - 7个功能模块各自独立
   - 可以并行开发
   - 后续易于扩展

✅ 自动化触发
   - 聊天中自动识别意图
   - 自动调用对应功能
   - 用户体验顺畅

✅ 便于测试和优化
   - 每个模块都可单独测试
   - 每个DataProvider都有fallback
   - 系统鲁棒性强
```

---

## 下一步

要开始开发吗？建议的流程：

1. **确认架构** - 你觉得这个分层是否合理？
2. **选择起点** - 从哪个模块开始开发？(建议从Module 1开始)
3. **开始编码** - 实现第一个功能模块的接口和逻辑

你想要我立即开始哪一步？🚀

