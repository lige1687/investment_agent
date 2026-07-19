# 回测两层观察期模型 Implementation Plan（Phase 0）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把回测买/卖从"硬编码观察期 + 复查错对象 + 卖点顺序反"改成"L1 机械触发(放量+15EXPMA) -> 2 天观察 -> 判定 -> T+3 成交"的两层模型骨架。Phase 0 用**确定性占位 judge**(窗口内站稳/稳定跌破即 confirmed)，不依赖 LLM，先解封强买点、修正卖点顺序，为 Phase 1 接 LLM 铺好接口。

**Architecture:** 新增两个纯模块 `TriggerScanner`(L1 触发扫描)与 `ObservationJudge`(观察判定，Phase 0 给 `DeterministicJudge` 实现)。引擎 `run()` 在现有回放循环内改造买/卖两条路：买触发不再走 5 维门槛、改用 TriggerScanner；观察期末改调 judge 复查"站稳"；卖触发改为"先观察 2 天确认稳定跌破再卖"(覆盖现行的当天即卖)。买/卖都 T+3 成交。TriggerScanner 与 Judge 抽成独立模块，Phase 1 时把 judge 换成 LLM 实现 + 抽出 Pass 2 缓存即可，无需再动引擎循环。

**Tech Stack:** Python 3.11 + dataclasses + pytest + pytest-asyncio。Phase 0 零 LLM、零外部依赖。

**Design spec:** `docs/superpowers/specs/2026-07-16-backtest-two-layer-observation-design.md`

## Global Constraints

- **Phase 0 不接 LLM**：观察判定用 `DeterministicJudge`（纯函数）。`ObservationJudge` 是 Protocol，Phase 1 换 LLM 实现时引擎零改动。
- **MA 口径统一**：买/卖触发与观察复查都用 `config.expma_window`（15，EXPMA），不再买侧 MA20、卖侧 EXPMA15。`policy.py` 内部维度计算可暂保留原 MA，仅作 L2 数据准备，不参与触发。
- **放量阈值**：Phase 0 沿用 `config.buy_volume_ratio` / `config.breakdown_volume_ratio`（占位）。Phase 1 由 `VolumeThresholdProvider`(skill) 替换。
- **执行时序**：T 日收盘检测触发 -> T+1..T+2 观察 -> T+2 末判定 -> T+3 成交。观察窗口不完整(触发临近末段 bar) -> `gate=incomplete_window` hold，不成交。
- **数字来自确定性代码**：judge 只给方向(buy/sell/hold) + confirmed；金额/比例仍由 `strategy.py`(`ratio_of_position` / 目标仓位) 算。
- **可见门禁**：所有 hold 分支记录 `gate` 字段（`observation_not_confirmed` / `target_reached` / `min_trade_floor` / `account_risk` / `incomplete_window`），不再静默吞单。
- **批次系统保留**：核心仓/确认仓/高位仓的记账与卖出选择逻辑(`_select_batches_to_sell` 等)不动，只改触发与判定时序。批次分级保护的硬编码阈值清理由 Phase 2 处理。
- **测试双端全绿**：`cd backend && python3 -m pytest tests -q` 每个 task 结束前必须通过。
- **提交信息**：短命令式主题，如 `feat: add TriggerScanner for L1 mechanical signals`；每个 task 独立提交。

---

## File Structure

### 新增文件
- `backend/app/backtest/trigger_scanner.py` - L1 机械触发扫描（放量+15EXPMA 穿越）
- `backend/app/backtest/observation/__init__.py`
- `backend/app/backtest/observation/schemas.py` - `ObservationJudgment` 等模型
- `backend/app/backtest/observation/judge.py` - `ObservationJudge` Protocol + `DeterministicJudge`
- `backend/tests/backtest/__init__.py`（若不存在）
- `backend/tests/backtest/test_trigger_scanner.py`
- `backend/tests/backtest/test_judge.py`

### 修改文件
- `backend/app/backtest/engine.py` - 买/卖两条路改造、删 `buy_cooldown` 死代码、加 `gate`、修末段窗口
- `backend/app/backtest/events.py` - `_detect_buy_candidate` 触发口径改 mechanical（或由 TriggerScanner 取代触发职责）
- `backend/app/backtest/strategy.py` - 清理 `buy_candidate` 的死规则分支；卖出比例逻辑保留
- `backend/tests/test_backtest_engine.py` - 受影响用例改写为新时序断言

### 保留不动
- `policy.py`（5 维维度计算，后续作 L2 数据输入；Phase 0 不再当触发门槛）
- `fees.py` / `indicators.py` / `models.py`（仅可能加注释或复用 `expma_window`）
- `presets.py` / `fund_nav_data.py` / `westock_data.py` / API 层

---

## 任务清单概览

1. `TriggerScanner`（L1 机械触发，纯模块）
2. `ObservationJudge` Protocol + `DeterministicJudge`（Phase 0 占位判定）
3. 引擎买路改造（trigger -> 2 天观察 -> judge -> T+3 买）+ 删 `buy_cooldown` 死代码
4. 引擎卖路改造（trigger -> 2 天观察 -> judge -> T+3 卖，覆盖当天即卖）
5. 可见门禁 `gate` + 末段不完整窗口处理
6. 回归测试改写 + 契约测试
7.（可选）死参数标注 deprecated

---

## Task 1: TriggerScanner（L1 机械触发）

**Files:**
- Create: `backend/app/backtest/trigger_scanner.py`
- Test: `backend/tests/backtest/test_trigger_scanner.py`

**Interfaces:**
- Consumes: `SignalBar`、`BacktestConfig`（`expma_window`、`buy_volume_ratio`、`breakdown_volume_ratio`、`buy_volume_window`）
- Produces:
  - `@dataclass(frozen=True) class TriggerPoint`：`kind: Literal["buy","sell"]`、`index: int`、`date: date`
  - `class TriggerScanner`：`__init__(config)`；`scan(bars: list[SignalBar]) -> list[TriggerPoint]`
  - 触发规则：
    - buy：`closes[i-1] <= expma[i-1] and closes[i] > expma[i]`（站上）且 `volume_ratio[i] >= config.buy_volume_ratio`
    - sell：`closes[i-1] >= expma[i-1] and closes[i] < expma[i]`（跌破）且 `volume_ratio[i] >= config.breakdown_volume_ratio`
  - EXPMA 与 volume_ratio 用 `indicators.expma` / `indicators.volume_ratio`，窗口取 `config.expma_window` / `config.buy_volume_window`
  - 数据不足(index < max window) 时不触发；`None` 量比不触发

- [ ] **Step 1: 写失败测试**

`backend/tests/backtest/test_trigger_scanner.py`：

```python
from datetime import date, timedelta
from app.backtest.trigger_scanner import TriggerScanner, TriggerPoint
from app.backtest.models import BacktestConfig, SignalBar


def _bar(i, close, vol=100.0, prev_close=None):
    return SignalBar(
        date=date(2026, 1, 1) + timedelta(days=i),
        open=prev_close or close, high=close + 1, low=close - 1,
        close=close, volume=vol, amount=None,
    )


def _config():
    return BacktestConfig(
        fund_code="x", fund_name="x", signal_code="x", signal_name="x",
        expma_window=15, buy_volume_window=10,
        buy_volume_ratio=1.2, breakdown_volume_ratio=1.5,
    )


def _bars_crossing_up_above_ma():
    """构造一段先在 EXPMA 下方、后放量站上的序列。"""
    bars = []
    base = 10.0
    for i in range(40):
        bars.append(_bar(i, base))            # 平盘，让 EXPMA 收敛到 base 附近
    # 第 40 天放量站上
    bars.append(_bar(40, base + 2.0, vol=500.0, prev_close=base))
    return bars


def test_buy_trigger_emitted_on_volume_breakout_above_ma():
    scanner = TriggerScanner(_config())
    triggers = scanner.scan(_bars_crossing_up_above_ma())
    buys = [t for t in triggers if t.kind == "buy"]
    assert len(buys) >= 1
    assert buys[-1].index == 40
    assert isinstance(buys[-1], TriggerPoint)


def test_no_trigger_without_volume():
    bars = _bars_crossing_up_above_ma()
    bars[-1] = _bar(40, bars[-1].close, vol=50.0, prev_close=bars[-2].close)  # 缩量
    scanner = TriggerScanner(_config())
    triggers = scanner.scan(bars)
    assert not [t for t in triggers if t.kind == "buy" and t.index == 40]


def test_sell_trigger_emitted_on_volume_breakdown_below_ma():
    bars = []
    base = 10.0
    for i in range(40):
        bars.append(_bar(i, base))
    bars.append(_bar(40, base - 2.0, vol=600.0, prev_close=base))  # 放量跌破
    scanner = TriggerScanner(_config())
    triggers = scanner.scan(bars)
    sells = [t for t in triggers if t.kind == "sell" and t.index == 40]
    assert len(sells) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python3 -m pytest tests/backtest/test_trigger_scanner.py -q`
Expected: ImportError / FAILED

- [ ] **Step 3: 实现 TriggerScanner**

实现 `trigger_scanner.py`：按上述规则遍历 bars，返回按时序排列的 `TriggerPoint` 列表。注意 `expma` 的 seed 用 `values[0]`、`volume_ratio` 当 `index < window` 返回 None。

- [ ] **Step 4: 测试通过**

Run: `cd backend && python3 -m pytest tests/backtest/test_trigger_scanner.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/backtest/trigger_scanner.py backend/tests/backtest/test_trigger_scanner.py
git commit -m "feat: add TriggerScanner for L1 mechanical buy/sell signals"
```

---

## Task 2: ObservationJudge Protocol + DeterministicJudge

**Files:**
- Create: `backend/app/backtest/observation/__init__.py`
- Create: `backend/app/backtest/observation/schemas.py`
- Create: `backend/app/backtest/observation/judge.py`
- Test: `backend/tests/backtest/test_judge.py`

**Interfaces:**
- Consumes: `TriggerPoint`、`SignalBar`、`BacktestConfig`（`expma_window`）
- Produces:
  - `@dataclass(frozen=True) class ObservationJudgment`：`decision: Literal["buy","sell","hold"]`、`confirmed: bool`、`reason: str`、`gate: str | None = None`（`gate` 仅在 hold 时填，如 `observation_not_confirmed` / `incomplete_window`）
  - `class ObservationJudge(Protocol)`：`judge(trigger: TriggerPoint, window_bars: list[SignalBar], config) -> ObservationJudgment`
  - `class DeterministicJudge`：Phase 0 占位实现
    - buy：窗口内每个 bar 的 `close >= expma[该日]`（站稳不跌破）-> confirmed=True, decision="buy"；任一日跌破 -> confirmed=False, decision="hold", gate="observation_not_confirmed"
    - sell：窗口内每个 bar 的 `close <= expma[该日]`（稳定跌破不回踩）-> confirmed=True, decision="sell"；任一日站回 -> confirmed=False, decision="hold", gate="observation_not_confirmed"
    - 窗口 bars 不足（少于观察天数）-> decision="hold", confirmed=False, gate="incomplete_window"
  - 观察天数常量 `OBSERVATION_DAYS = 2`（Phase 0 固定；Phase 1 可配置化）

- [ ] **Step 1: 写失败测试**

`backend/tests/backtest/test_judge.py`：

```python
from datetime import date, timedelta
from app.backtest.observation.judge import DeterministicJudge, OBSERVATION_DAYS
from app.backtest.observation.schemas import ObservationJudgment
from app.backtest.trigger_scanner import TriggerPoint
from app.backtest.models import BacktestConfig, SignalBar


def _bar(i, close, vol=100.0):
    return SignalBar(date=date(2026,1,1)+timedelta(days=i), open=close,
                     high=close+1, low=close-1, close=close, volume=vol, amount=None)


def _cfg():
    return BacktestConfig(fund_code="x", fund_name="x", signal_code="x",
                          signal_name="x", expma_window=15)


def test_buy_confirmed_when_window_holds_above_ma():
    # 触发日站上后，T+1/T+2 仍站稳
    bars = [_bar(i, 12.0) for i in range(43)]   # 收敛后站上
    trigger = TriggerPoint(kind="buy", index=40, date=bars[40].date)
    j = DeterministicJudge().judge(trigger, bars[41:41+OBSERVATION_DAYS], _cfg())
    assert j.confirmed is True
    assert j.decision == "buy"


def test_buy_not_confirmed_when_window_falls_back_below_ma():
    bars = [_bar(i, 12.0) for i in range(43)]
    bars[41] = _bar(41, 8.0)   # T+1 跌回 MA 下方
    trigger = TriggerPoint(kind="buy", index=40, date=bars[40].date)
    j = DeterministicJudge().judge(trigger, bars[41:43], _cfg())
    assert j.confirmed is False
    assert j.decision == "hold"
    assert j.gate == "observation_not_confirmed"


def test_incomplete_window_holds():
    trigger = TriggerPoint(kind="buy", index=40, date=date(2026,2,10))
    j = DeterministicJudge().judge(trigger, [_bar(41, 12.0)], _cfg())  # 只有 1 天
    assert j.decision == "hold"
    assert j.gate == "incomplete_window"


def test_sell_confirmed_when_window_stays_below_ma():
    bars = [_bar(i, 8.0) for i in range(43)]
    trigger = TriggerPoint(kind="sell", index=40, date=bars[40].date)
    j = DeterministicJudge().judge(trigger, bars[41:43], _cfg())
    assert j.confirmed is True
    assert j.decision == "sell"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python3 -m pytest tests/backtest/test_judge.py -q`
Expected: ImportError / FAILED

- [ ] **Step 3: 实现 schemas + judge**

`schemas.py` 定义 `ObservationJudgment`；`judge.py` 定义 Protocol、`OBSERVATION_DAYS=2`、`DeterministicJudge`。EXPMA 在窗口内重新计算（用触发日前含的全部 closes 作 seed，或传入预计算序列--实现时任选其一并保持测试通过）。

- [ ] **Step 4: 测试通过**

Run: `cd backend && python3 -m pytest tests/backtest/test_judge.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/backtest/observation backend/tests/backtest/test_judge.py
git commit -m "feat: add ObservationJudge protocol and DeterministicJudge placeholder"
```

---

## Task 3: 引擎买路改造 + 删 buy_cooldown 死代码

**Files:**
- Modify: `backend/app/backtest/engine.py`
- Modify: `backend/app/backtest/events.py`（触发口径）
- Test: `backend/tests/test_backtest_engine.py`

**目标行为：**
- 买触发改用 `TriggerScanner` 的 buy 触发点（放量站上 15EXPMA），**不再要求 5 维 ≥3**。`EventDetector` 不再发 `buy_candidate`（或 `buy_candidate` 改由 TriggerScanner 结果生成，不含 5 维门槛）。
- 触发后进 2 天观察期（沿用现有 `buy_observation_*` 状态变量，`until_index = index + OBSERVATION_DAYS`）。
- 观察期末调 `DeterministicJudge.judge(buy_trigger, window_bars, config)`：
  - `confirmed=True` -> 生成 `buy_confirmation` -> `strategy._decide_buy` -> pending -> **T+1 成交（相对观察末日）= T+3 相对触发日**。
  - `confirmed=False` -> 记 `gate=observation_not_confirmed` 的 hold 事件，**不买**。
- 删除 `engine.py` 中 `buy_cooldown_until_index`（初始化 122 行 + 不可达写入 278-279 行）。
- 删除 `strategy.py` 中 `buy_candidate` 分支的"强买立即执行 observe_days=0"等死规则（非 test 模式从不调用）；`_decide_buy` 的 `min_trade_floor` / `target_reached` hold 保留，但补 `gate` 字段（Task 5 统一加）。

**Interfaces:**
- Consumes: `TriggerScanner`、`DeterministicJudge`、`OBSERVATION_DAYS`
- Produces: 引擎买路新时序；`buy_candidate` 事件 details 增加 `trigger` 信息；hold 事件带 `gate`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_backtest_engine.py` 新增（构造一段放量站上 15EXPMA 后站稳的 fund_nav + signal_bars）：

```python
def test_buy_trigger_fills_on_T_plus_3_when_observation_confirms():
    config = _config_for_breakout()           # helper：放量站上 + 站稳的序列
    fund_nav, signal_bars = _build_breakout_series(confirmed=True)
    result = BacktestEngine().run(config, fund_nav, signal_bars)
    buys = [t for t in result.trades if t.action == "buy"]
    assert len(buys) == 1
    # 触发日 T -> 成交日 = T + 3
    trigger_date = _first_buy_trigger_date(signal_bars, config)
    assert buys[0].date == trigger_date + timedelta(days=3)


def test_buy_not_confirmed_does_not_buy_and_records_gate():
    fund_nav, signal_bars = _build_breakout_series(confirmed=False)  # T+1 跌回
    config = _config_for_breakout()
    result = BacktestEngine().run(config, fund_nav, signal_bars)
    assert not [t for t in result.trades if t.action == "buy"]
    gates = [e for e in result.events if e.get("details", {}).get("gate") == "observation_not_confirmed"]
    assert gates
```

（helper `_build_breakout_series` / `_first_buy_trigger_date` 用 TriggerScanner 的同一套序列生成逻辑，确保触发点可预期。）

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python3 -m pytest tests/test_backtest_engine.py -q`
Expected: FAILED（当前引擎不按 T+3 成交、或不买）

- [ ] **Step 3: 改造引擎买路**

- 在 `run()` 开头构造 `TriggerScanner(config)` + `DeterministicJudge()`。
- 买触发：用 TriggerScanner 预扫出 buy 触发点集合，或每日检查当日是否为 buy 触发。触发后设观察期状态。
- 观察期末（`index == buy_observation_until_index`）：取窗口 bars 调 `judge`。confirmed -> 生成 `buy_confirmation`（details 带 `market_regime` 等仍可保留给 `_decide_buy`）；不 confirmed -> 记 hold 事件 `gate=observation_not_confirmed`，清除观察状态。
- 删除 `buy_cooldown_until_index` 全部出现。
- `EventDetector._detect_buy_candidate`：移除 5 维门槛依赖，或直接让引擎用 TriggerScanner 取代该事件（二选一，保持 test_backtest_events.py 若有相关用例同步改）。

- [ ] **Step 4: 测试通过**

Run: `cd backend && python3 -m pytest tests/test_backtest_engine.py tests/backtest/ -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/backtest/engine.py backend/app/backtest/events.py backend/tests/test_backtest_engine.py
git commit -m "feat: rewire buy path to trigger + 2-day observation + judge (T+3 fill)"
```

---

## Task 4: 引擎卖路改造（先观察 2 天再卖，覆盖当天即卖）

**Files:**
- Modify: `backend/app/backtest/engine.py`
- Modify: `backend/app/backtest/strategy.py`
- Test: `backend/tests/test_backtest_engine.py`

**目标行为：**
- 卖触发：`TriggerScanner` 的 sell 触发点（放量跌破 15EXPMA）。沿用现 `_detect_technical_breakdown` 的穿越判定口径（已被 TriggerScanner 覆盖）。
- 触发后进 **2 天观察期（新增卖侧观察状态变量 `sell_observation_*`）**，**当日不卖**。
- 观察期末调 `DeterministicJudge.judge(sell_trigger, window_bars, config)`：
  - `confirmed=True`（稳定跌破、无回踩）-> `strategy.decide` 产出 sell（`ratio_of_position` 沿用现有 0.5 / 止损 1.0）-> pending -> T+3 成交。批次选择 `_select_batches_to_sell` 保留。
  - `confirmed=False`（回踩站回 MA 上方）-> 记 `gate=observation_not_confirmed` hold，**不卖**。
- 删除/改写原"跌破当天立即卖 50% + post_sell_observation 决定加卖"的即时卖出分支。`post_sell_observation`（已卖后是否继续卖）本期可保留为独立机制，但**首次卖出必须等观察确认**。

**Interfaces:**
- Consumes: `TriggerScanner`、`DeterministicJudge`、现有批次选择逻辑
- Produces: 卖路新时序（T+3 卖）；卖侧 hold 事件带 `gate`

- [ ] **Step 1: 写失败测试**

```python
def test_sell_trigger_fills_on_T_plus_3_after_observation_confirms():
    config = _config_for_breakdown()
    fund_nav, signal_bars = _build_breakdown_series(confirmed=True)  # 放量跌破 + 稳定跌破
    result = BacktestEngine().run(config, fund_nav, signal_bars)
    sells = [t for t in result.trades if t.action == "sell"]
    assert len(sells) >= 1
    trigger_date = _first_sell_trigger_date(signal_bars, config)
    assert sells[0].date == trigger_date + timedelta(days=3)


def test_sell_not_confirmed_does_not_sell():
    fund_nav, signal_bars = _build_breakdown_series(confirmed=False)  # T+1 回踩站回
    config = _config_for_breakdown()
    result = BacktestEngine().run(config, fund_nav, signal_bars)
    assert not [t for t in result.trades if t.action == "sell"]
    assert [e for e in result.events if e.get("details", {}).get("gate") == "observation_not_confirmed"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python3 -m pytest tests/test_backtest_engine.py -q`
Expected: FAILED（当前卖点是触发当天卖，不是 T+3）

- [ ] **Step 3: 改造引擎卖路**

- 新增卖侧观察状态变量（仿 `buy_observation_*`）：`sell_observation_start_index` / `sell_observation_until_index` / `sell_observation_candidate`。
- 卖触发进观察期；`index == sell_observation_until_index` 时调 judge。confirmed -> 走 `strategy.decide` 生成 sell -> pending -> 次日成交；不 confirmed -> hold + gate。
- 改写 `strategy.py` 中 `technical_breakdown` 分支：仍是 sell + ratio，但**仅在被 judge confirmed 后调用**（引擎控制调用时机，strategy 只给决策）。
- 同步改写现有依赖"当天卖"的测试用例（见 Task 6）。

- [ ] **Step 4: 测试通过**

Run: `cd backend && python3 -m pytest tests/test_backtest_engine.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/backtest/engine.py backend/app/backtest/strategy.py backend/tests/test_backtest_engine.py
git commit -m "feat: rewire sell path to observe-2-days-then-sell (T+3 fill)"
```

---

## Task 5: 可见门禁 gate + 末段不完整窗口处理

**Files:**
- Modify: `backend/app/backtest/engine.py`
- Modify: `backend/app/backtest/strategy.py`（`_decide_buy` hold 分支补 gate）
- Test: `backend/tests/test_backtest_engine.py`

**目标行为：**
- 所有 hold/observe 决策事件 `details` 带 `gate` 字段，枚举：`observation_not_confirmed` / `incomplete_window` / `target_reached` / `min_trade_floor` / `account_risk`。
- `_decide_buy` 的三个 hold 分支（`strategy.py:162-165, 203-204`）补对应 `gate`：`target_reached` / `min_trade_floor`（两处）/ account_risk 分支补 `account_risk`。
- 观察窗口不完整（触发日 + OBSERVATION_DAYS 超出 `len(fund_nav)-1`，或窗口末日 >= 最后一根 bar）-> judge 返回 `gate=incomplete_window`（Task 2 已实现），引擎据此 hold 且**不再因 `engine.py:170` 的 `continue` 丢事件**：把"末段 bar 跳过事件检测"改成"仍记录 incomplete_window hold"或调整边界判定顺序。

**Interfaces:**
- Consumes: `ObservationJudgment.gate`、`_decide_buy` hold 分支
- Produces: 每个 hold 事件可由 `details.gate` 聚合统计

- [ ] **Step 1: 写失败测试**

```python
def test_buy_at_full_position_records_target_reached_gate():
    # 仓位已达 target，强买触发 + 确认 -> 不买，gate=target_reached
    ...
    assert any(e.get("details", {}).get("gate") == "target_reached" for e in result.events)

def test_trigger_near_last_bar_records_incomplete_window():
    # 触发日在倒数第 1-2 根，窗口不完整 -> 不成交，gate=incomplete_window
    ...
    assert any(e.get("details", {}).get("gate") == "incomplete_window" for e in result.events)
    assert not [t for t in result.trades if t.action == "buy"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python3 -m pytest tests/test_backtest_engine.py -q`
Expected: FAILED

- [ ] **Step 3: 补 gate + 修末段边界**

- `StrategyDecision` 增加 `gate: str | None = None`（或事件 `details` 直接写 gate，二选一；优先 `details.gate` 不改 dataclass 形状）。
- `_decide_buy` 各 hold 分支填 gate；`_event_record` 把 `decision.gate`（若有）透传到 `details`。
- 末段：`run()` 中 `if index >= len(fund_nav) - 1: continue`（engine.py:170）改为允许观察期末判定--若该 index 是某观察窗口的 `until_index`，仍执行 judge 并记录结果（含 incomplete_window）。

- [ ] **Step 4: 测试通过**

Run: `cd backend && python3 -m pytest tests/test_backtest_engine.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/backtest/engine.py backend/app/backtest/strategy.py backend/tests/test_backtest_engine.py
git commit -m "feat: add visible gates and incomplete-window handling to backtest holds"
```

---

## Task 6: 回归测试改写 + 契约测试

**Files:**
- Modify: `backend/tests/test_backtest_engine.py`
- Modify: `backend/tests/test_backtest_events.py`（若 buy_candidate 触发口径变了）
- Run: 全量后端测试

**目标：** 现有 `test_backtest_engine.py` 多个用例建立在"卖点当天卖 / 买点 5 维门槛 / 硬编码 2 天观察复查信号强度"上，按新模型改写断言：

| 现有用例（举例） | 改写方向 |
|---|---|
| `test_engine_executes_buy_candidate_on_next_fund_nav_day` | 改为 T+3 成交 |
| `test_engine_sells_high_position_batch_first_after_profit_peak_drawdown` | 卖出延后到观察确认后 T+3 |
| `test_engine_applies_sell_cooldown_after_technical_breakdown` | 卖侧冷却语义随卖路改造调整；若 `sell_cooldown` 已成死代码，用例改写或删除 |
| 各 `core_protection_tier*` 用例 | 批次保护逻辑保留，但触发时序随卖路变；断言成交日 |

- [ ] **Step 1: 跑全量后端测试，列出所有失败用例**

Run: `cd backend && python3 -m pytest tests -q`
Expected: 一批 FAIL（被改写行为的用例）

- [ ] **Step 2: 逐个改写为对新模型的断言**（T+3 时序、观察确认、gate）

- [ ] **Step 3: 全量绿**

Run: `cd backend && python3 -m pytest tests -q`
Expected: 全部 PASS

- [ ] **Step 4: 契约测试补充**（若 Task 3/4/5 已覆盖可跳过）

确保以下契约有用例：
- 强买触发 + 站稳 -> T+3 成交
- 强买触发 + 跌回 -> 不买 + gate
- 卖触发 + 稳定跌破 -> T+3 卖
- 卖触发 + 回踩 -> 不卖 + gate
- 末段触发 -> incomplete_window

- [ ] **Step 5: 提交**

```bash
git add backend/tests/test_backtest_engine.py backend/tests/test_backtest_events.py
git commit -m "test: rewrite backtest engine tests for two-layer observation model"
```

---

## Task 7（可选）: 死参数标注 deprecated

**Files:**
- Modify: `backend/app/backtest/models.py`（注释）
- 不删字段（避免 schema/compiler 测试连锁破坏）

`weak_buy_allows_trade` / `first_entry_plan_ratio` / `sell_cooldown_days` 在 `models.py` 加注释：`# DEPRECATED: 当前不被读取，Phase 2 重接策略文本解析时启用`。Phase 2 决定真接或真删。

- [ ] **Step 1: 加注释**
- [ ] **Step 2: 全量测试仍绿**
- [ ] **Step 3: 提交** `chore: mark unused backtest config fields as deprecated`

---

## Phase 1 / Phase 2 大纲（本期不实现，仅备忘）

**Phase 1（接 LLM）：**
- 新增 `ObservationJudge` 的 LLM 实现 `LLMObserverJudge`，走 `get_llm_client("backtest_observer")`，temperature=0，结构化输出 `ObservationJudgment`。
- 新增 `ObservationCache`：键 `(symbol, trigger_date, window_context_hash, skill_versions)`，持久缓存，跨次复现。
- 新增 `VolumeThresholdProvider`：调 skill 一次性给买/卖放量倍数，替换 `buy_volume_ratio`/`breakdown_volume_ratio`。
- 把 judge 调用抽成显式 Pass 2（预扫所有触发 -> 批量调 LLM 落缓存 -> 引擎重放读缓存）。
- `strategy_compiler_agent.py` 改走 `get_llm_client(role)`，删 httpx 直打。
- 引擎 `run()` 改 async 或用 sync 包裹 async judge。

**Phase 2（数据源 + 清理）：**
- "逻辑/催化"接真实数据源（景气度/公告 skill）。
- "资金回流"接真·主力净流入数据。
- 多标的组合回测（修"组合允许"半真）。
- 引擎上帝类拆分、执行日志不再写临时文件、`meta` 块接入 market-data 可信边界。
- metrics 加 benchmark / Sharpe / 胜率；批次分级阈值清出引擎方法体进 config。

## 依赖与风险

- **行为变更面大**：卖侧从"当天卖"改"先观察再卖"，现有引擎测试需大量改写（Task 6）。Phase 0 先固化新行为、全绿后再上 Phase 1 LLM。
- **买路去 5 维门槛**可能让买点变多--这是预期（用户要的就是别被 5 维卡死）。T+3 延迟不变，但判定有意义。
- **批次系统与观察期耦合**：卖侧观察确认后才进 `_select_batches_to_sell`，需确认批次 peak/return 计算时点仍正确（peak 在观察期内可能变化）。Task 4 实现时验证。
- **EXPMA 重计算开销**：judge 在每个窗口重算 EXPMA，窗口数稀疏，可忽略；若性能有问题，预计算全序列 EXPMA 传入。
