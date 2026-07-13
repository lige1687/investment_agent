# 今日交易讨论室渐进式输入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将今日交易讨论室改成自动读取同步持仓的一键入口，只在形成明确买入建议后确认可用现金，并让目标仓位跨日持续沿用。

**Architecture:** 讨论上下文把“分析可信”与“金额可执行”拆成两个状态；现金和账户峰值允许在讨论开始时未知。买入资金由单独的不可变确认记录保存，最终金额仍由服务端使用同步持仓、申赎预检、确认现金、在途金额和目标仓位复算。账户峰值来自持续积累的估值快照，缺失时只降低买入行动等级，不伪装成零回撤。

**Tech Stack:** FastAPI、Pydantic v2、SQLAlchemy Async、SQLite、React 18、TypeScript、Ant Design、Vitest、pytest。

## Global Constraints

- 不接入支付宝、天天基金或券商订单 API，不自动下单。
- 养基宝同步持仓是讨论室的持仓来源；不可用时不得用空持仓启动正式实盘讨论。
- 可用现金未由用户为本次买入确认时，不得生成可执行买入金额。
- 在途买入和今日已申购默认 0、默认收起，但金额说明必须披露该假设。
- 今日已申购只作用于“拟买基金 + 当前渠道”，不得作为全账户统一金额。
- 账户峰值缺失时回撤为未知，不得当作 0；未知回撤最多允许条件操作。
- 已确认目标仓位不会因刷新、跨日或正常持仓变化而失效；只有用户主动调整才生成新政策版本。
- DeepSeek、问财、飞书和养基宝密钥只从忽略提交的后端环境读取，不进入日志、响应、数据库快照或 Git。
- 所有行为变更严格执行测试先行：先看到目标测试因缺少行为而失败，再写最小实现。

---

## File Map

### Backend

- Modify `backend/app/llm/registry.py`: 提供按角色检查有效凭证的公共函数。
- Modify `backend/app/api/v1/trading_room.py`: 允许无现金启动讨论，按需接收资金确认，并使用服务端数据复算。
- Modify `backend/app/trading_room/context.py`: 分离分析 blocker 与执行 blocker，允许现金和峰值未知。
- Create `backend/app/trading_room/account_valuation.py`: 保存确认后的账户估值并查询近期峰值。
- Modify `backend/app/models/trading_room.py`: 增加资金确认和账户估值快照表。
- Modify `backend/app/models/__init__.py`: 注册新增 SQLAlchemy 模型。
- Modify `backend/app/trading_room/store.py`: 保存和读取不可变资金确认。
- Modify `backend/app/services/yangjibao_service.py`: 返回持仓同步时间。
- Modify `backend/tests/trading_room/test_specialists.py`: 验证独立 DeepSeek Key 的就绪检查。
- Modify `backend/tests/trading_room/test_orchestrator.py`: 验证未知现金/峰值不阻断分析。
- Modify `backend/tests/trading_room/test_store.py`: 验证资金确认不可变且可回放。
- Create `backend/tests/trading_room/test_account_valuation.py`: 验证估值快照和近期峰值。
- Modify `backend/tests/trading_room/test_api.py`: 验证按需确认、服务端复算和基金级当日申购。
- Create `backend/tests/test_yangjibao_service.py`: 验证同步时间响应和服务端讨论持仓读取。

### Frontend

- Modify `frontend/src/types/portfolio.ts`: 增加 `synced_at`。
- Modify `frontend/src/types/tradingRoom.ts`: 允许现金/峰值为空，增加执行 blocker 和资金确认类型。
- Modify `frontend/src/api/tradingRoom.ts`: 使用新的 finalize 资金确认合同。
- Create `frontend/src/components/trading-room/SyncedAccountSummary.tsx`: 展示同步持仓状态。
- Create `frontend/src/components/trading-room/ExecutionFundingPanel.tsx`: 买入后确认现金，低频订单默认折叠。
- Modify `frontend/src/components/trading-room/TradingRoomPage.tsx`: 删除四个前置输入，改成一键讨论和分阶段 finalize。
- Modify `frontend/src/components/trading-room/ContextSnapshotCard.tsx`: 对未知现金和峰值显示“未确认/历史不足”。
- Modify `frontend/src/components/trading-room/PolicyImportPanel.tsx`: 已就绪政策压缩成摘要，仅主动点击时编辑。
- Modify `frontend/src/components/trading-room/TradingRoomPage.test.tsx`: 覆盖渐进式交互与政策持久化。

---

### Task 1: 修复讨论室独立 DeepSeek Key 的运行时就绪判断

**Files:**
- Modify: `backend/tests/trading_room/test_specialists.py`
- Modify: `backend/app/llm/registry.py`
- Modify: `backend/app/api/v1/trading_room.py`

**Interfaces:**
- Produces: `llm_credentials_configured(role: str | None = None) -> bool`
- Consumes: 现有 `_resolve_config(role)` 角色配置解析。

- [ ] **Step 1: 写失败测试，证明全局 Key 为空时讨论室独立 Key 仍应可用**

```python
def test_trading_room_credential_check_uses_role_specific_key(monkeypatch):
    from app.llm.registry import llm_credentials_configured

    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "trading_room_llm_api_key", "room-secret")

    assert llm_credentials_configured("chair") is True
```

- [ ] **Step 2: 运行测试并确认因公共函数不存在而失败**

Run: `cd backend && python3 -m pytest -q tests/trading_room/test_specialists.py::test_trading_room_credential_check_uses_role_specific_key`

Expected: FAIL，提示无法导入 `llm_credentials_configured`。

- [ ] **Step 3: 实现按角色检查并替换错误的全局 Key 判断**

在 `backend/app/llm/registry.py` 增加：

```python
def llm_credentials_configured(role: Optional[str] = None) -> bool:
    return bool(_resolve_config(role).api_key.strip())
```

在 `backend/app/api/v1/trading_room.py` 导入该函数，并将：

```python
if not settings.llm_api_key:
```

替换为：

```python
if not llm_credentials_configured("chair"):
```

- [ ] **Step 4: 运行目标测试和讨论室专业席位测试**

Run: `cd backend && python3 -m pytest -q tests/trading_room/test_specialists.py tests/trading_room/test_api.py`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/app/llm/registry.py backend/app/api/v1/trading_room.py backend/tests/trading_room/test_specialists.py
git commit -m "fix: honor trading room llm credentials"
```

---

### Task 2: 分离分析可信状态与金额执行状态

**Files:**
- Modify: `backend/tests/trading_room/test_orchestrator.py`
- Modify: `backend/app/trading_room/context.py`
- Modify: `backend/app/api/v1/trading_room.py`

**Interfaces:**
- Produces: `TradingContextSnapshot.cash: float | None`
- Produces: `TradingContextSnapshot.holdings_value: float`
- Produces: `TradingContextSnapshot.equity: float | None`
- Produces: `TradingContextSnapshot.peak_equity: float | None`
- Produces: `TradingContextSnapshot.execution_ready: bool`
- Produces: `TradingContextSnapshot.execution_blockers: tuple[str, ...]`
- Consumes: 现有 `CriticalDataInput`、市场数据 blocker 和上下文哈希逻辑。

- [ ] **Step 1: 写失败测试，证明缺少资金信息时仍可完成分析上下文**

```python
def test_unknown_cash_and_peak_allow_analysis_but_not_execution():
    snapshot = TradingContextBuilder.build(
        as_of=NOW,
        data_mode="live",
        market_dates={"CN": "2026-07-14"},
        positions=[{"symbol": "001513", "market_value": 20_000}],
        cash=None,
        equity=None,
        peak_equity=None,
        pending_orders=[],
        themes={},
        funds={},
        policy_version_id="policy-ready",
        skill_versions={},
        critical_inputs=[CriticalDataInput(
            key="portfolio", source="yangjibao", as_of=NOW,
            confidence="HIGH", is_mock=False, stale=False,
        )],
    )

    assert snapshot.status == "complete"
    assert snapshot.formally_actionable is True
    assert snapshot.holdings_value == 20_000
    assert snapshot.equity is None
    assert snapshot.execution_ready is False
    assert snapshot.execution_blockers == (
        "available_cash_unconfirmed", "account_drawdown_unknown",
    )
```

- [ ] **Step 2: 运行测试并确认 Pydantic 拒绝 `None` 或缺少新字段**

Run: `cd backend && python3 -m pytest -q tests/trading_room/test_orchestrator.py::test_unknown_cash_and_peak_allow_analysis_but_not_execution`

Expected: FAIL，原因是 `cash`/`peak_equity` 不接受 `None` 或 `execution_ready` 不存在。

- [ ] **Step 3: 修改上下文合同和构建逻辑**

将字段定义改成：

```python
cash: float | None = Field(default=None, ge=0)
holdings_value: float = Field(ge=0)
equity: float | None = Field(default=None, gt=0)
peak_equity: float | None = Field(default=None, gt=0)
execution_ready: bool
execution_blockers: tuple[str, ...]
```

在 `TradingContextBuilder.build` 中将 `cash`、`equity`、`peak_equity` 参数改为可空，使用持仓的 `market_value` 在服务端计算 `holdings_value`，并独立计算：

```python
execution_blockers: list[str] = []
if cash is None:
    execution_blockers.append("available_cash_unconfirmed")
if peak_equity is None:
    execution_blockers.append("account_drawdown_unknown")
```

`blockers` 继续只由演示数据、过期数据、模拟数据和低可信关键输入产生；`status` 与 `formally_actionable` 不受执行 blocker 影响。哈希基准必须同时加入 `execution_ready` 与 `execution_blockers`。

- [ ] **Step 4: 让会话创建请求接受未知资金字段**

在 `SessionCreateRequest` 中使用：

```python
cash: float | None = Field(default=None, ge=0)
equity: float | None = Field(default=None, gt=0)
peak_equity: float | None = Field(default=None, gt=0)
```

保留 `pending_orders` 以兼容历史回放，但新前端创建会话时固定发送空数组。

- [ ] **Step 5: 运行上下文、编排器和 API 回归测试**

Run: `cd backend && python3 -m pytest -q tests/trading_room/test_orchestrator.py tests/trading_room/test_shadow_session.py tests/trading_room/test_api.py`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add backend/app/trading_room/context.py backend/app/api/v1/trading_room.py backend/tests/trading_room/test_orchestrator.py
git commit -m "feat: separate trading analysis and execution readiness"
```

---

### Task 3: 保存本次买入资金确认并由服务端复算金额

**Files:**
- Modify: `backend/app/models/trading_room.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/trading_room/store.py`
- Modify: `backend/app/api/v1/trading_room.py`
- Modify: `backend/tests/trading_room/test_store.py`
- Modify: `backend/tests/trading_room/test_api.py`

**Interfaces:**
- Produces: `ExecutionFundingConfirmation` 请求模型。
- Produces: `TradingRoomFundingConfirmationRecord` 不可变审计记录。
- Produces: `TradingRoomStore.save_funding_confirmation(session_id, fund_code, channel, available_cash, pending_buy_amount, consumed_purchase_today, confirmed_at)`。
- Produces: finalize 请求字段 `execution_funding`，替代不可信的客户端 `guard_inputs`。
- Consumes: `TradeStatusSnapshot.fund_code`、保存的申赎预检、不可变持仓快照和已确认政策。

- [ ] **Step 1: 写失败存储测试，要求资金确认按会话与基金回放**

```python
funding = await store.save_funding_confirmation(
    session_id=session.id,
    fund_code="001513",
    channel="支付宝",
    available_cash=20_000,
    pending_buy_amount=0,
    consumed_purchase_today=0,
    confirmed_at=NOW.replace(tzinfo=None),
)
replayed = await store.get_latest_funding_confirmation(session.id, "001513", "支付宝")

assert replayed.id == funding.id
assert replayed.available_cash == 20_000
assert replayed.fund_code == "001513"
```

在同一测试中再保存另一基金的 `consumed_purchase_today=8_000`，断言重新读取 001513 仍为 0，证明当日申购不会跨基金或渠道串用。

- [ ] **Step 2: 写失败 API 测试，要求没有现金确认时无法 finalize 买入**

```python
payload = _finalize_payload()
payload.pop("guard_inputs", None)
payload["execution_funding"] = None
response = await client.post(
    f"/api/v1/agent/trading-room/sessions/{session_id}/finalize",
    json=payload,
)
assert response.status_code == 409
assert response.json()["detail"] == "available_cash_confirmation_required"
```

- [ ] **Step 3: 写失败 API 测试，证明客户端不能伪造账户权益或目标仓位**

```python
payload = _finalize_payload()
payload.pop("guard_inputs", None)
payload["execution_funding"] = {
    "available_cash": 500,
    "pending_buy_amount": 0,
    "consumed_purchase_today": 0,
}
response = await client.post(
    f"/api/v1/agent/trading-room/sessions/{session_id}/finalize",
    json=payload,
)
decision = response.json()["decision"]
assert decision["guarded_range"] is None
assert "available_cash" in decision["reasons"]
```

- [ ] **Step 4: 运行三个目标测试并确认因表、方法和新请求合同缺失而失败**

Run: `cd backend && python3 -m pytest -q tests/trading_room/test_store.py tests/trading_room/test_api.py -k 'funding or available_cash_confirmation or recomputes_cash'`

Expected: FAIL。

- [ ] **Step 5: 新增不可变资金确认模型**

在 `backend/app/models/trading_room.py` 增加：

```python
class TradingRoomFundingConfirmationRecord(Base):
    __tablename__ = "trading_room_funding_confirmations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("trading_room_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fund_code: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(40), nullable=False)
    available_cash: Mapped[float] = mapped_column(Float, nullable=False)
    pending_buy_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    consumed_purchase_today: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
```

给三个金额字段添加 `before_update` 不可变保护，或对整行禁止 update；在 `backend/app/models/__init__.py` 导入并加入 `__all__`。

- [ ] **Step 6: 实现存储方法**

在 `TradingRoomStore` 增加：

```python
async def save_funding_confirmation(
    self, *, session_id: str, fund_code: str, channel: str,
    available_cash: float, pending_buy_amount: float,
    consumed_purchase_today: float, confirmed_at: datetime,
) -> TradingRoomFundingConfirmationRecord:
    row = TradingRoomFundingConfirmationRecord(
        session_id=session_id,
        fund_code=fund_code,
        channel=channel,
        available_cash=available_cash,
        pending_buy_amount=pending_buy_amount,
        consumed_purchase_today=consumed_purchase_today,
        confirmed_at=confirmed_at.replace(tzinfo=None),
    )
    self._db.add(row)
    await self._db.flush()
    return row

async def get_latest_funding_confirmation(
    self, session_id: str, fund_code: str, channel: str,
) -> TradingRoomFundingConfirmationRecord | None:
    result = await self._db.execute(
        select(TradingRoomFundingConfirmationRecord)
        .where(
            TradingRoomFundingConfirmationRecord.session_id == session_id,
            TradingRoomFundingConfirmationRecord.fund_code == fund_code,
            TradingRoomFundingConfirmationRecord.channel == channel,
        )
        .order_by(
            desc(TradingRoomFundingConfirmationRecord.confirmed_at),
            desc(TradingRoomFundingConfirmationRecord.id),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()

async def list_funding_confirmations(
    self, session_id: str,
) -> list[TradingRoomFundingConfirmationRecord]:
    result = await self._db.execute(
        select(TradingRoomFundingConfirmationRecord)
        .where(TradingRoomFundingConfirmationRecord.session_id == session_id)
        .order_by(TradingRoomFundingConfirmationRecord.id)
    )
    return list(result.scalars().all())

async def get_latest_cash_confirmation(
    self,
) -> TradingRoomFundingConfirmationRecord | None:
    result = await self._db.execute(
        select(TradingRoomFundingConfirmationRecord)
        .order_by(
            desc(TradingRoomFundingConfirmationRecord.confirmed_at),
            desc(TradingRoomFundingConfirmationRecord.id),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()
```

查询按 `confirmed_at DESC, id DESC`，不得跨基金或跨渠道复用 `consumed_purchase_today`。

- [ ] **Step 7: 替换 finalize 合同并进行服务端复算**

增加：

```python
class ExecutionFundingConfirmation(BaseModel):
    available_cash: float = Field(ge=0)
    pending_buy_amount: float = Field(default=0, ge=0)
    consumed_purchase_today: float = Field(default=0, ge=0)
```

将 `FinalizeRequest.guard_inputs` 替换为：

```python
execution_funding: ExecutionFundingConfirmation | None = None
```

确认时间必须由后端使用 `datetime.now(ZoneInfo(settings.timezone))` 生成，不能接受浏览器提供的时间。基金代码和渠道必须从本会话保存的有效预检记录解析，不能由 `execution_funding` 指定；新增 `_saved_preflight_channel(session, fund_code, share_class) -> str` 辅助函数完成匹配。

新增 `GET /agent/trading-room/funding/latest`，只返回最近一次 `available_cash` 和服务端 `confirmed_at` 供下次预填；不返回也不复用旧的 `pending_buy_amount` 或 `consumed_purchase_today`。预填值仍必须由用户点击确认后才能用于本次 finalize。

`_guard_inputs_from_context` 改为接收确认记录，并只从以下来源构造 `BuyGuardInputs`：

```python
holdings_value = sum(max(0.0, float(p.get("market_value") or 0)) for p in positions)
account_equity = holdings_value + funding.available_cash
current_allocation_pct = current_fund_value / account_equity
target_allocation_pct = saved_policy_target.target_pct
available_cash = funding.available_cash
pending_buy_amount = funding.pending_buy_amount
consumed_purchase_today = funding.consumed_purchase_today
```

本任务不改变专业席位分数和建议区间的既有校验路径；申赎状态仍以服务端保存/刷新结果为准，账户权益、目标仓位、持仓市值、现金、在途金额和今日申购不得使用浏览器提交的派生值。

- [ ] **Step 8: 将确认记录加入会话响应审计字段**

`_session_response` 使用 `list_funding_confirmations` 返回当前会话的 `funding_confirmations`，字段只包含基金、渠道、金额和确认时间；不得包含任何 API 凭证。

- [ ] **Step 9: 运行存储、API、护栏和编排测试**

Run: `cd backend && python3 -m pytest -q tests/trading_room/test_store.py tests/trading_room/test_api.py tests/trading_room/test_guard.py tests/trading_room/test_orchestrator.py`

Expected: PASS。

- [ ] **Step 10: 提交**

```bash
git add backend/app/models/trading_room.py backend/app/models/__init__.py backend/app/trading_room/store.py backend/app/api/v1/trading_room.py backend/tests/trading_room/test_store.py backend/tests/trading_room/test_api.py
git commit -m "feat: confirm trading funds only when needed"
```

---

### Task 4: 从服务端同步持仓并积累可信账户峰值

**Files:**
- Modify: `backend/app/models/trading_room.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/trading_room/account_valuation.py`
- Create: `backend/tests/trading_room/test_account_valuation.py`
- Create: `backend/tests/test_yangjibao_service.py`
- Modify: `backend/tests/trading_room/test_api.py`
- Modify: `backend/app/api/v1/trading_room.py`
- Modify: `backend/app/services/yangjibao_service.py`
- Modify: `frontend/src/types/portfolio.ts`

**Interfaces:**
- Produces: `AccountValuationService.record_confirmed(session_id, holdings_value, cash, captured_at, confidence)`。
- Produces: `AccountValuationService.recent_peak(as_of, lookback_days=180) -> float | None`。
- Produces: 养基宝组合响应 `synced_at: str | None`。
- Produces: 会话创建只接受市场/政策元数据，持仓、基金名称和持仓同步时间由后端本地数据库装配。
- Consumes: Task 3 的资金确认、同步持仓和会话 ID。

- [ ] **Step 1: 写失败测试，要求只有包含已确认现金的估值进入峰值**

```python
await service.record_confirmed(
    session_id="s1", holdings_value=80_000, cash=20_000,
    captured_at=NOW, confidence="HIGH",
)
await service.record_unconfirmed(
    session_id="s2", holdings_value=120_000, captured_at=NOW,
)

assert await service.recent_peak(as_of=NOW) == 100_000
```

- [ ] **Step 2: 写失败测试，要求无可信历史时峰值为 `None`**

```python
assert await service.recent_peak(as_of=NOW) is None
```

- [ ] **Step 3: 运行测试并确认因模型/服务不存在而失败**

Run: `cd backend && python3 -m pytest -q tests/trading_room/test_account_valuation.py`

Expected: FAIL。

- [ ] **Step 4: 写失败 API 测试，证明会话忽略浏览器持仓并使用服务端同步持仓**

```python
@pytest.mark.asyncio
async def test_session_uses_server_synced_portfolio(client, monkeypatch):
    async def fake_portfolio(self):
        return {
            "connected": True,
            "total_value": 20_000,
            "synced_at": NOW.isoformat(),
            "positions": [{
                "symbol": "001513", "name": "易方达信息产业混合A",
                "type": "fund", "market_value": 20_000,
            }],
        }

    monkeypatch.setattr(
        "app.api.v1.trading_room.YangjibaoService.get_local_portfolio",
        fake_portfolio,
    )
    policy = await _import_policy(
        client, [{"scope": "fund", "key": "001513", "target_pct": 0.3}],
    )
    payload = _session_payload(policy["version_id"])
    for key in ("positions", "cash", "equity", "peak_equity", "pending_orders", "funds"):
        payload.pop(key, None)

    response = await client.post("/api/v1/agent/trading-room/sessions", json=payload)

    assert response.status_code == 200
    context = response.json()["context"]
    assert context["positions"][0]["symbol"] == "001513"
    assert context["holdings_value"] == 20_000
    assert context["cash"] is None
    assert context["equity"] is None
```

另写一个服务端返回空持仓的 live 请求测试，断言状态码为 409、detail 为 `synced_portfolio_empty`。

- [ ] **Step 5: 新增估值快照模型和服务**

模型字段固定为：

```python
class AccountValuationSnapshotRecord(Base):
    __tablename__ = "account_valuation_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    holdings_value: Mapped[float] = mapped_column(Float, nullable=False)
    cash: Mapped[float | None] = mapped_column(Float, nullable=True)
    equity: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
```

`record_confirmed` 保存 `equity = holdings_value + cash`；`record_unconfirmed` 保存 `cash=None, equity=None, confidence="UNKNOWN"`。`recent_peak` 只查询 lookback 窗口内 `confidence IN ("HIGH", "MEDIUM") AND equity IS NOT NULL` 的最大值。

- [ ] **Step 6: 会话创建时只从服务端读取持仓和峰值，finalize 后保存确认估值**

`SessionCreateRequest` 删除 `positions`、`cash`、`equity`、`peak_equity`、`pending_orders` 和 `funds`。在 `create_session` 中调用 `YangjibaoService(db).get_local_portfolio()`；live 模式持仓为空时返回 409。构建上下文时使用：

```python
portfolio = await YangjibaoService(db).get_local_portfolio()
positions = portfolio["positions"]
funds = {item["symbol"]: {"name": item["name"]} for item in positions}
synced_at = (
    datetime.fromisoformat(portfolio["synced_at"])
    if portfolio.get("synced_at")
    else None
)
critical_inputs = [item for item in request.critical_inputs if item.key != "portfolio"]
critical_inputs.append(CriticalDataInput(
    key="portfolio",
    source="yangjibao",
    as_of=synced_at,
    confidence=(
        "HIGH" if portfolio.get("connected") and portfolio.get("synced_at")
        else "UNKNOWN"
    ),
    is_mock=False,
    stale=(
        synced_at is None
        or synced_at.date() < request.as_of.date()
    ),
))
```

`cash=None`、`equity=None`、`pending_orders=[]`；`holdings_value` 由 `TradingContextBuilder` 对服务端持仓求和。`_collect_server_preflights` 改为显式接收 `positions`、`funds` 和 `execution_channel`，不再读取浏览器请求中的持仓。

创建上下文前：

```python
peak_equity = await AccountValuationService(db).recent_peak(as_of=request.as_of)
```

finalize 接收资金确认后：

```python
await AccountValuationService(db).record_confirmed(
    session_id=session.id,
    holdings_value=holdings_value,
    cash=funding.available_cash,
    captured_at=funding.confirmed_at,
    confidence="HIGH",
)
```

如果上下文中的 `peak_equity is None`，保留护栏金额但把行动等级最高限制为 `CONDITIONAL`、`immediately_executable=False`，并加入 `account_drawdown_unknown`。如果峰值存在，服务端计算当前回撤；达到政策 warning 阈值时，把 `has_veto` 设为真，不能只信客户端风险声明。

- [ ] **Step 7: 返回养基宝持仓同步时间**

`YangjibaoService.get_local_portfolio` 使用所有 `source == "yangjibao"` 持仓的最大 `updated_at`：

```python
synced_at = max((p.updated_at for p in positions if p.updated_at), default=None)
```

响应增加：

```python
"synced_at": synced_at.isoformat() if synced_at else None
```

同步时间只是披露数据，不把未知时间伪装成当前时间。

- [ ] **Step 8: 运行估值、API、养基宝和风险指标测试**

Run: `cd backend && python3 -m pytest -q tests/trading_room/test_account_valuation.py tests/trading_room/test_api.py tests/trading_room/test_risk_metrics.py tests/test_yangjibao_service.py`

Expected: PASS。

- [ ] **Step 9: 提交**

```bash
git add backend/app/models/trading_room.py backend/app/models/__init__.py backend/app/trading_room/account_valuation.py backend/app/api/v1/trading_room.py backend/app/services/yangjibao_service.py backend/tests/trading_room/test_account_valuation.py backend/tests/trading_room/test_api.py frontend/src/types/portfolio.ts
git commit -m "feat: derive account peak from trusted snapshots"
```

---

### Task 5: 将前端改成一键讨论和买入后资金确认

**Files:**
- Modify: `frontend/src/types/tradingRoom.ts`
- Modify: `frontend/src/api/tradingRoom.ts`
- Create: `frontend/src/components/trading-room/SyncedAccountSummary.tsx`
- Create: `frontend/src/components/trading-room/ExecutionFundingPanel.tsx`
- Modify: `frontend/src/components/trading-room/TradingRoomPage.tsx`
- Modify: `frontend/src/components/trading-room/ContextSnapshotCard.tsx`
- Modify: `frontend/src/components/trading-room/TradingRoomPage.test.tsx`

**Interfaces:**
- Produces: `ExecutionFundingInput` TypeScript 类型。
- Produces: `ExecutionFundingPanel` 回调 `onConfirm(input: ExecutionFundingInput)`。
- Consumes: Task 2 的 nullable 上下文和 Task 3 的 finalize API。
- Consumes: Task 4 的 `YangjibaoPortfolioResponse.synced_at`。

- [ ] **Step 1: 写失败页面测试，要求首屏没有四个前置输入**

```tsx
it('starts from synced holdings without upfront execution inputs', async () => {
  vi.mocked(tradingRoomApi.getCurrentPolicy).mockResolvedValue(readyPolicy)
  vi.mocked(portfolioApi.getPortfolio).mockResolvedValue({ data: syncedPortfolio } as never)

  render(<TradingRoomPage />)

  expect(await screen.findByText(/已同步 3 个持仓/)).toBeInTheDocument()
  expect(screen.queryByText('可用现金')).not.toBeInTheDocument()
  expect(screen.queryByText('账户近期峰值')).not.toBeInTheDocument()
  expect(screen.queryByText('在途买入')).not.toBeInTheDocument()
  expect(screen.queryByText('今日已申购')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '开始今日讨论' })).toBeEnabled()
})
```

- [ ] **Step 2: 写失败交互测试，要求只有买入候选出现现金确认**

```tsx
it('asks for cash only after a buy candidate exists', async () => {
  vi.mocked(tradingRoomApi.createSession).mockResolvedValue(buyCandidateSession)
  render(<TradingRoomPage />)
  fireEvent.click(await screen.findByRole('button', { name: '开始今日讨论' }))

  expect(await screen.findByText('确认可买金额')).toBeInTheDocument()
  expect(screen.getByLabelText('可用现金')).toBeInTheDocument()
  expect(screen.queryByLabelText('在途买入')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('今日已申购')).not.toBeInTheDocument()
})
```

- [ ] **Step 3: 写失败测试，要求低频订单默认折叠且展开后作用域清楚**

```tsx
fireEvent.click(screen.getByRole('button', { name: /有未确认订单或今天已买过/ }))
expect(screen.getByLabelText('账户在途买入')).toBeInTheDocument()
expect(screen.getByLabelText('本基金今日已申购')).toBeInTheDocument()
expect(screen.getByText(/按无在途买入、今日未申购计算/)).toBeInTheDocument()
```

再使用没有达到 `conditional_buy_min` 的 WATCH 会话和仅含卖出意见的会话分别渲染，断言两者均不存在“确认可买金额”和“可用现金”输入。

- [ ] **Step 4: 运行目标测试并确认因现有前置输入和组件缺失而失败**

Run: `cd frontend && npm run test:run -- src/components/trading-room/TradingRoomPage.test.tsx`

Expected: FAIL。

- [ ] **Step 5: 更新类型和 API 合同**

在 `TradingContextSnapshot` 中使用：

```ts
cash: number | null
holdings_value: number
equity: number | null
peak_equity: number | null
execution_ready: boolean
execution_blockers: string[]
```

增加：

```ts
export interface ExecutionFundingInput {
  available_cash: number
  pending_buy_amount: number
  consumed_purchase_today: number
}
```

`SessionCreatePayload` 删除 `positions`、`cash`、`equity`、`peak_equity`、`pending_orders` 和 `funds`，防止浏览器覆盖服务端同步持仓。`tradingRoomApi.finalizeSession` 的 payload 类型包含 `execution_funding: ExecutionFundingInput`，不再发送 `guard_inputs`。增加 `tradingRoomApi.getLatestFunding()`，只读取最近确认现金和服务端确认时间。

- [ ] **Step 6: 实现同步账户摘要组件**

`SyncedAccountSummary` 接收：

```ts
interface Props {
  connected: boolean
  positionCount: number
  totalValue: number
  syncedAt: string | null
  loading: boolean
}
```

已连接且有持仓时显示“已同步 N 个持仓 · 总市值 ¥X · 更新时间”；时间为空显示“同步时间未知”，不得显示当前时间。未连接或空持仓时用 warning Alert，并禁用正式讨论按钮。

- [ ] **Step 7: 实现按需资金确认组件**

`ExecutionFundingPanel` 默认只显示 `InputNumber aria-label="可用现金"` 和确认按钮。最近确认现金可以预填，但旁边必须显示“上次确认于 …，本次仍需确认”。使用 Ant Design `Collapse` 或文本按钮收起：

```tsx
<Button type="link">有未确认订单或今天已买过这只基金</Button>
```

展开后显示 `aria-label="账户在途买入"` 和 `aria-label="本基金今日已申购"`。默认值都是 0；确认时间由服务端生成。组件始终展示“按无在途买入、今日未申购计算”的假设说明，用户填入非零值后改成对应摘要。

- [ ] **Step 8: 改写 TradingRoomPage 的启动与 finalize 流程**

页面加载时并行读取政策和 `portfolioApi.getPortfolio()`，组合响应只用于首屏摘要，不作为正式上下文持仓来源；不保存四个金额 state。开始讨论请求不发送任何持仓和资金字段，只发送政策版本、市场日期、行情关键输入、题材和执行渠道。后端会在创建会话时重新读取本地同步持仓。

前端不得创建 `critical_inputs.portfolio`；该条输入由后端使用 `portfolio.synced_at` 生成。时间为空时后端置信度降为 `UNKNOWN`，不得使用 `new Date()` 冒充同步时间。

创建会话后，只在 buy memo 分数达到 `policy.conditional_buy_min`、建议区间存在、目标基金、该基金的 fund 级目标仓位和保存的 preflight 均可识别时设置 `pendingBuyDecision`。其余结果直接展示，不出现资金确认。资金确认后调用 finalize，将返回的 `final_decision` 合并到当前 session。

- [ ] **Step 9: 更新上下文卡片的未知值文案**

```tsx
<Descriptions.Item label="可用现金">
  {context.cash === null ? '买入时确认' : money(context.cash)}
</Descriptions.Item>
<Descriptions.Item label="持仓市值">{money(context.holdings_value)}</Descriptions.Item>
<Descriptions.Item label="账户净值">
  {context.equity === null ? '现金确认后计算' : money(context.equity)}
</Descriptions.Item>
<Descriptions.Item label="账户近期峰值">
  {context.peak_equity === null ? '历史不足' : money(context.peak_equity)}
</Descriptions.Item>
```

执行 blocker 与分析 blocker 分区展示；不能把 `available_cash_unconfirmed` 显示成整个讨论不可分析。

- [ ] **Step 10: 运行页面测试和前端完整测试**

Run: `cd frontend && npm run test:run -- src/components/trading-room/TradingRoomPage.test.tsx`

Expected: PASS。

Run: `cd frontend && npm run test:run`

Expected: 全部 PASS。

- [ ] **Step 11: 提交**

```bash
git add frontend/src/types/tradingRoom.ts frontend/src/api/tradingRoom.ts frontend/src/components/trading-room/SyncedAccountSummary.tsx frontend/src/components/trading-room/ExecutionFundingPanel.tsx frontend/src/components/trading-room/TradingRoomPage.tsx frontend/src/components/trading-room/ContextSnapshotCard.tsx frontend/src/components/trading-room/TradingRoomPage.test.tsx
git commit -m "feat: reveal trading inputs only when needed"
```

---

### Task 6: 压缩交易政策展示并保证目标仓位只主动修改

**Files:**
- Modify: `frontend/src/components/trading-room/PolicyImportPanel.tsx`
- Modify: `frontend/src/components/trading-room/TradingRoomPage.tsx`
- Modify: `frontend/src/components/trading-room/TradingRoomPage.test.tsx`
- Modify: `backend/tests/trading_room/test_api.py`

**Interfaces:**
- Produces: `PolicyImportPanel` 已就绪态的“查看策略”和“调整策略”交互。
- Produces: 新题材只有达到买入讨论门槛后才出现一次目标仓位确认。
- Consumes: 现有 `TradingPolicy.target_allocations` 和 `onImport(targets)`。

- [ ] **Step 1: 写失败前端测试，要求 ready 政策不自动进入编辑态**

```tsx
it('keeps confirmed targets across reloads and edits only on request', async () => {
  vi.mocked(tradingRoomApi.getCurrentPolicy).mockResolvedValue(readyPolicy)
  render(<TradingRoomPage />)

  expect(await screen.findByText(/通信 25%/)).toBeInTheDocument()
  expect(screen.queryByText('还需确认目标仓位')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('目标仓位 1')).not.toBeInTheDocument()
  expect(tradingRoomApi.importPolicy).not.toHaveBeenCalled()

  fireEvent.click(screen.getByRole('button', { name: '调整策略' }))
  expect(screen.getByLabelText('目标仓位 1')).toHaveValue(25)
})
```

- [ ] **Step 2: 写失败后端测试，要求当前政策持续返回最新 ready 版本**

```python
first = await _import_policy(client, [])
ready = await _import_policy(
    client, [{"scope": "theme", "key": "通信", "target_pct": 0.25}],
)
current = await client.get("/api/v1/agent/trading-policy")

assert first["ready"] is False
assert current.json()["version_id"] == ready["version_id"]
assert current.json()["target_allocations"] == ready["target_allocations"]
```

同时增加前端测试：进入页面时不出现“机器人目标仓位”；当 theme memo 返回 `theme="机器人"` 且 buy score 达到 `conditional_buy_min` 后，才显示“机器人尚未设置目标仓位”。确认后调用 `importPolicy`，payload 必须保留已有目标并追加 `{ scope: 'theme', key: '机器人', target_pct: 用户输入 }`。

- [ ] **Step 3: 运行测试并确认现有 ready 面板缺少主动编辑入口**

Run: `cd frontend && npm run test:run -- src/components/trading-room/TradingRoomPage.test.tsx`

Expected: FAIL。

Run: `cd backend && python3 -m pytest -q tests/trading_room/test_api.py -k current_policy`

Expected: PASS；若失败，修复排序为 `created_at DESC, version_id DESC`，不新增每日过期逻辑。

- [ ] **Step 4: 实现紧凑摘要和显式编辑**

ready 状态默认只显示政策名称、明显机会阈值和目标仓位摘要，以及两个按钮：

```tsx
<Button type="link">查看策略</Button>
<Button type="link" onClick={() => setEditing(true)}>调整策略</Button>
```

只有 `editing === true` 时渲染目标仓位输入，初值必须来自 `policy.target_allocations`，不能重新套用通信/纳斯达克/全球基金默认数组。保存成功后的新 policy 由父组件传回时退出编辑态。

`TradingRoomPage` 在讨论完成后读取 theme memo 和 buy memo；只有 buy score 达到条件门槛且 `policy.target_allocations` 不含该题材时，渲染一次目标输入。保存新政策后清除提示并显示“目标已保存，请重新发起讨论”，因为已创建会话的政策快照不可变。不得静默修改当前会话。

- [ ] **Step 5: 运行前后端目标测试**

Run: `cd frontend && npm run test:run -- src/components/trading-room/TradingRoomPage.test.tsx`

Expected: PASS。

Run: `cd backend && python3 -m pytest -q tests/trading_room/test_api.py -k policy`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/trading-room/PolicyImportPanel.tsx frontend/src/components/trading-room/TradingRoomPage.tsx frontend/src/components/trading-room/TradingRoomPage.test.tsx backend/tests/trading_room/test_api.py
git commit -m "feat: persist trading targets until explicit edit"
```

---

### Task 7: 完整验证、浏览器验收和推送

**Files:**
- Modify only if verification reveals a scoped defect.

**Interfaces:**
- Consumes: Tasks 1–6 的完整行为。
- Produces: 可复现的测试、构建、浏览器和 Git 推送证据。

- [ ] **Step 1: 运行完整后端测试**

Run: `cd backend && python3 -m pytest -q`

Expected: 0 failures。

- [ ] **Step 2: 运行 Python 编译检查**

Run: `cd backend && python3 -m compileall -q app`

Expected: exit 0。

- [ ] **Step 3: 运行完整前端测试和生产构建**

Run: `cd frontend && npm run test:run`

Expected: 0 failures。

Run: `cd frontend && npm run build`

Expected: exit 0；现有大包体积 warning 可以记录，但 TypeScript 或构建错误必须修复。

- [ ] **Step 4: 检查差异和密钥边界**

Run: `git diff --check`

Expected: 无输出，exit 0。

使用只输出变量名的本地脚本比较 `backend/.env` 中长度至少 8 的敏感值与 `git diff HEAD~6..HEAD`；Expected: `tracked_secret_values_found=[]`。脚本不得打印任何密钥值。

- [ ] **Step 5: 重启后端并检查健康端点**

Run: `curl -fsS http://127.0.0.1:8000/api/health`

Expected: `{"status":"ok","version":"0.1.0"}`。若运行中服务尚未加载新代码，先正常停止旧 uvicorn 进程，再从 `backend` 启动 `uvicorn app.main:app --host 127.0.0.1 --port 8000`。

- [ ] **Step 6: 使用浏览器完成五项验收**

打开 `http://localhost:5173/trading-room`，逐项确认：

1. 首屏只显示同步账户摘要和开始按钮，没有四个金额输入。
2. 不操作/观察结果不会要求现金。
3. 买入候选只在结果阶段要求现金。
4. 低频订单默认隐藏，展开后显示账户在途和本基金今日申购。
5. 刷新页面后已确认目标仓位仍是摘要状态，不再次询问。

同时检查浏览器控制台没有 React exception、未处理请求错误或密钥内容。

- [ ] **Step 7: 运行最终 Git 检查并推送当前功能分支**

```bash
git status --short
git log --oneline -7
git push origin agent/p0-data-trust
```

Expected: 工作树干净，本地 HEAD 与 `origin/agent/p0-data-trust` 一致。
