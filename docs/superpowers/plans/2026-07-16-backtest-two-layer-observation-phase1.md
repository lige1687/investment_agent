# 回测两层观察期模型 Implementation Plan（Phase 1）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: COMPLETE — merged to `main` (commit `513e3ef`).** All Tasks 1-11 done.
> Post-merge closeout:
> - `2e21b05` fixed a real prosperity-gate bug (`prosperity < 50` on a 0-10 scale rejected all buys → `< config.prosperity.min_score_to_buy`) and adapted 3 integration-test expectations.
> - `384ab51` wired a real `SectorRegimeProvider` into the production API entry (`app/api/v1/backtest.py`). Without it `engine.py:350` defaulted `regime_for_buy="neutral"` every day, silently downgrading every strong_buy from the 20% target to 6% (Task 8 tier-downgrade). `neutral` now remains only the per-day missing-data fallback inside the provider.
> - `fdc2211` added the 5th contract test (Task 11 Step 2): `tests/backtest/test_engine_regime_change.py` — a single `engine.run()` where the provider returns bull early / bear late, guarding the per-index regime lookup on both buy sizing (20% vs 6%) and sell mode (trailing vs gain-ladder).
> Full backtest suite green: 119 passed. Phase 2 scope (real 逻辑/催化 data sources, real 资金回流, multi-asset portfolio, engine god-class split, metrics benchmark/Sharpe) is not yet planned.

**Goal:** Phase 0 用确定性 `DeterministicJudge` 跑通了买/卖两层观察期骨架（T+3 成交、gate 可见）。Phase 1 把占位 judge 换成**真 LLM**（走 registry、缓存保可复现），并按 spec §11 重构卖侧为**"风险出口 + regime 分级止盈"**（per-sector regime skill 驱动牛 trailing / 熊 gain-ladder），同时接上放量阈值 skill、买侧 regime 降档、compiler 改走 registry。

**Architecture:** 新增 `LLMObserverJudge`（实现 Phase 0 已建的 `ObservationJudge` Protocol），走 `get_llm_client("backtest_observer")`、temperature=0、结构化输出；判断结果按 (symbol+触发日+窗口上下文 hash+skill 版本) **持久缓存**。引擎 `run()` 改 async 以调 async judge。卖侧拆两层：风险出口（放量跌破 observe，Phase 0 已实现，**最高优先**）+ 止盈（regime 驱动：牛=高点回撤 trailing，熊=gain-ladder 分批直接）。regime 由 `batch-trading-market-regime` skill（带 signal-ETF 赛道上下文）给出 per-sector 判断 + take-profit tightness。买/卖共用同一 regime 信号。

**Tech Stack:** Python 3.11 async + pytest-asyncio + SQLAlchemy（缓存落库）+ SkillBridge + LLM registry。

**Design spec:** `docs/superpowers/specs/2026-07-16-backtest-two-layer-observation-design.md`（§3.1 三遍缓存架构、§11 卖侧设计）。

## Global Constraints

- **LLM 全走 registry**：`get_llm_client("backtest_observer")`（走 `trading_room_llm_*` 凭证，可让回测跑在 DeepSeek 上）。temperature=0。不 import provider SDK。
- **可复现**：LLM 判断必须缓存，键含 skill SHA-256 版本，skill 变则失效重算。无缓存命中才调 LLM；命中直接返回。
- **数字来自确定性代码**：LLM 只给方向/确认/regime/take-profit tightness，不给金额比例。gain-ladder 阈值（+X%/+Y%）从 config/skill 读，LLM 不造数。
- **风险出口永远最高优先**：跌破观察进行中或已触发时，止盈不抢（卖侧两层优先级见 §11.1）。
- **per-sector regime**：signal-ETF 代表赛道，regime 按赛道判（科技牛、同期其他熊），不是账户级一刀切。
- **引擎 async**：`run()` 改 `async def`；API 与测试随之改 async（pytest-asyncio）。
- **测试不真调 LLM**：用 fake LLM client + fake skill registry。每个 task 结束 `cd backend && python3 -m pytest tests/backtest/ tests/test_backtest_*.py -q` 全绿。不跑全量套件（real-data 测试会挂）。
- **只 `git add` backtest 文件**，不碰工作区遗留的 conversational-trading-room 文件。不 push。

---

## File Structure

### 新增
- `backend/app/backtest/observation/llm_judge.py` - `LLMObserverJudge`
- `backend/app/backtest/observation/prompts.py` - judge prompt 构建（窗口 bars + 维度数据 + skill 内容）
- `backend/app/backtest/observation/cache.py` - `ObservationCache`（持久，落 SQLite）
- `backend/app/backtest/observation/regime.py` - `SectorRegimeProvider`（skill + signal-ETF 趋势）
- `backend/app/backtest/volume_threshold.py` - `VolumeThresholdProvider`（skill 一次性给放量倍数）
- `backend/app/backtest/profit_taking.py` - 止盈策略：`TrailingTakeProfit`（牛）+ `GainLadderTakeProfit`（熊）
- `backend/app/models/backtest.py` - `ObservationCacheRecord` ORM（若缓存落库）
- 测试：`tests/backtest/test_llm_judge.py`、`test_cache.py`、`test_regime.py`、`test_volume_threshold.py`、`test_profit_taking.py`

### 修改
- `backend/app/backtest/engine.py` - `run()` 改 async；接 `LLMObserverJudge`+cache；卖侧两层重构；买侧 regime 降档接上（去硬编码 neutral）
- `backend/app/backtest/strategy.py` - 止盈按 regime 分牛/熊；gain-ladder 批次选择
- `backend/app/backtest/observation/judge.py` - `DeterministicJudge` 保留作 fallback/测试
- `backend/app/backtest/strategy_compiler_agent.py` - 改走 `get_llm_client(role)`，删 httpx 直打
- `backend/app/api/v1/backtest.py` - `await engine.run(...)`
- `backend/app/backtest/presets.py` - per-sector gain-ladder 阈值
- `backend/app/backtest/models.py` - gain-ladder 阈值字段、observer role 配置
- `backend/tests/test_backtest_engine.py` / `test_backtest_api.py` - 改 async + 适配

---

## 任务清单概览

- **1a LLM judge 基础**：1 LLMObserverJudge+prompt / 2 ObservationCache / 3 引擎 async + 接 judge+cache
- **1b 卖侧重构**：4 SectorRegimeProvider / 5 两层卖框架 + 风险出口优先 / 6 牛 trailing + 熊 gain-ladder / 7 阈值外置
- **1c 收尾**：8 买侧 regime 降档 / 9 VolumeThresholdProvider / 10 compiler 走 registry / 11 测试 + 回归

---

## Task 1: LLMObserverJudge + prompt 构建

**Files:** `observation/llm_judge.py`、`observation/prompts.py` | Test: `tests/backtest/test_llm_judge.py`

**Interfaces:**
- Consumes: `ObservationJudge` Protocol（Phase 0 已建）、`TriggerPoint`、`ObservationJudgment`、`get_llm_client("backtest_observer")`、`TradingSkillRegistry.load("batch-trading-buy-signal")` 等
- Produces:
  - `class LLMObserverJudge`：`async def judge(trigger, window_bars, config, *, all_bars=None) -> ObservationJudgment`
  - prompt 包含：触发类型+日 T、窗口 [T+1,T+2] bars、维度数据（趋势修复/量能健康/站稳状态真实值；半真/假维度标 `data_status`）、skill 内容（`<verified_skill sha256>`）、放量判定依据
  - 输出结构化 JSON：`{decision, confirmed, dimensions:[{name,passed,reason,data_status}], reasons, confidence, regime?, take_profit_tightness?}`
  - 解析失败重试一次，仍失败 -> 返回 `ObservationJudgment(decision="hold", confirmed=False, gate="unavailable")`，不抛

- [x] **Step 1: 写失败测试（FakeLLMClient 固定输出）** - confirmed=true/false/hold/解析失败四路径
- [x] **Step 2: 跑确认失败**
- [x] **Step 3: 实现 prompts.py + llm_judge.py** - temperature=0，`response_format={"type":"json_object"}`
- [x] **Step 4: 测试通过**
- [x] **Step 5: 提交** `feat: add LLMObserverJudge with structured skill-bound prompts`

---

## Task 2: ObservationCache（持久）

**Files:** `observation/cache.py`、`models/backtest.py`（ORM） | Test: `tests/backtest/test_cache.py`

**Interfaces:**
- Produces:
  - `class ObservationCache`：`async def get(key) -> ObservationJudgment | None`、`async def put(key, judgment, skill_versions)`
  - 缓存键 = hash(`symbol + trigger_date + window_context_hash + skill_versions_sha`）
  - 落 SQLite（复用 `data/financial.db` 或独立 `data/backtest_cache.db`），跨次回测复现
- skill 版本变 -> 键变 -> 自动失效重算

- [x] **Step 1: 写失败测试** - put 后 get 命中；skill 版本变后不命中；未 put 返回 None
- [x] **Step 2-5: 实现 + 测试 + 提交** `feat: add persistent ObservationCache keyed by skill versions`

---

## Task 3: 引擎 async + 接 LLMObserverJudge + cache

**Files:** `engine.py`、`api/v1/backtest.py`、测试 | 注意：高风险

**目标：**
- `BacktestEngine.run` 改 `async def`；API `await` 它；测试改 `pytest.mark.asyncio`。
- 引擎构造 `LLMObserverJudge` + `ObservationCache`，替换 `DeterministicJudge`（保留 DeterministicJudge 作 `judge_fallback` 或仅测试用）。
- 观察期末：先查 cache，命中直接用；未命中调 `await judge.judge(...)`，写 cache，再用。
- 三遍架构（spec §3.1）：Pass 1 扫触发 -> Pass 2 批量调 judge 落 cache -> Pass 3 确定性重放读 cache。Phase 1 可先做"循环内 await judge + cache"（非显式三遍），显式三遍抽离留到性能需要时。

- [x] **Step 1: 写失败测试** - fake judge + real cache：首次跑调 judge、写 cache；再次跑命中 cache 零调用，结果一致
- [x] **Step 2: 跑确认失败**（同步 run 无法 await）
- [x] **Step 3: 改 async** - run/execute_pending/相关方法 async；API await；测试 async
- [x] **Step 4: 接 judge+cache**
- [x] **Step 5: 全 backtest 测试绿**
- [x] **Step 6: 提交** `feat: make engine async and use LLMObserverJudge with cache`

---

## Task 4: SectorRegimeProvider（per-sector regime）

**Files:** `observation/regime.py` | Test: `tests/backtest/test_regime.py`

**Interfaces:**
- Consumes: `batch-trading-market-regime` skill（带 signal-ETF 赛道上下文）、signal_bars 趋势（MA/MACD/回撤）
- Produces:
  - `class SectorRegimeProvider`：`async def assess(symbol, signal_bars, as_of_index) -> SectorRegime`
  - `SectorRegime`：`state: Literal["bull","neutral","bear"]`、`take_profit_tightness: Literal["loose","normal","tight"]`、`reason`、`skill_versions`
  - 调 skill 时传入 signal-ETF 的趋势/回撤/量能作为"target-sector relative strength"输入，让 skill 输出 per-sector 判断（skill 本身账户级，但吃赛道输入）
  - skill 不可用 -> 用 signal-ETF 自身趋势（MA20/60 + 回撤深度）确定性兜底，标 `source="fallback_trend"`

- [x] **Step 1: 写失败测试** - fake skill 返回 bull/tight -> SectorRegime 正确；skill 不可用 -> 趋势兜底
- [x] **Step 2-5: 实现 + 测试 + 提交** `feat: add SectorRegimeProvider using market-regime skill`
- [x] **核对**：读 `~/.codex/skills/batch-trading-market-regime/SKILL.md`，确认其 inputs 能吃 signal-ETF 赛道数据；若不能，扩展 skill 的 references 或在 provider 里把赛道趋势拼进 prompt

---

## Task 5: 卖侧两层框架 + 风险出口优先

**Files:** `engine.py`、`profit_taking.py` | Test: `tests/backtest/test_profit_taking.py`

**目标：**
- 卖侧拆两层：风险出口（放量跌破 observe，Phase 0 已实现）+ 止盈（regime 驱动）。
- **优先级**：风险出口进行中（sell_observation 窗口内）或当日已触发风险出口 -> **压制止盈**，不抢。
- 止盈层在趋势未破时独立触发，不依赖跌破观察。

- [x] **Step 1: 写失败测试** - 跌破观察进行中时，止盈信号被压制（不卖）；趋势未破时止盈正常触发
- [x] **Step 2-5: 实现 + 测试 + 提交** `feat: two-layer sell with risk-exit priority over profit-taking`

---

## Task 6: 牛 trailing + 熊 gain-ladder 止盈

**Files:** `profit_taking.py`、`strategy.py`、`presets.py`、`models.py` | Test: `tests/backtest/test_profit_taking.py`

**Interfaces:**
- `class TrailingTakeProfit`（牛）：批次峰值回撤 >= `trailing_drawdown_pct` -> 卖一个批次（复用现有 `profit_drawdown` 逻辑，但 regime=bull 才用，阈值偏松）
- `class GainLadderTakeProfit`（熊）：批次浮盈达 ladder 第一档（如 +20%）-> 卖一个批次，剩余继续跑；达下一档（+30%）再卖一批；**不等回撤**。档位 per-sector（presets 配置）
- 卖一个批次 = 卖一个 `HoldingBatch` 档位（沿用 `_select_batches_to_sell` 的批次选择）
- `BacktestConfig` 增 `gain_ladder_thresholds: tuple[float,...]`（per-sector，presets 里设）

- [x] **Step 1: 写失败测试**
  - 牛市 + 批次浮盈 +15% 回撤到阈值 -> trailing 卖
  - 熊市 + 批次浮盈 +20% -> gain-ladder 卖一批；+30% 再卖一批；中间不卖
  - 牛市不用 gain-ladder，熊市不用 trailing
- [x] **Step 2-5: 实现 + 测试 + 提交** `feat: regime-conditional profit-taking (bull trailing, bear gain-ladder)`

---

## Task 7: 阈值外置（解魔法数）

**Files:** `models.py`、`presets.py`、`engine.py`、`profit_taking.py`

**目标：** 把 review #7 标的引擎方法体里的魔法数（`_CORE_HARD_CAP_PEAK=40`、tier 阈值 40/10·15/8·10/1.5、批次止盈 3/3·5/4·8/5·15/6、`near_cost_line_pct=1.5`、retention_rates 等）外置到 `BacktestConfig` / presets，按赛道配置。gain-ladder 阈值、trailing 回撤% 一并外置。

- [x] **Step 1: 写测试** - config 改阈值 -> 引擎行为跟着变（证明不再硬编码）
- [x] **Step 2: 外置** - 移到 config 字段 + presets 设值；引擎/profit_taking 读 config
- [x] **Step 3: 测试 + 提交** `refactor: externalize backtest thresholds to config/presets`

---

## Task 8: 买侧 regime 降档（去硬编码 neutral）

**Files:** `engine.py`、`strategy.py`

**目标：** Phase 0 把 `buy_confirmation` 的 `market_regime` 硬编码成 `"neutral"`、`signal_level` 硬编码 `"strong_buy"`，导致 `_decide_buy` 的 bear 降档（buy_scale 0.7）失效。本 task 用 `SectorRegimeProvider` 真实 regime 替换硬编码；signal_level 分级留到 LLM judge 输出（若 judge 输出 dimensions.passed_count 可推导 level，否则继续 strong_buy）。

- [x] **Step 1: 写测试** - bear regime + 买确认 -> buy_scale 降档（买更少）；bull -> 全仓
- [x] **Step 2: 去 hardcode，接 regime provider**
- [x] **Step 3: 测试 + 提交** `feat: wire sector regime into buy sizing (remove hardcoded neutral)`

---

## Task 9: VolumeThresholdProvider（skill 给放量倍数）

**Files:** `volume_threshold.py`、`engine.py`/`trigger_scanner.py` | Test: `tests/backtest/test_volume_threshold.py`

**Interfaces:**
- `class VolumeThresholdProvider`：`async def get(symbol, side) -> float`（side=buy/sell）
- 一次性（per 回测）调 skill 给买/卖放量倍数，替换 `config.buy_volume_ratio`/`breakdown_volume_ratio` 硬编码
- skill 不可用 -> 回退 config 默认值，标 `source="fallback_config"`

- [x] **Step 1: 写测试** - fake skill 返回 1.5 -> TriggerScanner 用 1.5；不可用 -> config 默认
- [x] **Step 2-5: 实现 + 测试 + 提交** `feat: skill-provided volume thresholds for trigger scanner`

---

## Task 10: strategy_compiler_agent 改走 registry

**Files:** `strategy_compiler_agent.py` | Test: `tests/test_backtest_*`（现有 compiler 测试）

**目标：** 删 `AnthropicStrategyCompilerClient` 的 httpx 直打，改用 `get_llm_client(role)`（新角色如 `strategy_compiler` 或复用 `backtest_observer`）。修掉 review #9（绕过 registry、钉死 Anthropic）。

- [x] **Step 1: 改实现** - `StrategyCompilerAgent` 用 `get_llm_client` 的 `chat()`
- [x] **Step 2: 现有 compiler 测试改 fake client 适配 registry 接口**
- [x] **Step 3: 测试 + 提交** `refactor: route strategy compiler through LLM registry`

---

## Task 11: 回归 + 契约测试 + 真实数据 smoke

**Files:** 各测试 | Run: 全 backtest 套件

- [x] **Step 1: 全 backtest 测试绿**（async 适配后）
- [x] **Step 2: 契约测试**
  - LLM judge 缓存命中 -> 重跑结果一致（可复现）
  - 牛市 trailing 止盈、熊市 gain-ladder 止盈、风险出口优先
  - 买侧 bear 降档
  - regime 随时间变（同回测内牛转熊）
- [x] **Step 3: 真实数据 smoke**（可选，需 LLM 凭证）- 跑一个 ETF 预设，确认卖侧 gain-ladder 真触发、churn 比Phase 0 降
- [x] **Step 4: 提交** `test: phase1 regression and contract tests`

---

## 依赖与风险

- **引擎 async 改造面大**：`run()` async 会传染到 execute_pending/_detect_* 等方法和所有测试。Task 3 是高风险核心，先做最小 async + judge+cache，再逐步迁。
- **LLM 可复现**：缓存是硬约束，没缓存回测不可信。Task 2/3 必须保证同输入同输出。
- **per-sector regime skill**：`batch-trading-market-regime` 当前账户级，Task 4 需确认它能吃 signal-ETF 赛道输入；若不能，扩展 skill 或用 signal-ETF 趋势兜底。
- **卖侧两层优先级**：风险出口压制止盈的逻辑要小心别把合法止盈也压了（只在跌破观察进行中/已触发时压）。
- **成本**：每个触发窗口 1 次 LLM 调用 + regime 评估。regime 随时间变需按窗口评估，缓存键含日期。稀疏触发下量级可接受。
- **DeepSeek 结构化输出**：judge 输出 schema 较复杂，失败语义重试一次->标 unavailable->hold。
- **Phase 1 不做**：多标的组合、数据可信边界接入、引擎上帝类拆分、metrics benchmark--留 Phase 2。
