# 回测引擎两层观察期模型设计（L1 机械触发 + L2 LLM 观察）

日期：2026-07-16
状态：已与用户逐段确认（待 review 后出实施 plan）
分支：`agent/backtest-two-layer-observation`（新建）

## 1. 背景与问题

回测能跑通，但效果远不及预期——"强买点出现了系统却不买"。逐步追踪买/卖执行链路后，定位到根因不是冷静期（`buy_cooldown_until_index` 是死代码，从不被读），而是**策略层写的意图和引擎层执行的逻辑是两套，且引擎静默赢**：

1. **买点观察复查的是错的东西**。`strategy.py:67` 写了"强买信号立即执行、无需观察"，但 `engine.py:217-229` 对所有 `buy_candidate` 硬编码 2 天观察期并 `continue`，**从不调用 `strategy.decide()`**——那条"立即执行"规则是非 test 模式下的死代码。观察期末的 `_detect_buy_confirmation` 复查的是"原信号通过数 + market_regime"，**没有复查"是否站稳均线"**——用户最在意的确认，代码没做。
2. **卖点观察顺序反了**。用户要"放量跌破 15 日均线 -> 观察 2 天确认稳定跌破 -> 再卖"；代码是"跌破当天立即卖 50% -> 之后观察 3 天决定要不要继续卖"（`strategy.py:108` + `_detect_post_sell_observation`）。先卖后确认 vs 先确认后卖，完全相反。
3. **"放量"是硬编码魔法数**。`buy_volume_ratio=1.2` / `breakdown_volume_ratio=1.5` 写死，用户认为该交专业 skill。
4. **5 维 checklist 当触发门槛过严**，且其中"逻辑/催化"维度数据是假的（见 §4）。
5. 配套问题：`weak_buy_allows_trade` / `first_entry_plan_ratio` / `sell_cooldown_days` 被编译器写入但从不读取（死参数）；引擎 1269 行上帝类；执行日志写临时文件返回服务器路径；`strategy_compiler_agent` 绕过 LLM registry 直接打 Anthropic。

本 spec 只锁定**两层观察期模型**（P0，解决买/卖被静默吞掉），其余配套问题列入 §8 分阶段与 §9 不做。

## 2. 用户确认的需求决策

| 决策点 | 结论 |
|---|---|
| 买点触发（L1） | 放量突破 + 站上 15 日均线（机械、确定性）。5 维 checklist **不再当触发门槛**，整体搬到 L2 观察 |
| 买点观察 | 2 天，全权 LLM 调 skill 判 5 维 -> 决定买不买 |
| 卖点触发（L1） | 放量跌破 15 日均线（机械、确定性） |
| 卖点观察 | 2 天，全权 LLM 调 skill 判相关维度 -> 决定卖不卖（**对称**，覆盖此前"当天就卖"的选择） |
| 放量阈值 | skill **一次性**给出本回测的放量倍数（买/卖各一），引擎确定性使用，可复现 |
| MA 口径 | 买/卖统一 15 日 EXPMA（与现有破位检测一致），不再买侧 MA20、卖侧 EXPMA15 两套 |
| "逻辑/催化"维度 | 数据源是假（`prosperity.score` 手填常数）。Phase 0/1 **降权留空**不让假数据进 LLM；Phase 2 接真实数据源（板块景气度/公告/催化剂 skill） |
| LLM 管线 | LLM 走 `get_llm_client(role)`（新增角色 `backtest_observer`）；skill 走 SkillBridge 真调用。顺手修掉 `strategy_compiler_agent` 绕过 registry 的问题 |
| 可复现性 | temperature=0 + 按 (标的+触发日+窗口上下文 hash+skill 版本) 缓存 LLM 判断。首跑慢、重跑免费且一致 |
| 执行时序 | T 日收盘检测 L1 触发 -> T+1..T+2 观察窗口 -> LLM 于 T+2 收盘判断 -> T+3 成交（ETF 用 close 当 NAV，同样 T+3） |
| 分工 | Claude 负责规划/设计/文档/review；实现由 subagent 执行 |

## 3. 方案：两层模型（买/卖对称）

```
                L1 机械触发（确定性）                 L2 观察期（2 天，LLM+skill）
买   放量突破 + 站上 15EXPMA  ──►  LLM 调 skill 判 5 维  ──►  买入（金额按策略）
卖   放量跌破 15EXPMA        ──►  LLM 调 skill 判相关维度 ──►  卖出（比例按策略）
```

- **L1 只回答"有没有出现值得观察的机械事件"**，不给买卖结论。对应 `EventDetector` 拆出来的纯触发扫描。
- **L2 只回答"观察窗口里条件是否成立、要不要动手"**，由 LLM 基于 skill 给的维度数据判断。对应新的观察裁判层。
- 触发与判断分离后，"信号 -> 成交"固定 T+3，但 T+3 内的判断是**有意义的**（LLM 看真实窗口数据），不再是复查错对象。

### 3.1 两遍 + 缓存架构（保可复现）

引擎从单遍同步改为**三遍**，把 LLM 调用隔离成可缓存的独立一遍：

```
Pass 1  TriggerScanner（确定性）
        遍历 bars，按 L1 规则扫出所有触发点：[{type: buy/sell, trigger_date: T}, ...]
        每个触发点定义观察窗口 [T+1, T+2]
        │
Pass 2  ObservationJudge（LLM+skill，缓存）          ← 唯一调 LLM 的地方
        对每个触发窗口：
          - 取窗口内 bars + 快照 + skill 提供的维度数据
          - 调 get_llm_client("backtest_observer")，temperature=0
          - 结构化输出：{decision: buy|sell|hold, dimensions: {...}, reasons: [...]}
          - 缓存键 = (symbol, trigger_date, window_context_hash, skill_versions)
        │
Pass 3  ExecutionReplay（确定性）
        重放引擎，在窗口末日(T+2)读 Pass 2 的缓存判断作为决策，
        T+3 成交。批次记账/费用/指标沿用现有引擎逻辑。
```

- Pass 1、Pass 3 纯确定性，无 LLM，可单测。
- Pass 2 是唯一非确定来源，靠缓存兜成可复现：首次回测跑 LLM 落盘，再次回测命中缓存零调用。
- 引擎测试用 fake judge（不碰 LLM），与现有 `FakeLLMClient` 模式一致。

## 4. 5 维数据真实性检验（用户单独要求）

逐维查 `policy.py` 数据源，决定哪些能交给 LLM、哪些是假数据必须先补：

| 维度 | 现在的数据源 | 真实性 | 处理 |
|---|---|---|---|
| 趋势修复 | signal_bars OHLCV（MA/低点/突破） | ✓ 真实 | 现成，MA 统一成 15EXPMA |
| 量能健康 | bar.volume 量比 | ✓ 真实 | 现成，但"放量阈值"改由 skill 给 |
| 资金回流 | bar.amount 成交额 | △ 弱代理 | 成交额 ≠ 资金流向；真·主力净流入需 skill/数据源，Phase 2 补 |
| 逻辑/催化 | `config.prosperity.score` | ✗ 假 | 手填常数、回测期间不变。Phase 0/1 **降权留空**；Phase 2 接景气度/公告 skill |
| 组合允许 | snapshot + 静态暴露输入 | △ 半真 | 仓位计算真，但单标的无组合、"相关暴露"是静态输入。Phase 2 随多标的支持再补 |

**结论：5 维里 2 真、2 半真、1 假。** Phase 0/1 让 LLM 只判真实可用的维度（趋势修复、量能健康，外加站稳均线这个新确认项），半真/假维度标注数据状态后降权或留空，不让假数据污染判断。

## 5. 后端架构

### 5.1 新增/修改模块

```
backend/app/backtest/
├── engine.py                  # 改：run() 拆成三遍；删 test_mode 对主循环的污染（观察改走 judge）
├── trigger_scanner.py         # 【新增】L1 机械触发扫描（放量+15EXPMA），替代 _detect_buy_candidate 触发部分
├── observation/
│   ├── __init__.py
│   ├── judge.py               # 【新增】ObservationJudge：调 backtest_observer LLM，结构化输出
│   ├── cache.py               # 【新增】按 (symbol,date,context_hash,skill_versions) 缓存判断
│   ├── context.py             # 【新增】组装 LLM 输入：窗口 bars + 维度数据 + skill 输出
│   └── schemas.py             # 【新增】ObservationJudgment pydantic 模型
├── volume_threshold.py        # 【新增】VolumeThresholdProvider：skill 一次性给放量倍数
├── policy.py                  # 改：维度计算从"触发门槛"改成"给 LLM 的数据准备"
├── strategy.py                # 改：buy_candidate 的死规则清理；卖出比例仍在此（ratio_of_position）
├── strategy_compiler_agent.py # 改：改走 get_llm_client(role)，不再 httpx 直打 Anthropic
└── models.py                  # 改：新增 backtest_observer role 相关配置；MA 窗口统一
```

### 5.2 触发口径（L1）

- 买触发：当日 close > 15EXPMA 且 前一日 close ≤ 15EXPMA（站上），且当日量比 ≥ skill 给的买入放量倍数。
- 卖触发：当日 close < 15EXPMA 且 前一日 close ≥ 15EXPMA（跌破），且当日量比 ≥ skill 给的破位放量倍数。
- 量比基准 = 当日量 / 前 N 日均量（不含当日），沿用 `indicators.volume_ratio`。

### 5.3 LLM 观察契约（L2）

```
输入（ObservationJudge.construct_prompt）:
  - 触发类型(buy/sell) + 触发日 T
  - 窗口 [T+1, T+2] 的 bars（OHLCV）
  - 维度数据（policy 计算的真实值：趋势修复/量能健康/站稳状态；半真/假维度标 data_status）
  - skill 提供的放量判定依据
  - <verified_skill sha256="..."> 绑定的 batch-trading-buy-signal / take-profit 等 skill 内容

输出（ObservationJudgment）:
  {
    "decision": "buy" | "sell" | "hold",
    "confirmed": true | false,            // 窗口内条件是否持续成立（站稳/稳定跌破）
    "dimensions": [{"name": "...", "passed": bool, "reason": "...", "data_status": "real|proxy|missing"}],
    "reasons": ["..."],
    "confidence": "high" | "medium" | "low"
  }
```

- LLM **只给方向和确认**，不给金额/比例——金额比例仍由确定性代码（`strategy.py` 的 ratio / 目标仓位缺口）算，沿用系统"数字永远来自确定性代码"原则。
- `confirmed=false` -> hold（不动手），等下一个触发。
- 结构化输出失败重试一次，仍失败 -> 该触发标 `unavailable` 并 hold，不阻塞其余。

### 5.4 卖出金额/比例

- 现状：`strategy.py` 硬编码 `technical_breakdown -> ratio_of_position=0.5`、`stop_loss -> 1.0`。
- 本期：保留确定性比例逻辑，但观察期改为"先确认再卖"。卖出比例仍由 `strategy.py` 给（半仓/清仓），LLM 不碰数字。
- 后续（Phase 2）：比例可从策略文本/配置解析，接上 `first_entry_plan_ratio` 等目前死掉的参数。

## 6. 可复现性与成本（硬约束）

- **可复现**：回测价值 = 同数据同结果。LLM 非确定，必须 temperature=0 + 缓存。缓存键含 `skill_versions`（SHA-256），skill 变了缓存自动失效重算。SkillBridge 已有 `cache_ttl_seconds` 可复用，但回测判断建议持久缓存（落 DB 或文件，跨次复用）。
- **成本**：L1 触发（放量+MA）是稀疏事件，一年几十个信号；每个触发 1 次 LLM 调用（窗口内一次判断，非逐 bar）。量级可接受。首跑慢、重跑免费。
- **合规**：LLM 全走 `get_llm_client(role)`，新角色 `backtest_observer` 走 `trading_room_llm_*` 同款凭证（可让回测跑在 DeepSeek 上）。skill 走 SkillBridge 真调用，`BatchTradingSkillRouter` 从装饰性元数据升级为真路由（修掉 review #11）。

## 7. 测试策略

| 层 | 测法 |
|---|---|
| TriggerScanner | 构造 OHLCV 序列 -> 放量站上/跌破 15EXPMA 的触发点准确；量比阈值由 skill 给时正确读取 |
| VolumeThresholdProvider | fake skill 返回固定倍数 -> 引擎使用该倍数 |
| ObservationJudge | fake LLM 固定输出 -> confirmed=true/false/hold 三路径；结构化输出失败重试一次再失败标 unavailable |
| ObservationCache | 同键命中、skill 版本变后失效、跨次复现 |
| Engine 三遍 | fake judge -> 买触发 T+3 成交、卖触发先观察 2 天再卖、confirmed=false 不动手；末段 bar 不丢确认（修 `engine.py:170` 边界） |
| 回归 | 现有 `test_backtest_engine.py` 全绿（行为变更的用例改写为对新模型的断言） |
| 契约 | 强买点 -> T+3 成交（而非 T+3 不成交/被吞）；买点+仓位满 -> 产出可见 `gate` 事件而非静默 hold |

## 8. 分阶段实施

- **Phase 0（P0，先解封）**：L1 机械触发 + 2 天观察骨架（**确定性**，judge 先用占位规则：窗口内站稳/稳定跌破即 confirmed）。买点能按模型成交、卖点改先观察再卖。删 `buy_cooldown` 死代码、修末段 bar 丢确认、MA 统一 15EXPMA。可跑可测，不依赖 LLM。
- **Phase 1**：接 `ObservationJudge`（真 LLM + 缓存）替换占位规则；`VolumeThresholdProvider` 接 skill；`strategy_compiler_agent` 改走 registry。
- **Phase 2**：补"逻辑/催化"真实数据源（景气度/公告 skill）、"资金回流"真·资金流向数据；多标的组合支持（修"组合允许"半真）；引擎上帝类拆分、执行日志不再写临时文件、metrics 加 benchmark/Sharpe。

## 9. 明确不做（防范围蔓延）

- 本期不动数据可信边界接入（`market_data_trust` / `market_data_mode` / `meta` 块）——另立 P1，不混进观察期改造。
- 不做多标的组合回测（Phase 2）。
- 不加 WebSocket / 实时推送（回测本就是离线）。
- 不删 5 维 checklist——维度计算复用为 LLM 的数据输入，只是不再当触发门槛。
- 不引入新的 provider SDK；所有 LLM 调用走 registry。
- Phase 0 不接 LLM，先用确定性占位 judge，保证能跑能测、不被 LLM 凭证/成本卡住。

## 10. 依赖与风险

- **行为变更面大**：卖侧从"当天卖"改"先观察 2 天再卖"，现有 `test_backtest_engine.py` 多个用例建立在前者上，需改写。Phase 0 先固化新行为再上 LLM。
- **T+3 成交延迟**：2 天观察 + T+1 执行 = 信号到成交 3 天。用户已确认接受（换判断质量）。强买点不再"立即执行"——这是有意为之，spec 覆盖了 `strategy.py:67` 那条死规则。
- **LLM 判断质量**：DeepSeek 结构化输出稳定性；失败语义沿用现有（重试一次 -> 标 unavailable -> hold）。
- **缓存膨胀**：按触发点缓存，量级稀疏，无虞；但需定期清理过期 skill 版本对应的旧缓存。
- **假维度风险**：Phase 0/1 降权留空"逻辑/催化"，LLM 判断会缺一维；需在输出里显式标 `data_status=missing`，不让 LLM 把"没数据"当成"不通过"。
