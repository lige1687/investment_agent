# 交易讨论室运行时修复计划（P0 × 2 + 小清理）

## 背景

`agent/p0-data-trust` 分支的讨论室功能链路在测试环境全部通过（318 后端 + 31 前端），但代码审查发现两个会让**生产实际使用断掉**的问题：

1. **账户估值快照只有读没有写**：`AccountValuationService.recent_peak()` 在 `create_session` 被调用，但 `record_confirmed()` / `record_unconfirmed()` 在生产代码中零调用。`account_valuation_snapshots` 表永远为空 → `peak_equity` 永远是 `None` → `account_drawdown_unknown` blocker 永远存在，回撤功能永久失效且用户无感知。
2. **create_session 同步串行阻塞**：HTTP handler 内串行跑最多 8 个 iwencai preflight（每个 timeout 30s）+ 6 个 LLM 角色（每个 timeout 60s × 最多 2 次尝试）。正常情况总时长 ~130s，而前端 `client.ts` timeout 是 120s——真实 DeepSeek 环境下首次讨论大概率超时，且超时后后端还在跑、用户重试会创建重复 session。

本计划只修这两个 P0 加两处小清理。**不做**：chair/recorder 角色接入、create_session 后台任务化改造、`guard_sell` 删除、`get_latest_cash_confirmation` 过滤——这些留给后续迭代。

工作分支：继续在 `agent/p0-data-trust` 上做。

---

## Phase 1 — 补估值快照写入闭环

### 1.1 时区归一化（先做，避免混存）

**问题**：`account_valuation.py` 的 `record_*` 和 `recent_peak` 都用 `.replace(tzinfo=None)` 直接剥时区。但 `create_session` 的 `as_of` 来自浏览器（UTC ISO），`finalize_session` 的 `now` 是 `Asia/Shanghai`——剥掉时区后同表混存两种本地时间，比较会偏 8 小时。

**修改** `backend/app/trading_room/account_valuation.py`：

```python
from datetime import datetime, timedelta, timezone

def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)
```

- `record_confirmed` / `record_unconfirmed`：`captured_at=_naive_utc(captured_at)` 替换现有 `.replace(tzinfo=None)`
- `recent_peak`：`as_of` 同样先过 `_naive_utc` 再算 cutoff

无需数据迁移（该表生产中至今为空）。

### 1.2 create_session 记录未确认快照

**修改** `backend/app/api/v1/trading_room.py` 的 `create_session`，在 `session = await store.create_session(...)` 之后加：

```python
if request.data_mode == "live":
    await AccountValuationService(db).record_unconfirmed(
        session_id=session.id,
        holdings_value=context.holdings_value,
        captured_at=request.as_of,
    )
```

- demo 模式不记录（演示数据不得污染审计历史）
- 未确认快照 `equity=None`、`confidence="UNKNOWN"`，本来就不参与 peak 计算（`recent_peak` 只取 HIGH/MEDIUM 且 equity 非空），纯审计用途

### 1.3 finalize_session 记录已确认快照

**修改** `finalize_session`，在 `if request.execution_funding is not None:` 分支里、`save_funding_confirmation` 之后加：

```python
if context.get("data_mode") == "live":
    portfolio_input = next(
        (item for item in context.get("critical_inputs") or []
         if isinstance(item, dict) and item.get("key") == "portfolio"),
        None,
    )
    trusted = (
        portfolio_input is not None
        and portfolio_input.get("confidence") == "HIGH"
        and not portfolio_input.get("stale")
    )
    await AccountValuationService(db).record_confirmed(
        session_id=session_id,
        holdings_value=float(context.get("holdings_value") or 0),
        cash=funding.available_cash,
        captured_at=now,   # 服务端确认时刻，不用客户端时间
        confidence="HIGH" if trusted else "MEDIUM",
    )
```

设计依据（`docs/plans/2026-07-14-trading-room-progressive-inputs.md`）："用可信的同步持仓市值和当时已确认现金形成账户权益记录，并从连续快照中计算近期峰值"。

已知可接受的行为：
- holdings_value 取自会话不可变快照（讨论时点），finalize 时持仓可能已漂移——设计明确复算基于讨论快照，可接受
- finalize 被调用两次（如先 422 再成功）会产生两条 confirmed 记录——peak 取 max，重复无害

### 1.4 测试

**扩展** `backend/tests/trading_room/test_account_valuation.py`：
- 时区归一化：用 `+08:00` aware datetime 记录、用 UTC aware `as_of` 查询 `recent_peak`，验证纳入窗口且数值正确

**新增到** `backend/tests/trading_room/test_api.py`（复用现有 client fixture 与 `_finalize_payload` helper）：

1. `test_finalize_with_funding_feeds_peak_into_next_session`（端到端闭环，不直接查表）：
   - 导入 fund 001513 目标 30% 政策 → create session（默认 fixture 持仓 001513 市值 20,000）→ finalize 带 `execution_funding.available_cash=20000`
   - 再 create 第二个 session，**`as_of` 用 `NOW + timedelta(days=1)`**（关键：finalize 的 confirmed 时刻晚于 NOW，第二个 session 的 as_of 必须晚于确认时刻才能进 lookback 窗口）
   - 断言第二个 session 的 `context["peak_equity"] == 40000`（20000 持仓 + 20000 现金）
   - 注意：第二个 session 因 `synced_at.date() < as_of.date()` 会带 `critical_input_stale:portfolio` blocker，只影响 `formally_actionable`，不影响 peak 断言
2. `test_demo_session_does_not_record_valuation`：
   - 用 `data_mode="demo"` 创建 session 并 finalize（带 funding）→ 再建一个 live session（as_of 晚一天）→ 断言 `context["peak_equity"] is None`

---

## Phase 2 — 并行化 round-one 讨论与 preflight

### 2.1 orchestrator round-one 并行

**修改** `backend/app/trading_room/orchestrator.py` 的 `TradingRoomOrchestrator.discuss`。现有代码自己注释了 "Sequential execution does not change independence"（每个角色只收同一快照、互不可见），因此可以安全并行：

```python
import asyncio

async def discuss(self, context: TradingContextSnapshot) -> TradingDiscussionResult:
    snapshot_payload = context.model_dump(mode="json")

    async def _run_role(role: str) -> tuple[str, SpecialistRunResult]:
        runner = self._runners.get(role)
        if runner is None:
            return role, _missing_role(role, context.context_hash)
        return role, await runner.run_round_one(
            context_snapshot=snapshot_payload,
            context_hash=context.context_hash,
        )

    pairs = await asyncio.gather(*(_run_role(role) for role in ROUND_ONE_ROUTE))
    round_one = dict(pairs)
    # 后续 conflicts / round_two 逻辑不变（skeptic 依赖全部 round-one 结果，保持串行在 gather 之后）
```

- `gather` 返回顺序与入参一致，`round_one` dict 保持 `ROUND_ONE_ROUTE` 顺序，现有测试的顺序断言不受影响
- 不加 `return_exceptions=True`：`SpecialistRunner._run` 内部已捕获 `LLMError` / `ValidationError` 并返回 UNAVAILABLE，异常向上抛是意外情况，保持与现状一致的传播行为
- LLM client 由 registry 缓存共享，`httpx.AsyncClient` 并发安全

### 2.2 preflight 并行

**修改** `backend/app/api/v1/trading_room.py` 的 `_collect_server_preflights`：把现有 for 循环里的串行 `await _query_preflight(...)` 改为先收集去重后的 `(symbol, name, share_class)` 列表（保留现有 `[:8]` 截断和 `(symbol, share_class)` 去重逻辑），然后：

```python
results = await asyncio.gather(*(
    _query_preflight(PreflightRequest(
        fund_code=symbol, fund_name=name, share_class=share_class,
        customer_scope="retail", channel=request.execution_channel,
        channel_confirmed=False,
    ))
    for symbol, name, share_class in unique_positions
))
return list(results)
```

- 每个 `_query_preflight` 自建 provider 和 httpx client，并发安全
- `AnnouncementProviderError` 已在 `_query_preflight` 内部捕获（返回带 `preflight_error` 的 payload，不抛出），gather 不会被单个失败打断

### 2.3 测试

**新增到** `backend/tests/trading_room/test_orchestrator.py` 一个确定性并发测试：

- 构造两个 fake runner：A 的 `run_round_one` 先 `await event.wait()`，B 的 `run_round_one` 执行 `event.set()`（A 在 ROUND_ONE_ROUTE 中排在 B 前面，如 A=portfolio_risk、B=market_regime）
- 串行执行会死锁，并行执行立即完成
- 整个 `discuss` 调用包在 `asyncio.wait_for(..., timeout=5)` 里，串行实现会 TimeoutError 快速失败

现有 orchestrator / api 测试应全部保持通过（并行不改变结果集）。

### 2.4 预期效果

round-one 从 5×单角色耗时 降到 1×最慢角色；preflight 从 8×串行 降到 1×最慢查询。正常路径总时长从 ~130s 降到 ~40s，脱离前端 120s 超时线。

---

## Phase 3 — 小清理（可选，低风险）

### 3.1 提取 holdings_value 共享计算

`context.py:84-87` 和 `trading_room.py:749-753`（`_guard_inputs_from_context`）用相同公式各算一遍 holdings_value，存在漂移风险。在 `backend/app/trading_room/context.py` 提取：

```python
def compute_holdings_value(positions: list[dict[str, Any]]) -> float:
    return sum(
        max(0.0, float(p.get("market_value") or 0))
        for p in positions
        if isinstance(p, dict)
    )
```

两处调用方改用该函数（`TradingContextBuilder.build` 内部 + `_guard_inputs_from_context`）。行为差异：context.py 原实现没有 `isinstance` 守卫，统一加上（更严格，positions 来自服务端本就是 dict 列表，不影响现有测试）。

### 3.2 前端 create_session 超时富余（可选）

即使并行化后，最坏情况（某角色重试 2 次）仍可能逼近 120s。给 createSession 单独放宽超时，`frontend/src/api/tradingRoom.ts`：

```typescript
createSession: async (payload: SessionCreatePayload) =>
  (await apiClient.post<TradingRoomSession>(
    '/agent/trading-room/sessions', payload, { timeout: 300_000 },
  )).data,
```

---

## 验证

```bash
# 后端：全量测试（原 318 + 新增 ≥4 个全部通过）
cd backend && python3 -m pytest tests/ -q

# 后端：编译检查
cd backend && python3 -m compileall app -q

# 前端：测试 + 构建（31 passed 不变；若做 3.2 需通过 tsc）
cd frontend && npx vitest run && npx tsc -b && npx vite build
```

人工验收（可选，需要 DeepSeek key）：
1. 清空 `data/financial.db` 后启动，同步养基宝持仓
2. 发起一次讨论 → 买入候选出现 → 确认现金 → finalize
3. 次日（或改 as_of）再发起讨论，`ContextSnapshotCard` 的"账户近期峰值"应显示上次确认的权益值而非"历史不足"
4. 观察 create_session 耗时明显下降（服务端日志中 5 个角色的请求应基本同时发出）

## 明确不做（防止范围蔓延）

- chair / recorder 角色接入讨论流程（决策裁决仍暂由前端从 buy memo 提取）
- create_session 拆分为"建会话 → 后台讨论 → 前端轮询"的异步模式
- `LightTradeGuard.guard_sell` 的删除或接入
- `get_latest_cash_confirmation` 的会话/渠道过滤
