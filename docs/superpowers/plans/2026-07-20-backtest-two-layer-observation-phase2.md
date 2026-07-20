# 回测两层观察期模型 Implementation Plan（Phase 2）

> **Status: DRAFT - awaiting review.** Phase 1 已合并到 `main`（`513e3ef`）并完成 closeout（`2e21b05` / `384ab51` / `fdc2211`，119 tests green）。本 plan 是 Phase 2 草案，按 spec §8 范围拆成可执行 task。
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phase 1 把两层观察期模型 + 真 LLM judge + 缓存 + regime 分级止盈跑通。Phase 2 解决 Phase 0/1 明确"留到后面"的债：**内部清理**（执行日志去临时文件、metrics 加 benchmark/Sharpe、接死参数、删死码）、**真实数据源**（逻辑/催化景气度、资金回流真·主力净流入，替换 prosperity 手填常数和 amount 弱代理）、**引擎上帝类拆分**（`engine.py` 1950 行 / `run()` 660 行拆成 collaborator）、**多标的组合**（修"组合允许"半真）。

**Architecture:** 沿用 Phase 1 的 provider 模式（`SectorRegimeProvider` / `VolumeThresholdProvider`）：新增 `ProsperityProvider`、`CapitalFlowProvider` 镜像同款 skill + 确定性兜底 + 持久缓存。引擎拆分走**行为保持重构**（每抽一个 collaborator 全测试绿才提交，不引入新行为）。metrics 扩展是纯加法（`BacktestMetrics` 加字段，`_calculate_metrics` 扩计算）。多标的是最大改造，牵动 config / run() / API / policy / metrics 全链路，列为最后一段并设"工作量超阈值则拆 Phase 3"闸门。

**Tech Stack:** Python 3.11 async + pytest-asyncio + SkillBridge + LLM registry（不引入新 provider SDK）。

**Design spec:** `docs/superpowers/specs/2026-07-16-backtest-two-layer-observation-design.md`（§8 分阶段、§5.4 死参数、§4 五维数据真实性、§9 不做）。

## Global Constraints（沿用 Phase 1）

- **LLM 全走 registry**：`get_llm_client(role)`，不 import provider SDK。新增 provider（`ProsperityProvider` 若需 LLM）走 `backtest_observer` 或新角色，凭证沿用 `trading_room_llm_*`。
- **可复现**：所有 skill/LLM 判断必须持久缓存，键含 skill SHA-256 版本。新 provider 复用 `ObservationCache` / `RegimeCache` 同款键模式。
- **数字来自确定性代码**：provider 只给方向/数据，不给金额比例。metrics 计算纯确定性。
- **skill 不可用 fail-safe**：新 provider 沿用 `SectorRegimeProvider` 模式——skill 失败回退确定性兜底（`source="fallback_*"`），永不抛异常、不阻塞回测。
- **行为保持重构**：Phase 2c 引擎拆分期间，每个 commit 后 `tests/backtest/` + `tests/test_backtest_*.py` 必须全绿，不允许"先拆后修测试"。测试是安全网不是障碍。
- **只 `git add` backtest 文件**，不碰工作区遗留文件，不 push。不跑全量套件（real-data 测试会挂）。

---

## 分段与依赖

- **Phase 2a（内部清理 + metrics，低风险，先做）**：Task 1-5。互相独立，可串行交 subagent。
- **Phase 2b（真实数据源，中风险）**：Task 6-7。依赖对应 skill 可用性；skill 不在则先建 skill 或确认兜底足够。
- **Phase 2c（引擎拆分，高风险）**：Task 8。在 2a/2b 后做——拆的是"已清理 + 已加数据源"的稳定态，不返工。
- **Phase 2d（多标的组合，最高风险）**：Task 9。依赖 2c 拆分后的 collaborator。**设闸门**：若设计评估发现工作量超阈值（牵动 config/run()/API/policy/metrics 全链路重写），拆为独立 Phase 3，本 plan 只交付设计 spec。

> **Open question（review 时拍板）**：
> 1. **多标的（Task 9）本期做还是拆 Phase 3？** 它是最大改造。推荐：本期只出设计 spec（2d-0），实现视 spec 复杂度决定是否进 Phase 3。
> 2. **benchmark 标的选什么？** 推荐沪深300 ETF（510300）或与 signal-ETF 同赛道的宽基/行业指数。需用户确认默认值。
> 3. **执行日志字段是改 `execution_log_path` -> `execution_log_markdown`（破坏性），还是新增字段保留 path？** 推荐破坏性替换（回测离线，前端应展示文本而非路径），但需确认前端无 path 依赖。

---

## File Structure

### 新增
- `backend/app/backtest/metrics.py` - 从 `engine._calculate_metrics` 抽出，扩展 Sharpe/Sortino/Calmar/benchmark（Task 2/3）
- `backend/app/backtest/observation/prosperity.py` - `ProsperityProvider`（Task 6）
- `backend/app/backtest/observation/capital_flow.py` - `CapitalFlowProvider`（Task 7）
- `backend/app/backtest/engine/` - 拆分后的 collaborator 包（Task 8）：`observation_window.py`（`ObservationWindowStateMachine`）、`batch_policy.py`（`BatchSelectionPolicy`）、`batch_protection.py`（`BatchProtectionDetector`）、`regime_resolver.py`（`RegimeResolver`）、`execution_sink.py`（`ExecutionLogSink`）
- 测试：`tests/backtest/test_metrics.py`、`test_prosperity_provider.py`、`test_capital_flow_provider.py`、`test_engine_split_*.py`（每个 collaborator 一个）

### 修改
- `backend/app/backtest/models.py` - `BacktestMetrics` 加字段；`BacktestConfig` 加 benchmark/metrics 配置；删死字段 `first_entry_plan_ratio`/`weak_buy_allows_trade`/`buy_cooldown_days`/`sell_cooldown_days`（或接上）；`BacktestResult.execution_log_path` -> `execution_log_markdown`
- `backend/app/backtest/engine.py` - 瘦身：`run()` 拆 Pass 编排，主循环委托给 collaborator；`_calculate_metrics` 移到 `metrics.py`；删死方法 `_detect_buy_confirmation`（1780-1864）
- `backend/app/backtest/strategy.py` - `_decide_buy` buy_scale ladder 外置/接 `first_entry_plan_ratio`；卖出比例外置
- `backend/app/backtest/policy.py` - `_logic_catalyst`（148-162）改读 `ProsperityProvider`；`_funds_return`（136-145）改读 `CapitalFlowProvider`
- `backend/app/backtest/observation/llm_judge.py` - prompt 里 资金回流/逻辑催化 维度改读 provider 结果（`llm_judge.py:193` amount 标注、`:52-54` data_status）
- `backend/app/api/v1/backtest.py` - benchmark 三方对齐；response 字段更名；多标的 N 方对齐（Task 9）
- `backend/app/schemas/backtest.py` - `BacktestRunResponse` metrics 字段类型化；`execution_log_path` -> `execution_log_markdown`；多标的 request schema（Task 9）
- `frontend/src/types/` + 相关组件 - 同步 metrics 新字段、execution_log 字段更名（若前端用到）

---

## 任务清单概览

- **2a 内部清理**：1 执行日志去临时文件 / 2 metrics Sharpe+Sortino+Calmar / 3 metrics benchmark / 4 接死参数 / 5 删死码
- **2b 真实数据源**：6 ProsperityProvider（逻辑/催化）/ 7 CapitalFlowProvider（资金回流）
- **2c 引擎拆分**：8 engine.py 上帝类拆 5 个 collaborator
- **2d 多标的**：9 多标的组合（设计 spec + 闸门评估）

---

## Task 1: 执行日志去临时文件

**Files:** `engine.py`（740-757）、`models.py`（`BacktestResult.execution_log_path`）、`schemas/backtest.py`（`BacktestRunResponse.execution_log_path`）、`api/v1/backtest.py`（193） | Test: `tests/test_backtest_api.py`

**目标：** `run()` 现在每次写 `.md` 到 `tempfile.gettempdir()` 并返回绝对路径（`engine.py:740-757`）。改成 in-memory 返回 markdown 字符串，删 tempfile 写。`ExecutionLogger`（`execution_logger.py`）已在内存累积结构化 `ExecutionLog` records，`to_markdown()` 只是渲染——无需改 logger。

**Interfaces:**
- `BacktestResult.execution_log_markdown: str | None`（替换 `execution_log_path: str | None`，`models.py:157`）
- `BacktestRunResponse.execution_log_markdown: str | None`（替换 `execution_log_path`，`schemas/backtest.py:134`）
- `run()` 末尾：`execution_log_markdown = execution_logger.to_markdown()`，删 `tempfile`/`open`/`os.path.join` 块

- [ ] **Step 1: 写失败测试** - 断言 `response.execution_log_markdown` 非空且含关键执行记录；断言 `tempfile.gettempdir()` 下不产生新文件（或 `execution_log_path` 不再返回）
- [ ] **Step 2: 改 `BacktestResult` / `BacktestRunResponse` 字段** + `api/v1/backtest.py:193` 赋值点
- [ ] **Step 3: 改 `engine.py:740-757`** - 删 tempfile 写，改 `execution_log_markdown = execution_logger.to_markdown()`
- [ ] **Step 4: 前端同步**（若 `src/types/` 或组件用到 `execution_log_path`）- grep 前端确认
- [ ] **Step 5: 测试 + 提交** `refactor: return execution log in-memory instead of temp file`

---

## Task 2: metrics 加 Sharpe / Sortino / volatility / Calmar

**Files:** `engine.py`（`_calculate_metrics` 1924-1950）、`models.py`（`BacktestMetrics` 141-147）、`schemas/backtest.py`（127） | Test: `tests/backtest/test_metrics.py`（新增）

**目标：** `BacktestMetrics` 当前只有 5 个字段（total_return_pct / annual_return_pct / max_drawdown_pct / trade_count / final_equity），无任何风险调整收益。`equity_curve`（`PortfolioSnapshot`，含 date + equity + cumulative_return_pct）足够算日收益率。

**Interfaces:**
- `BacktestMetrics` 加字段：
  - `sharpe_ratio: float` - 日收益率均值 / 日收益率 std × √252（无风险利率默认 0，可配 `risk_free_rate`）
  - `sortino_ratio: float` - 用下行 std（仅负收益）
  - `annual_volatility_pct: float` - 日收益率 std × √252 × 100
  - `calmar_ratio: float` - annual_return_pct / max_drawdown_pct（回撤为 0 时返回 0 或 inf，定一个语义）
- 新建 `metrics.py`：`def calculate_metrics(equity_curve, config, trades) -> BacktestMetrics`，从 `engine._calculate_metrics` 抽出 + 扩展。`engine` 改为调用它。
- 边界：交易日 < 2 / 恒定权益 / 单边上涨（std=0）-> 各比率返回 0.0 并在 reason 标注，不抛、不 NaN。

- [ ] **Step 1: 写失败测试** - 构造已知 equity_curve（如线性上涨、先涨后跌），手算 Sharpe/Sortino/Calmar 断言；恒定权益 -> 0.0 不抛
- [ ] **Step 2: 新建 `metrics.py`** + 扩展 `BacktestMetrics` dataclass
- [ ] **Step 3: `engine._calculate_metrics` 改调 `metrics.calculate_metrics`**
- [ ] **Step 4: API schema `metrics: dict[str, Any]` 保持兼容**（新字段自动进 dict）；前端 type 同步
- [ ] **Step 5: 测试 + 提交** `feat: add Sharpe/Sortino/Calmar/volatility to backtest metrics`

---

## Task 3: metrics 加 benchmark 收益对比

**Files:** `metrics.py`、`engine.py`（`run()` 签名 105）、`models.py`（`BacktestConfig`）、`api/v1/backtest.py`（`_align_by_date` 316 三方对齐）、`schemas/backtest.py`（`BacktestRunRequest` 110） | Test: `tests/backtest/test_metrics.py`

**目标：** 加 benchmark 系列对比。需 benchmark series 输入（日 OHLCV 或 NAV），三方对齐 fund_nav / signal_bars / benchmark。

**Interfaces:**
- `BacktestConfig` 加 `benchmark_code: str | None = None`（如 "sh510300"）
- `run()` 加可选 `benchmark_nav: list[FundNavPoint] | None = None`（或 benchmark bars）
- `_align_by_date` 扩成三方对齐（fund / signal / benchmark），benchmark 缺失则跳过 benchmark metrics
- `BacktestMetrics` 加：`benchmark_return_pct: float`、`alpha_pct: float`（超额 = total_return - benchmark_return）、`beta: float`（fund 日收益对 benchmark 日收益回归斜率）、`information_ratio: float`（超额收益均值 / 跟踪误差 × √252）
- benchmark 数据源：复用 `EastmoneyFundNavClient`（ETF NAV）或 signal 同款 `WestockDataClient`

- [ ] **Step 1: 写失败测试** - 给定 fund + benchmark 系列，断言 alpha/beta/information_ratio；benchmark 缺失 -> 字段为 0 / None 不抛
- [ ] **Step 2: 扩 config / run() 签名 / `_align_by_date` 三方**
- [ ] **Step 3: `metrics.py` 加 benchmark 计算**（回归用 `statistics` 或手写最小二乘，不引新依赖）
- [ ] **Step 4: API 层接 benchmark_code** - request 传参，加载 benchmark NAV
- [ ] **Step 5: 测试 + 提交** `feat: add benchmark return/alpha/beta to backtest metrics`

> **Open question：** benchmark 默认标的（沪深300 510300？中证500 510500？同赛道行业指数？）。Task 实现时给 `benchmark_code=None` 占位，默认值 review 时定。

---

## Task 4: 接死参数 + 卖出比例外置

**Files:** `strategy.py`（`_decide_buy` 175-189 buy_scale ladder、卖出比例 88/95/109/121）、`models.py`（死字段 69-72） | Test: `tests/test_backtest_engine.py`、`tests/backtest/test_config_thresholds.py`

**目标：** spec §5.4 标 `first_entry_plan_ratio` 等参数"目前死掉"。调研确认：`first_entry_plan_ratio` / `weak_buy_allows_trade` / `buy_cooldown_days` / `sell_cooldown_days` 被 compiler 写进 config 但 engine/strategy 从不读；卖出比例硬编码 0.5/1.0。本期接上或明确删除。

**Interfaces / 决策点：**
- **buy_scale ladder 外置**：`_decide_buy`（`strategy.py:175-189`）当前硬编码 `bull+strong=1.0 / middle=0.7 / weak=0.5 / bear|neutral=0.3`。改成读 config 字段：`buy_scale_strong/middle/weak` + `regime_downgrade_factor`（bear|neutral 乘子，默认 0.3）。`first_entry_plan_ratio` 作为"首仓占目标比例"替代 strong_buy 的 1.0（语义：首次建仓建 first_entry_plan_ratio 比例的目标仓，默认 0.5）。
- **卖出比例外置**：`ratio_of_position` 当前硬编码（`strategy.py:88/95/109/121`）。加 config 字段 `profit_drawdown_sell_ratio` / `technical_breakdown_sell_ratio` / `post_sell_observation_sell_ratio` / `stop_loss_sell_ratio`，默认值对齐现状（0.5/0.5/0.5/1.0）。
- **死字段处置**：`weak_buy_allows_trade` / `buy_cooldown_days` / `sell_cooldown_days` —— 若本期不接（cooldown 已被 `observe_days` 替代，weak_buy 在新模型里走观察期确认），**删除字段 + 删 compiler 里的赋值**（`strategy_text.py` / `strategy_compiler_agent.py`），避免"写进去没人读"的债务继续。`first_entry_plan_ratio` 接上不删。

- [ ] **Step 1: 写测试** - config 改 buy_scale_* / sell_ratio_* -> 引擎行为跟着变（证明不再硬编码）；删 cooldown 字段后 compiler 测试不报缺字段
- [ ] **Step 2: `models.py` 加 buy_scale / sell_ratio 字段 + 删 cooldown/weak_buy_allows_trade**
- [ ] **Step 3: `strategy.py` 读 config** 替换硬编码；`first_entry_plan_ratio` 接 strong_buy 首仓
- [ ] **Step 4: `strategy_text.py` / `strategy_compiler_agent.py` 删死字段赋值**
- [ ] **Step 5: presets.py 给新字段设默认值**（对齐现状，保行为不变）
- [ ] **Step 6: 测试 + 提交** `refactor: externalize buy/sell ratios, wire first_entry_plan_ratio, drop dead cooldown fields`

> **Open question：** `first_entry_plan_ratio` 语义是"首仓比例"还是"首仓占目标的比例"？影响乘法顺序。推荐后者（占目标比例，乘 target_position_pct）。

---

## Task 5: 删死方法 `_detect_buy_confirmation`

**Files:** `engine.py`（1780-1864） | Test: 现有套件（确认无引用）

**目标：** 调研确认 `_detect_buy_confirmation`（1780-1864）在当前主循环里**死代码**——主循环在 361-380 inline 构建 `buy_confirmation_event`，不调这个方法。删掉减负，为 Task 8 拆分清场。

- [ ] **Step 1: grep 确认 `_detect_buy_confirmation` 无生产调用**（仅定义，无 self.引用）
- [ ] **Step 2: 删方法**
- [ ] **Step 3: 全 backtest 测试绿**（应无影响）
- [ ] **Step 4: 提交** `refactor: remove dead _detect_buy_confirmation method`

---

## Task 6: ProsperityProvider（逻辑/催化真实数据源）

**Files:** `observation/prosperity.py`（新增）、`engine.py`（Pass 2b 178-188、买门 357、regime fallback 1684）、`policy.py`（`_logic_catalyst` 148-162） | Test: `tests/backtest/test_prosperity_provider.py`

**目标：** spec §4 标"逻辑/催化"维度为**假**（`prosperity.score` 手填常数，`presets.py` 各处 `score=8.0`，回测期间不变、不来自 skill）。本期接真实景气度/公告数据源，镜像 `SectorRegimeProvider` 模式。

**Interfaces:**
- `class ProsperityProvider`：`async def assess(symbol, signal_bars, as_of_index, config) -> ProsperityAssessment`
  - `ProsperityAssessment`：`score: float`（0-10）、`reasons: list[str]`、`source: str`（"skill"/"fallback_config"）、`skill_versions: list[str]`
  - 调 `announcement-search` skill（`~/.openclaw/workspace/skills/announcement-search/` 已存在但未被 backtest 引用）或景气度 skill，传 symbol + as_of_date
  - skill 不可用 -> 回退 `config.prosperity.score`，标 `source="fallback_config"`，永不抛
  - 持久缓存：复用 `RegimeCache` 同款 JSON 文件模式，键 `(symbol, date, skill_version)`
- 接入点：
  - Pass 2b（`engine.py:178-188`）：若 `prosperity_provider` 给定，per-index 算 `self._prosperity[idx]`
  - 买门（`engine.py:357`）：`prosperity = self._prosperity.get(index) or config.prosperity`
  - regime fallback（`engine.py:1684`）：`_get_market_regime` 改读 per-day prosperity
  - `policy.py:148-162` `_logic_catalyst`：改读 `ProsperityAssessment`，`data_status` 从 `missing` 升级为 `real`（skill 命中）或 `proxy`（fallback）

- [ ] **Step 1: 核对 skill 现状** - 读 `announcement-search/SKILL.md`，确认 inputs/outputs 能给景气度评分；若不能，确认兜底 `config.prosperity` 是否可接受为本期交付（skill 接入留 follow-up）
- [ ] **Step 2: 写失败测试** - fake skill 返回 score=9 -> ProsperityAssessment 正确；skill 不可用 -> 回退 config 值；缓存命中跳过 skill
- [ ] **Step 3: 实现 `prosperity.py`**（镜像 `regime.py` 结构）
- [ ] **Step 4: 接入 engine Pass 2b + 买门 + regime fallback + policy**
- [ ] **Step 5: `llm_judge.py` prompt 里 逻辑/催化 维度 data_status 升级**
- [ ] **Step 6: 测试 + 提交** `feat: add ProsperityProvider for real 逻辑/催化 data source`

---

## Task 7: CapitalFlowProvider（资金回流真实数据源）

**Files:** `observation/capital_flow.py`（新增）、`policy.py`（`_funds_return` 136-145、`__init__` 44）、`observation/llm_judge.py`（prompt 193 amount 标注、`__init__` 97） | Test: `tests/backtest/test_capital_flow_provider.py`

**目标：** spec §4 标"资金回流"为**弱代理**（`SignalBar.amount` 是成交额，非真·主力净流入）。`amount` 当前被用（policy 计算 + cache key + LLM prompt），但只是成交额。本期接真·资金流数据源，镜像 `VolumeThresholdProvider` 模式。

**Interfaces:**
- `class CapitalFlowProvider`：`async def get_flow(symbol, as_of_date, config) -> CapitalFlowAssessment`
  - `CapitalFlowAssessment`：`net_inflow: float`（主力净流入）、`inflow_strength: float`（归一化强度 0-1）、`source: str`、`skill_versions: list[str]`
  - 调资金流 skill（调研发现 `~/.openclaw/workspace/skills/` 有"美国 ETF 资金流分析"/"行业轮动监控"但未被 backtest 引用；需确认是否有 A 股主力净流入 skill，无则建 skill 或用东方财富资金流 API）
  - skill 不可用 -> 回退 `bar.amount` 成交额代理，标 `source="fallback_turnover"`
  - 缓存：复用 `ObservationCache` 键模式 `(symbol, date, "capital_flow", skill_version)`
- 接入点：
  - `policy.py:44` `TradingSystemPolicy.__init__` 注入 provider
  - `policy.py:136-145` `_funds_return` 改读 `CapitalFlowAssessment.net_inflow` 而非 `bar.amount`
  - `llm_judge.py:97` `LLMObserverJudge.__init__` 注入；prompt（`:193`）`额=` 改成 `主力净流入=` + 强度

- [ ] **Step 1: 核对 skill 现状** - 确认是否有 A 股主力净流入 skill；若无，决定建 skill 还是接东方财富资金流 API（`direct_api.py` 模式）
- [ ] **Step 2: 写失败测试** - fake skill 返回净流入 -> assessment 正确；不可用 -> 回退 turnover；缓存命中跳过 skill
- [ ] **Step 3: 实现 `capital_flow.py`**（镜像 `volume.py` 结构）
- [ ] **Step 4: 注入 policy + llm_judge，替换 amount 直读**
- [ ] **Step 5: 测试 + 提交** `feat: add CapitalFlowProvider for real 资金回流 data source`

> **风险：** 资金流 skill 可能完全不存在（调研未发现 backtest 可用的 A 股主力净流入 skill）。若需新建 skill，工作量外溢——此时 Task 7 可能拆成 7a（建 skill）+ 7b（接 provider）。review 时评估。

---

## Task 8: 引擎上帝类拆分

**Files:** `engine.py`（1950 行）、新增 `engine/` 包 | Test: 全 backtest 套件（4400 行回归 + 契约测试是安全网）

**目标：** `engine.py` 1950 行，`run()` 单方法 660 行，buy/sell/止盈/观察窗/权益/事件/日志全缠在主循环。拆成 5 个 collaborator，**行为保持**（不改对外行为，只重组内部）。这是 Phase 2 最高回归风险项。

**拆分缝（调研确认）：**
1. **`ObservationWindowStateMachine`** - 持有 `buy_observation_*` / `sell_observation_*` / `post_sell_observation_*` 状态（现 199-208）+ 主循环 inline 块（buy 330-438、sell 440-545）+ 末段清理（686-736）
2. **`BatchSelectionPolicy`** - `_select_batches_to_sell`（990-1101）、`_batches_by_priority`、`_core_half_batches`、`_batches_covering_shares`、`_next_buy_batch_type`（973）。纯函数 `(event, decision, batches, nav, config) -> batches`
3. **`BatchProtectionDetector`** - `_detect_batch_profit_protection`（1322-1454）、`_detect_post_sell_observation`（1456-1526）、`_post_sell_recheck_result`（1528-1608）、`_core_protection_tier`（1728-1778）、`_batch_*_protection_triggered`（1619-1648）
4. **`RegimeResolver`** - `_regimes` 缓存、`_regime_state`（1650）、`_get_market_regime`（1666）；确定性 fallback 移出 engine
5. **`ExecutionLogSink`** - 临时文件写（Task 1 后已是 in-memory）+ `ExecutionLogger` 调用（634）

**重构纪律（硬约束）：**
- **一次抽一个 collaborator**，每个 commit 后全测试绿才继续下一个。不允许"一次性大拆"。
- 顺序建议：`RegimeResolver`（最独立）-> `BatchSelectionPolicy`（纯函数）-> `BatchProtectionDetector` -> `ObservationWindowStateMachine`（最大）-> `ExecutionLogSink`（最小）
- 每抽一个：先移方法到新类（保持签名），engine 持有实例并委托，跑测试，绿了才提交。**不改逻辑、不改签名、不改测试期望**（除非测试直接断言 engine 私有方法——那种改成断言新 collaborator）。
- `run()` 最终瘦到只做 Pass 编排（Pass 1/2/2b/3 的调度），主循环体委托给 collaborator。

- [ ] **Step 1: 抽 `RegimeResolver`** + 测试绿 + 提交
- [ ] **Step 2: 抽 `BatchSelectionPolicy`** + 测试绿 + 提交
- [ ] **Step 3: 抽 `BatchProtectionDetector`** + 测试绿 + 提交
- [ ] **Step 4: 抽 `ObservationWindowStateMachine`** + 测试绿 + 提交（最大，可能需分 4a 买窗 / 4b 卖窗 / 4c post-sell 三个子 commit）
- [ ] **Step 5: 抽 `ExecutionLogSink`** + 测试绿 + 提交
- [ ] **Step 6: `run()` 瘦身复核** - 确认主循环只编排、不内联状态机；全契约测试绿
- [ ] **Step 7: 提交** `refactor: split BacktestEngine god-class into collaborators`（或每步独立提交）

> **风险：** 这是纯结构重构，但 660 行主循环重排极易引入微妙回归（观察窗边界、cooldown、批次选择顺序）。安全网：4400 行测试 + Phase 1 的 5 个契约测试（含刚加的 regime-change）。若某步测试红且难定位，回退该步重拆，不硬修测试。

---

## Task 9: 多标的组合（设计 spec + 闸门评估）

**Files:** 设计 spec `docs/superpowers/specs/2026-07-20-backtest-multi-asset-portfolio.md`（新增） | 实现文件待 spec 定稿

**目标：** spec §4 标"组合允许"为**半真**（仓位计算真，但单标的无组合、"相关暴露"是静态输入 `current_correlated_growth_exposure_pct`）。本期修真：支持多标的组合回测，跨标的聚合暴露/相关性。

**现状（调研）：** engine 硬编码单 (fund, signal) 对——`BacktestConfig` 标量 fund_code/signal_code；`run()` 单 fund_nav/signal_bars + 等长检查（118）；API 单对 + `_align_by_date` 两方对齐；`_portfolio_allowed`（policy.py:164-187）读静态字段不跨标的聚合。

**闸门（先出 spec，再评估是否本期实现）：**
- [ ] **Step 1: 出设计 spec** - 覆盖：config 多标的结构（`symbols: list[SymbolConfig]`）、`run()` 签名（dict 化）、API N 方对齐、跨标的暴露聚合（`_portfolio_allowed` 改实时聚合）、相关性/风险预算、metrics 多曲线（per-symbol + portfolio-level）、与 Task 8 collaborator 的接合点
- [ ] **Step 2: 工作量评估** - 若 spec 显示需重写 config/run()/API/policy/metrics 全链路（估算 > Phase 1 量级），**拆为 Phase 3**，本 plan 只交付 spec；若可控（增量改造），继续 Step 3
- [ ] **Step 3（若闸门通过）: 分子 task 实现** - 按 spec 拆，每步测试绿
- [ ] **Step 4: 提交** `feat: multi-asset portfolio backtest` 或 `docs: multi-asset portfolio design spec (deferred to Phase 3)`

> **Open question（review 时拍板）：** Task 9 本期做到哪？推荐：**本期只出设计 spec（Step 1-2），实现视评估决定 Phase 2d 还是 Phase 3。** 多标的是 spec §8 列的 Phase 2 项，但工作量看可能超阈值，硬塞会拖垮 Phase 2 节奏。

---

## 依赖与风险

- **Task 1-5 独立低风险**：内部清理 + metrics 加法，不改行为模型。可串行快速推进。
- **Task 6-7 依赖 skill 可用性**：`announcement-search` skill 存在但需核对能否给景气度评分；A 股主力净流入 skill 可能不存在（Task 7 风险最高，可能外溢建 skill）。fail-safe 兜底保证不阻塞回测。
- **Task 8 最高回归风险**：660 行主循环重排。纪律是"一次一个 collaborator + 每步全绿"，4400 行测试 + 5 契约测试是安全网。必须在 Task 1-7 后做（拆稳定态不返工）。
- **Task 9 最大设计变更**：牵动全链路。闸门机制防止失控——先 spec 后评估，可拆 Phase 3。
- **行为保持 vs 行为变更**：Task 1-5/8 是行为保持（测试期望基本不变）；Task 6-7 改 LLM 输入数据源（行为可能变，但更真）；Task 9 是行为扩展。每 task 明确标注属于哪类，测试策略不同。
- **不引入新依赖**：Sharpe/回归用 `statistics` 或手写，不引 numpy/pandas（除非用户同意）。
- **Phase 2 不做**（沿用 spec §9）：数据可信边界接入（`market_data_trust` / `market_data_mode`，另立 P1）、WebSocket 实时推送、新 provider SDK。
