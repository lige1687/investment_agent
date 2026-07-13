# Fund Backtest MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first backend-only fund backtest loop for event-triggered, semi-autonomous strategy decisions.

**Architecture:** Add a focused `backtest` service package with pure Python models, indicator calculations, fund fee simulation, event detection, strategy decision policy, and report-ready result structures. Expose one FastAPI endpoint that accepts in-memory historical fund NAV and signal asset bars for MVP testing; later iterations can replace those arrays with westock-data/SkillBridge fetchers.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, pytest, existing backend package layout.

## Global Constraints

- Trading object is a fund; signal object is an ETF, index, or sector.
- Program code performs daily replay and deterministic calculations.
- Strategy decision is only invoked when buy/sell/observe events trigger.
- Buy strategy is prosperity filter plus volume-confirmed trend entry plus staged buying.
- Sell strategy includes profit-peak drawdown, technical breakdown, stop-loss, and observation review.
- Fund management/custodian fees are treated as already reflected in NAV by default.
- Subscription/redemption fees are simulated explicitly.
- MVP uses daily bars and T+1 NAV execution.
- Output must include performance metrics, equity curve, trades, triggered events, and human-readable reasons.

---

### Task 1: Pure Backtest Domain Core

**Files:**
- Create: `backend/app/backtest/__init__.py`
- Create: `backend/app/backtest/models.py`
- Create: `backend/app/backtest/indicators.py`
- Create: `backend/app/backtest/fees.py`
- Test: `backend/tests/test_backtest_core.py`

**Interfaces:**
- Produces: `FundNavPoint`, `SignalBar`, `BacktestConfig`, `PortfolioSnapshot`, `TradeRecord`, `BacktestResult`
- Produces: `expma(values: list[float], window: int) -> list[float]`
- Produces: `moving_average(values: list[float], window: int) -> list[float | None]`
- Produces: `volume_ratio(volumes: list[float], window: int) -> list[float | None]`
- Produces: `FundFeeModel.calculate_buy_shares(cash: float, nav: float) -> tuple[float, float]`
- Produces: `FundFeeModel.calculate_sell_cash(shares: float, nav: float, holding_days: int) -> tuple[float, float]`

- [ ] Write failing tests for EXPMA, volume ratio, buy fee, and redemption fee tiers.
- [ ] Run `cd backend && pytest tests/test_backtest_core.py -q` and confirm missing module failures.
- [ ] Implement the domain models and helper functions.
- [ ] Re-run the same test file and confirm it passes.

### Task 2: Event Detection and Strategy Policy

**Files:**
- Create: `backend/app/backtest/events.py`
- Create: `backend/app/backtest/strategy.py`
- Test: `backend/tests/test_backtest_events.py`

**Interfaces:**
- Consumes: models and indicators from Task 1.
- Produces: `BacktestEvent`
- Produces: `EventDetector.detect(...) -> list[BacktestEvent]`
- Produces: `RuleBasedStrategyAgent.decide(event: BacktestEvent, context: StrategyContext) -> StrategyDecision`

- [ ] Write failing tests for buy candidate, profit drawdown, technical breakdown, and observation review events.
- [ ] Run `cd backend && pytest tests/test_backtest_events.py -q` and confirm failures.
- [ ] Implement event detection with deterministic thresholds.
- [ ] Implement the MVP strategy policy that chooses buy, sell, observe, or hold from structured context.
- [ ] Re-run the event tests and confirm they pass.

### Task 3: Replay Engine

**Files:**
- Create: `backend/app/backtest/engine.py`
- Test: `backend/tests/test_backtest_engine.py`

**Interfaces:**
- Consumes: Task 1 models/fees and Task 2 events/strategy.
- Produces: `BacktestEngine.run(config, fund_nav, signal_bars) -> BacktestResult`

- [ ] Write a failing test where a prosperity-approved, volume-confirmed trend event buys a partial fund position.
- [ ] Write a failing test where profit peak drawdown triggers a partial sell and records realized cash.
- [ ] Run `cd backend && pytest tests/test_backtest_engine.py -q` and confirm failures.
- [ ] Implement daily replay, T+1 fund NAV execution, cash/shares accounting, equity curve, and metrics.
- [ ] Re-run engine tests and confirm they pass.

### Task 4: API Schemas and Route

**Files:**
- Create: `backend/app/schemas/backtest.py`
- Create: `backend/app/api/v1/backtest.py`
- Modify: `backend/app/api/v1/router.py`
- Test: `backend/tests/test_backtest_api.py`

**Interfaces:**
- Consumes: `BacktestEngine.run(...)`
- Produces: `POST /api/v1/backtest/run`

- [ ] Write a failing FastAPI test for `POST /api/v1/backtest/run` with inline sample NAV and signal bars.
- [ ] Run `cd backend && pytest tests/test_backtest_api.py -q` and confirm the route is missing.
- [ ] Add Pydantic request/response schemas.
- [ ] Add the route and include it in the v1 router.
- [ ] Re-run API test and confirm it passes.

### Task 5: Verification

**Files:**
- Modify only if tests expose a real issue.

- [ ] Run `cd backend && pytest -q`.
- [ ] Record any unsupported features for later: westock-data fetcher, topnews context injection,同花顺 event explanation, frontend view, persistent saved backtest runs.

## Self-Review Notes

- The MVP deliberately accepts inline historical data so the replay engine can be tested without network calls.
- The strategy Agent is initially a deterministic local policy with the same JSON-shaped interface a future LLM Agent will use.
- The plan excludes frontend work and persistent database tables to keep the first slice testable and small.
- No git commit step is included because `/Users/yongbiaoli/Desktop/financial` is not currently a git repository.
