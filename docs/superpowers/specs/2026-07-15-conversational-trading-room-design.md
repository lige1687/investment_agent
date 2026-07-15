# 讨论室对话式改造设计（问答式多专家 + 快捷功能）

日期：2026-07-15
状态：已与用户逐段确认
分支：`agent/p0-data-trust`（延续）

## 1. 背景与问题

现有"今日交易讨论室"是**一键批处理**：点击"开始今日讨论"→ 6 个专家全量跑一遍 → 输出结构化结论。实际使用中的问题：

1. **不可用感强**：申赎预检大量 UNKNOWN/LIMITED/SUSPENDED、`peak_equity` 永远为 null、市场指数低置信、组合数据 stale——严格 fail-closed 导致几乎每个专家都输出"关键数据缺失，无法评估"。
2. **形态不对**：用户想要的是**问答**——"我问一个问题，专家们围绕它讨论"，而不是每次全量生成一份体检报告。
3. **缺少常用功能入口**：今日操作建议、机会发现等高频诉求没有一键入口。

## 2. 用户确认的需求决策

| 决策点 | 结论 |
|---|---|
| 产品形态 | 讨论室改成**对话式**，与"AI 投资助手"页**并存**（后者不动） |
| 专家参与 | **智能路由**：按问题类型按需召唤专家，非每次全员 |
| 快捷功能 | 首批 4 个：今日操作建议 / 机会发现 / 风险扫描 / 市场解读 |
| 数据缺失表现 | **分析照常给**（基于现有数据给定性分析+置信度声明），只有涉及执行才拦 |
| 呈现方式 | 专家发言**逐条冒出**（群聊感） |
| 执行闭环 | **不做**现金确认/护栏金额/采纳记录链路；真实仓位以养基宝同步为准 |
| 回撤数据 | 养基宝**每次同步自动记持仓市值快照**，`peak` 从同步历史计算，不再依赖用户手动确认 |
| 金额建议 | 给**建议区间**；金额策略留**可插拔嵌入点**（用户个人策略逐步沉淀），v1 用目标仓位缺口算法 |
| 基金指代 | 用户**只说中文名不说代码**（"信息产业那只"），路由层负责名称→代码解析，歧义时反问 |
| Skill 原则 | 专家只用用户自己积累的真实 skill（白名单+SHA-256 锁定），不新造 |
| 分工 | Claude 负责规划/设计/文档/review；实现由 subagent 执行 |

## 3. 方案选型（已确认：方案 A）

**方案 A（选定）**：在 `trading_room/` 内新增**对话编排层**，与批处理编排器平级。复用 `SpecialistRunner`、角色 schema/prompt、`TradingContextSnapshot`、会话存储。

放弃的备选：
- 方案 B（扩展 InvestmentAgent、专家变工具）：路由不可控、专家结论被转述失真、token 高、无真群聊感。
- 方案 C（批处理加追问框）：不符合"问答优先"的核心诉求。

选 A 的理由：系统灵魂是"专家各司其职 + 确定性边界 + 证据可溯"，只有 A 能在对话形态下保住这三点。

## 4. 后端架构

### 4.1 新增模块

```
backend/app/trading_room/
├── orchestrator.py          # 现有批处理编排器（不动）
├── conversation/            # 【新增】
│   ├── orchestrator.py      # ConversationOrchestrator：路由 → 并行专家 → 主席综合
│   ├── router.py            # 问题路由 + 基金名称解析（一次轻量 LLM 调用）
│   ├── presets.py           # 4 个快捷功能：预设问题 + 固定路由（跳过 LLM 路由）
│   └── store.py             # 对话消息持久化（扩展现有表）
└── amount_strategy.py       # 【新增】金额策略嵌入点
```

### 4.2 一次提问的数据流

```
用户发问 "信息产业那只要不要减点?"
  │
  ├─ POST /trading-room/conversations/{id}/ask  → 立即返回 turn_id
  │   后台任务（FastAPI BackgroundTasks）：
  │   1. Router（LLM）：解析基金名→代码、选参与专家
  │      → 写 system 消息（kind=routing）："本次参与：卖出保护、组合风险；已解析：易方达信息产业混合A(001513)"
  │      → 歧义时写 clarification 消息反问并终止本回合
  │   2. 构建 TradingContextSnapshot（复用现有，含置信度标注）
  │   3. 并行跑选中 specialist（asyncio.gather，复用 SpecialistRunner）
  │      每个完成 → 立即落一条该角色发言消息（kind=specialist_memo）
  │   4. AmountStrategy（纯计算）算建议区间（若本回合有买/卖动作候选）
  │   5. Chair（LLM）综合全部发言 + 硬区间 → 最终回答（kind=chair_summary）
  │
  └─ 前端 1.5s 轮询 GET /conversations/{id}/messages?after=<last_id> → 逐条冒出
```

### 4.3 推送选型：轮询（非 WebSocket）

后端 `app/api/ws/` 目前为空（无现成 WS 实现）。消息本来就要落库（审计），轮询读库零额外成本；1.5s 间隔对专家发言节奏（每条 5-20s）足够。接口形状不依赖轮询，后续可平滑升级 WS/SSE。

### 4.4 Router 设计

一次低温度小输出 LLM 调用，绑定 `batch-trading-router` skill（已在白名单）：

```
输入: 用户问题原文 + 持仓名录 [{code, name}] + 可选 preset_id
输出(结构化):
{
  "resolved_funds": [{"code": "001513", "name": "易方达信息产业混合A", "matched_from": "信息产业那只"}],
  "ambiguities": [],          // 非空 → 不跑专家，先反问
  "participants": ["sell_protection", "portfolio_risk"],
  "reason": "..."
}
```

- 名称解析与路由**合并为一次调用**（持仓名录只有几十行）。
- skeptic 默认不参与单问题讨论，只在"今日操作建议"全面扫描时上场。
- 结构化输出失败重试一次，仍失败 → error 消息，本回合终止（沿用现有专家的失败语义）。

### 4.5 快捷功能与 skill 白名单变化

| 快捷功能 | 固定参与专家 | 白名单变化 |
|---|---|---|
| 今日操作建议 | 全员（并行）：portfolio_risk、market_regime、theme_fund、buy、sell_protection，全部完成后 skeptic 复核 | 无 |
| 机会发现 | market_regime + theme_fund + buy | **新增** `hithink-sector-selector`、`hithink-fund-selector`、`行业轮动分析`（绑 theme_fund，仅机会发现模式加载） |
| 风险扫描 | portfolio_risk 单专家深度 | 无 |
| 市场解读 | market_regime 单专家深度 | 无 |

新增 skill 均为用户已有的真实 skill 包（`~/.openclaw/workspace/skills/` 下），按现有 `APPROVED_SKILLS` 机制收录（路径 + 文件清单 + SHA-256 快照）。

已核查：现有 6 席专家的 skill 绑定全部真实存在且文件齐全（batch-trading-* 8 包、hithink-fund-query、announcement-search、基金分析与筛选/fund-analysis）。

### 4.6 金额策略嵌入点

```python
class AmountStrategy(Protocol):
    def suggest(self, *, action: Literal["buy", "sell"], fund_code, positions,
                target_allocations, holdings_value, score) -> AmountSuggestion | None:
        """返回 {min, max, basis: 计算依据, caveats: [警示]}，无法计算时 None"""

class TargetGapStrategy:  # v1 默认，买卖同源
    """buy: (目标% − 当前%) × 持仓市值，按买入分数分档打折
    sell: (当前% − 目标%) × 持仓市值；无目标仓位时按浮盈比例分档（如浮盈>20% → 1/4仓）"""
```

- **数字永远来自确定性代码**，沿用系统既有原则（buy 席不得换算金额、chair 只能解释结构化结果）。
- Chair 拿硬区间做解释和倾向性表述（"建议靠区间下沿"），**不得编数字或放大区间**（复用 `validate_chair_memo` 的区间校验思路）。
- 用户个人策略（分批节奏、单日上限等）后续以新实现类 + 配置切换沉淀，专家与对话层零改动。
- 现有 `LightTradeGuard` 不进对话流（它管"可执行金额"；对话流只给"建议区间"，caveat 注明"实际可买以支付宝为准"）。

### 4.7 数据缺失的表现（对话模式规则）

专家 prompt 追加对话模式规则：
- 数据缺失/低置信/stale → **照常给定性分析和倾向性意见**，但必须在发言中声明数据状态（如"持仓数据同步于今早 9:31，未含今日盘中变动"）。
- `immediately_executable` 概念在对话流中不存在——没有执行，就没有执行拦截。
- 数据置信度声明由 Chair 汇总内联在最终回答（⚠️ 标注），不再渲染满屏 blocker。

### 4.8 养基宝同步记快照（解决 peak_equity 永远 null）

养基宝每次同步成功后，自动写一条 `account_valuation_snapshots`（holdings_value=同步市值，confidence=HIGH）。`recent_peak` 从同步历史算。现金不计入（基金投资者的回撤以持仓市值衡量更贴近实际）。**用户零操作，数据随使用自然积累。**

## 5. API 面（新增 3 端点）

```
POST /trading-room/conversations                      # 取或建今日会话
POST /trading-room/conversations/{id}/ask             # {text?, preset_id?} → {turn_id}，立即返回
GET  /trading-room/conversations/{id}/messages?after=N  # 轮询增量
```

- `ask`：BackgroundTasks 跑编排；同会话同时只允许一个进行中 turn（409）。
- 现有批处理端点全部保留不动。

## 6. 消息模型

复用 `trading_room_messages` 表，新增两列：

```
turn_id: str        # 一次提问的回合标识
kind:    str        # text | routing | specialist_memo | chair_summary | clarification | error
```

`sender_role`（已有）：user / system / 各专家角色 / chair。结构化内容放现有 `message_json`。
会话复用 `trading_room_sessions`：一天一会话可续聊，**每个 turn 重建上下文快照**（数据不过夜）。

## 7. 前端

`/trading-room` 整页替换为对话式界面（旧批处理组件保留在代码库不删）：

- 顶部：账户概要条（持仓数/市值/同步时间）+ [同步养基宝] [新会话]
- 快捷功能 4 按钮：无消息时显眼居中，有消息后收缩到顶部
- 消息流：用户气泡 / 系统路由气泡（本次参与+名称解析结果）/ 专家发言气泡（图标+一句话观点+▸详情展开完整 memo）/ 主席总结气泡（结论+建议区间+依据+⚠️数据警示）
- 输入框 placeholder 提示可直接说基金名
- demo 数据模式沿用现有 `DemoDataBanner`（信任边界要求不变）
- 轮询：TanStack Query `refetchInterval: 1500`，收到 chair_summary / clarification / error 后停止
- 专家 memo 详情展示改造自现有 `SpecialistRoundtable` 卡片逻辑

## 8. 测试策略

| 层 | 测法 |
|---|---|
| Router | fake LLM 固定输出 → 角色选择 / 名称解析 / 歧义反问三路径 |
| ConversationOrchestrator | fake runners（沿用现有 orchestrator 测试模式）→ 消息落库顺序 routing → memos → chair_summary；单专家失败不阻塞其余 |
| AmountStrategy | 纯函数单测：缺口计算 / 无目标仓位→None / 分数折扣 |
| 养基宝快照 | 同步成功 → `account_valuation_snapshots` 新增、`recent_peak` 可读 |
| API | httpx 全链路：ask → 轮询 messages（fake LLM）；并发 turn 409 |
| 前端 | Vitest：5 种 kind 渲染分支、轮询停止条件、快捷按钮、歧义反问交互 |

## 9. 明确不做（防范围蔓延）

- 现金确认 / 护栏可执行金额 / 采纳记录（accepted/ignored）链路——对话流不接入
- WebSocket / SSE 推送（轮询先行，接口形状兼容后续升级）
- 批处理讨论室页面的删除（代码保留，路由不再默认指向）
- 跨天会话记忆 / 长期对话历史进 prompt（每 turn 快照重建）
- 批次规划（batch-planner）、卖出执行（sell-execution）skill 的接入
- 执行预检（申赎公告查询）在对话流中的自动触发——仅当用户明确问"现在能不能买/申购状态"时由路由派给相应能力（v1 不做，列入后续迭代）

## 10. 依赖与风险

- **DeepSeek 结构化输出稳定性**：Router 输出 schema 较简单，风险低于专家 memo；失败语义沿用现有（重试一次→标不可用）。
- **路由误判**：预设快捷功能不走 LLM 路由（固定路由）兜底高频场景；自由提问误判时用户可追问纠正。
- **响应延迟**：单问题 2-3 专家并行 + router + chair ≈ 3 次串行 LLM 时延（约 30-60s），逐条冒出缓解等待感。
- **消息表膨胀**：单用户系统，量级无虞。
