# 飞书推送真实化与可用性提升

> 日期：2026-07-16 ｜ 分支建议：`agent/feishu-realdata`
> 范围：四块一起做——数据真实化、隔夜外盘专项、持仓影响关联、预警激活。
> 决策（已与用户确认）：① 飞书保持 webhook 单向推送，只修内容；② 真实数据为基底 + LLM 做解读增强；③ 四块一起做。
> 实现交 subagent，本文档为施工蓝图。

## 一、根因总结（诊断结论）

| 用户抱怨 | 代码根因 |
|---|---|
| 数据不真实 | `daily_summary._local_market_snapshot()` 用 `MarketDataProvider`（date-seeded 随机数 mock）；`DirectAPIStrategy._fetch_quotes` 是 stub（TODO 未实现）。skill 失败即 fallback 到假数据。 |
| 主题笼统（"AI"） | mock 写死 `INFLOW_SECTORS=["AI","半导体","新能源"]`，未用 eastmoney 真实行业板块。 |
| 上证强弱不对 | mock 的 `change_pct = _rng.uniform(-2.5, 2.5)`，纯随机。 |
| 隔夜纳指/韩日没说 | 无真实海外指数通道；`us_overnight` 全靠 Claude CLI skill，取不到就编。 |
| 影响持仓空洞 | `Position` 无 `estimated_change_pct` 字段；`_portfolio_context()` 只取累计盈亏，没带养基宝已有的 gsz/gszzl（`portfolio.py:61-64` 已解析但未透出）。 |
| 预警可用性低 | `anomaly_detection.scan_and_alert` 直接 `return skipped`（整段禁用）；`monitoring_alert.py` 解析出的 `PriceAlert` 行无任何定时任务消费（scheduler 无评估 job）。 |

## 二、已验证的技术事实

1. **eastmoney 全球指数真实可用**：`https://push2.eastmoney.com/api/qt/ulist.np/get` 一次批量返回全部指数，secid 映射——
   - 美股：`100.DJIA`(道指) `100.SPX`(标普) `100.NDX`(纳斯达克综合)
   - 亚太：`100.HSI`(恒生) `100.N225`(日经) `100.KS11`(韩国KOSPI)
   - A股：`1.000001`(上证) `1.000300`(沪深300) `0.399006`(创业板) `1.000688`(科创50)
   - 实测：上证 3923/-0.82%，日经 66899/-2.69%，KOSPI 6794/-6.72%（均为实时真值）
2. **eastmoney 真实行业板块**：`sector_card_service._fetch_eastmoney_all_sectors()` 已实现，返回具体行业（光模块/半导体设备等），返回字段 `f14`=板块名 `f3`=涨跌% `f62`=资金流。当前是同步 `httpx.Client`，async 任务需 `to_thread` 包裹。
3. **养基宝已有盘中估值**：`yangjibao/portfolio.py:61-64` 解析 `gsz`/`gszzl`/`vgsz`/`vgszzl`，存入 `Position.current_price = gsz or dwjz`，但 `gszzl`（今日预估涨跌）未落库也未透出。
4. **trust 边界**：`market_data_trust.py` 提供 `validate_index_rows`/`validate_quote_rows`/`validate_sector_rows`/`market_data_meta`，新数据源必须走校验，live 模式 fail-closed。

## 三、改造设计

### 阶段 A：真实数据通道（替换 mock）

**A1. 新建 `app/services/global_index_provider.py`**
- 类 `GlobalIndexProvider`，方法 `async get_indices(codes) -> list[dict]`
- 调 eastmoney `qt/ulist.np/get`，secids 用上面映射，fields=`f12,f14,f2,f3,f4,f5`（code,name,price,changePct,change,volume）
- 返回统一 bridge 格式：`{code, name, price, change, change_pct, market}`
- 失败时返回 `[]` + 抛 `DataUnavailable`，**绝不返回 mock**（遵守 trust 边界）
- A股 secid 前缀规则：`6`开头→`1.`, `0/3`开头→`0.`，海外指数固定 `100.`

**A2. 在 `direct_api.py` 实现真实 `_fetch_indices`（替换 stub）**
- 删除 `_fetch_indices` 里的 TODO stub，改为调用 `GlobalIndexProvider`
- `_fetch_quotes`（ETF/个股实时价）同步实现真实化：eastmoney `qt/stock/get` secid 规则 `1.600xxx`/`0.000xxx`/`0.3xxxxx`，fields=`f43,f57,f58,f169,f170`
- 这样 `bridge.invoke_simple("index_quote")` 走 DirectAPIStrategy 就能拿到真实数据，`market_service.get_global_indices()` 自动受益

**A3. `daily_summary._local_market_snapshot()` 废弃 mock**
- 改为：indices 调 `GlobalIndexProvider`；capital_flow 调 `sector_card_service._fetch_eastmoney_all_sectors`（`to_thread` 包裹）；sentiment 保留但标注——北向资金 eastmoney 有接口（`qt/ulist.np/get` secid 沪深港通），可后续补，先标 `source=eastmoney_partial`
- 保留 `MarketDataProvider` 仅作 `market_data_mode=demo` 时的演示用，live 模式绝不调用

**A4. trust 接入**
- `GlobalIndexProvider` 返回前过 `validate_index_rows`；板块过 `validate_sector_rows`
- `_local_market_snapshot` 返回结构带 `meta`：source/fetched_at/mode/is_mock

### 阶段 B：持仓实时估值（打通"影响持仓"）

**B1. `Position` 模型新增字段**
- `estimated_change_pct: Float | None`（今日预估涨跌，来自 gszzl）
- `estimated_nav: Float | None`（gsz 盘中估算净值）
- `estimated_at: DateTime | None`（估值时间戳，判断新鲜度）
- Alembic/SQLAlchemy 迁移（项目用 aiosqlite，`init_db` + `Base.metadata.create_all`，需确认是否要 alembic；查 `backend/app/database.py` 决定）

**B2. `yangjibao/portfolio.py` sync 时写入新字段**
- `sync()` 里 gsz/gszzl 解析处（line 61-64 附近）增加写入 `estimated_change_pct`/`estimated_nav`/`estimated_at`
- ETF 持仓（code 前缀 51/15/58）额外用 eastmoney 实时价校验/补充

**B3. 新建 `app/services/portfolio_valuation_service.py`**
- `async get_live_valuation() -> list[PositionValuation]`
- 盘中（is_market_hours 或美股开盘窗口）优先实时调 `YangjibaoClient.get_all_holdings()` 拿最新 gsz/gszzl；token 失效则读 DB 缓存并标 `stale=true`
- 返回：`{symbol, name, position_type, market_value, unrealized_pnl_pct, today_estimated_pct, estimated_at, stale}`

**B4. `daily_summary._portfolio_context()` 扩展**
- 改调 `PortfolioValuationService`，把 `today_estimated_pct` 带出来
- 持仓按"受隔夜外盘影响程度"排序：QDII/纳指/标普/恒生类ETF排前，纯A股基金排后

### 阶段 C：推送内容重构

**C1. 三段推送结构统一**
所有推送固定四段，数据为基底、LLM 只做解读：
```
【结论】一句话：偏强/偏弱/分歧/观望 + 对我是否重要
【关键依据】≤3条，真实指数/板块/资金数字
【影响你的持仓】≤3只，中文名+代码+今日预估+机会/风险（关联外盘/板块）
【下一步】≤2条观察动作
```

**C2. `us_overnight` 重构（用户最痛）**
- 数据基底（真实）：道指/标普/纳斯达克 + VIX/美元指数（eastmoney `100.VIX`/`100.USDX` 可选）+ 日经/KOSPI/恒生
- 持仓关联：持仓里的 QDII/纳指100ETF(159913等)/标普500ETF/恒生ETF/恒生科技ETF → 用隔夜外盘涨跌 × 基金 beta 估算今日开盘影响
- LLM 任务收窄：只做"把上面的真实数字翻译成中文解读 + 判断利好/利空/中性"，不再让它"调 skill 取数据"
- prompt 改造：把真实数据 JSON 作为 `facts` 喂入，明确"以下为真实数据，不得编造，只能解读"

**C3. `morning`/`tail` 重构**
- 数据基底：A股核心指数 + eastmoney 真实行业板块资金流 top/bottom + 持仓今日预估
- 板块用真实行业名（光模块/半导体设备），不再出现笼统"AI"
- 持仓关联：把持仓基金的重仓行业（从 FundProfile/板块映射）和今日强势板块匹配

**C4. LLM 调用改造**
- `_run_claude_skill_summary` 保留，但 prompt 重写：从"必须调同花顺 skill"改为"基于以下真实 facts 做解读"
- `_looks_substantive` 质量门禁：增加"必须引用至少一个 facts 里的真实数字"检查，防止 LLM 空谈
- fallback 改为"真实数据结构化要点"而非 mock 摘要（`_concise_local_summary` 重写，数据源换真实）

**C5. 新增 `/api/v1/feishu/preview` 调试端点**
- 手动触发三种推送预览，返回 `message` + `meta`（source/is_mock/reason），方便验收数据真实性，不用等定时任务

### 阶段 D：预警激活

**D1. 新建 `app/tasks/alert_evaluator.py`**
- `async evaluate_alerts()`：读所有 `enabled=True` 的 `PriceAlert` 行
- 对每条 alert 拉对应 symbol 实时数据：
  - ETF（51/15/58 前缀）→ eastmoney `qt/stock/get` 实时价
  - 场外基金 → `PortfolioValuationService` 的 gsz/gszzl
  - `_portfolio_` 聚合 → 组合总盈亏/回撤
- 判断条件命中（price_above/below、change_pct、consecutive_down）且过 `cooldown_min` → 推飞书
- 推送内容：基金中文名+代码+触发条件+当前值+建议动作（只提醒不指令）

**D2. scheduler 注册**
- 盘中每 10 分钟跑一次：`CronTrigger(day_of_week="mon-fri", minute="*/10")` + `is_market_hours()` 门禁
- 美股相关 alert（QDII/纳指持仓）额外在 22:30-次日 04:00 窗口检查（隔夜外盘）
- misfire_grace_time 合理设置

**D3. `anomaly_detection.py` 处理**
- `scan_and_alert` 保持 return skipped（基金日内 P&L 告警确实不适用），但加注释指向 `alert_evaluator` 接管
- 或直接删除该函数，从 scheduler 移除引用（确认无其他引用后）

**D4. alert 评估数据缓存**
- 同一 symbol 10 分钟内复用实时数据，避免重复请求 eastmoney
- 触发记录写 `alert_trigger_log` 表（可选，用于后续调优阈值/冷却）

## 四、文件改动清单

| 文件 | 改动 |
|---|---|
| `app/services/global_index_provider.py` | **新建** A1 |
| `app/services/portfolio_valuation_service.py` | **新建** B3 |
| `app/tasks/alert_evaluator.py` | **新建** D1 |
| `app/skills/strategies/direct_api.py` | A2 实现真实 `_fetch_indices`/`_fetch_quotes` |
| `app/services/market_data_provider.py` | A3 标注仅 demo 用，live 不调用 |
| `app/tasks/daily_summary.py` | A3/C1-C4 重构快照与推送 |
| `app/models/position.py` | B1 新增 3 字段 |
| `app/yangjibao/portfolio.py` | B2 sync 写入估值字段 |
| `app/services/yangjibao_service.py` | B3 暴露实时估值入口 |
| `app/tasks/scheduler.py` | D2 注册 alert_evaluator job |
| `app/tasks/anomaly_detection.py` | D3 清理 |
| `app/api/v1/feishu.py`（或 router） | C5 新增 preview 端点 |
| `backend/tests/` | 新增：global_index_provider、alert_evaluator、daily_summary 真实数据路径测试 |

## 五、验收标准

1. 手动跑 `us_overnight` 推送：正文必须包含真实的隔夜纳指/日经/KOSPI 数字，且与 eastmoney 实时一致；`meta.is_mock=False`。
2. `morning` 推送：板块名为具体行业（非"AI"），上证涨跌与 eastmoney 一致。
3. "影响你的持仓"段：至少 1 只基金带 `今日预估 ±X.XX%`。
4. 构造一条 `PriceAlert`（如某 ETF change_pct < -3%），10 分钟内收到飞书触发通知，重复触发受 cooldown 抑制。
5. `make test` 全绿；新增测试覆盖数据源失败时 fail-closed（返回 unavailable 而非 mock）。
6. eastmoney 不可达时：live 模式推送带 `meta.status=unavailable` + 安全提示，**不**用 mock 顶替。

## 六、实施顺序与依赖

```
A1 (index provider) ──┐
A2 (direct_api real) ──┼─> A3 (snapshot 去mock) ──┐
B1 (model 字段) ──────┐ │                          │
B2 (sync 写估值) ─────┼─> B3 (valuation svc) ──────┼─> C1-C4 (推送重构) ──> C5 (preview)
                      │ │                          │
                      └─┴──────────────────────────┴─> D1-D4 (预警) [可与C并行]
```

- A、B 是数据基底，先行；C 依赖 A+B；D 相对独立，可并行。
- 建议拆 2 个 subagent：一个做 A+B+C（数据+推送），一个做 D（预警）。D 的 alert_evaluator 依赖 B3 的估值服务，需 B3 先合入或约定接口。

## 七、风险与注意

- **eastmoney 限频**：批量 ulist 接口单次可查全部指数，板块接口 `pz=200` 一次够用，频率低（每天 3 次推送 + 预警 10 分钟一次），风险低。预警评估对单 symbol 实时价用缓存。
- **养基宝 token 失效**：B3 必须有 DB 缓存降级路径，标 `stale=true`，推送里如实说明"估值可能延迟"。
- **trust 边界**：所有新数据源走 `market_data_trust` 校验，live 模式 fail-closed，绝不静默用 mock。这是 CLAUDE.md 硬约束。
- **LLM 仍可能失败**：C4 的 fallback 是"真实数据结构化要点"（有数字、可用），不是 mock 摘要。即使 LLM 全挂，推送仍真实可用。
- **迁移**：B1 加字段需确认项目迁移机制（alembic vs create_all），影响部署。
