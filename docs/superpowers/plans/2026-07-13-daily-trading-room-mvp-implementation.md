# Daily Trading Room MVP Implementation Plan

> **For Codex:** Execute after the P0 data-trust checkpoint. Work inline with `executing-plans`; do not delegate unless the user explicitly requests sub-agents. Apply `test-driven-development` task by task and `verification-before-completion` at handoff.

**Goal:** Deliver a manual-confirmation daily fund trading room that freezes trustworthy context, runs skill-constrained DeepSeek specialists, exposes disagreements and missing evidence, preflights real subscription restrictions, computes portfolio risk, and returns guarded buy/sell ranges while allowing “today, do nothing.”

**Architecture:** Build a new bounded `app/trading_room` package rather than expanding `agent_service.py`. Deterministic modules own snapshots, exposure confidence, risk metrics, execution availability, policy versions, and amount clamping. DeepSeek specialists only interpret immutable inputs into validated memos; a recorder/chair summarizes deterministic outputs. Persist the full audit trail in SQLite and expose REST endpoints to a dedicated React page.

**Tech Stack:** FastAPI, SQLAlchemy asyncio, Pydantic v2, existing OpenAI-compatible LLM client with DeepSeek, local versioned skills, pytest, React/TypeScript, TanStack Query, Ant Design, Vitest.

---

## MVP acceptance

- A user can import `mid-term-theme-v1`, set target allocations once, and start a room from current holdings.
- The session freezes source/time/mode/staleness, portfolio, fund report periods, inferred exposure, execution status, policy version, and skill hashes.
- Incomplete, mock, stale, low-exposure-confidence, suspended, unknown-channel, or unresolved veto inputs cannot become an executable immediate buy.
- Specialist round one is independent; round two contains only explicit conflicts.
- Skeptic findings require a concrete evidence reference or missing field and never alter scores/amounts directly.
- The amount shown as executable is the intersection of the agent range, subscription allowance, target-allocation headroom, cash/holdings, and pending orders. No single-operation cap or forced batch label exists.
- User chooses final amount and records accepted/partial/ignored/watch feedback; no broker order is sent.

## Task 1: Define schemas and deterministic policy template

**Files:**
- Create: `backend/app/trading_room/__init__.py`
- Create: `backend/app/trading_room/schemas.py`
- Create: `backend/app/trading_room/policy.py`
- Create: `backend/tests/trading_room/test_policy.py`
- Modify: `backend/app/config.py`
- Modify: `backend/.env.example`

- [ ] Test the exact defaults for `mid-term-theme-v1`: buy threshold 80, conditional 65–79, account drawdown warning 5%, de-risk 7.5%, protection 10%, percentage stop disabled, no operation cap/batch field.
- [ ] Test policy imports require explicit target allocations before `ready=true` and create an immutable version id.
- [ ] Define enums and Pydantic contracts for data confidence, trade availability, theme phase, specialist state, action class, risk state, decision range, evidence reference, context snapshot, and policy.
- [ ] Add configured skill roots, preflight freshness (15 minutes), role temperatures (0.1/0.2), and DeepSeek role overrides.
- [ ] Keep API keys environment-only and exclude them from all schema serializers.

## Task 2: Version and whitelist local professional skills

**Files:**
- Create: `backend/app/trading_room/skill_registry.py`
- Create: `backend/tests/trading_room/test_skill_registry.py`

- [ ] Test only approved skills and their direct declared references load.
- [ ] Test traversal, symlink escape, missing files, and non-whitelisted names fail closed.
- [ ] Test stable SHA-256 hashes over normalized complete contents and a changed hash marks the role unavailable until session restart/reconfirmation.
- [ ] Load Router, market-regime, position-risk, buy-signal, stop-loss, take-profit, fund query, announcement search, and fund-analysis instructions; explicitly exclude batch planner and sell execution.
- [ ] Return immutable `SkillBundle` objects for prompt construction and store the name/hash pair in each memo.

## Task 3: Build exposure confidence without claiming real-time holdings

**Files:**
- Create: `backend/app/trading_room/exposure.py`
- Create: `backend/tests/trading_room/test_exposure.py`

- [ ] Test index funds bind to the tracked index and produce `index_tracked/HIGH` when provenance is valid.
- [ ] Test active-fund reported exposure rejects missing `report_period_end`, even if a current NAV date exists.
- [ ] Test 60-trading-day regression output and confidence thresholds: HIGH `age<=60, R²>=0.80, agree`; MEDIUM `age<=120, R²>=0.70 or partial`; LOW otherwise/conflict.
- [ ] Implement duplicate-holding normalization, industry/theme aggregation, report/publish timestamps, beta/R²/window fields, and drift conflict reasons.
- [ ] Ensure LOW may explain/watch but cannot be the main evidence for immediate action.

## Task 4: Restore current subscription and channel state

**Files:**
- Create: `backend/app/trading_room/execution_preflight.py`
- Create: `backend/tests/trading_room/test_execution_preflight.py`
- Create: `backend/tests/fixtures/trading_room/announcements_001513.json`

- [ ] Use frozen official-announcement fixtures for 易方达信息产业混合 A/C and test chronological restore across limit/adjust/resume events.
- [ ] Match exact fund code, share class, customer scope, effective date, and latest applicable state.
- [ ] Return OPEN/LIMITED/SUSPENDED/UNKNOWN with daily limit, consumed/remaining limit, redemption state, announcement URL/time, query time, and channel confirmation.
- [ ] Test SUSPENDED => no action; LIMITED => clamp; UNKNOWN or unconfirmed channel => conditional only.
- [ ] Refresh at finalize when the snapshot is older than 15 minutes.
- [ ] Keep network calls behind an injectable adapter; unit tests never depend on the live announcement service.

## Task 5: Compute risk and the LightTradeGuard deterministically

**Files:**
- Create: `backend/app/trading_room/risk_metrics.py`
- Create: `backend/app/trading_room/guard.py`
- Create: `backend/tests/trading_room/test_risk_metrics.py`
- Create: `backend/tests/trading_room/test_guard.py`

- [ ] Test account drawdown at 5/7.5/10 boundaries and thesis/trend-break priority over percentage stop.
- [ ] Test fund allocation, holding return, peak drawdown, theme exposure, cash reserve, volatility, and correlation outputs.
- [ ] Test the guard intersection for buys: agent range ∩ manager remaining limit ∩ target headroom ∩ available cash after pending orders.
- [ ] Test sells never exceed settled holdings after pending sells.
- [ ] Test there is no hidden single-operation cap, forced batch, or invented risk budget.
- [ ] Test user-configured loss-width math is optional and absent by default.

## Task 6: Persist auditable sessions and policy versions

**Files:**
- Create: `backend/app/models/trading_room.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/trading_room/store.py`
- Create: `backend/tests/trading_room/test_store.py`

- [ ] Add SQLAlchemy entities for session, specialist memo, message, policy version/proposal, exposure snapshot, and trade-status snapshot.
- [ ] Store structured JSON plus explicit status/timestamps and foreign keys; do not store LLM/API secrets.
- [ ] Test session snapshots and policy versions are immutable after creation.
- [ ] Test feedback states `accepted`, `partial`, `ignored`, and `watch` persist with user-selected amount and note.

## Task 7: Add structured DeepSeek specialist execution

**Files:**
- Modify: `backend/app/llm/openai_compat.py`
- Modify: `backend/app/llm/registry.py`
- Create: `backend/app/trading_room/specialists/base.py`
- Create: `backend/app/trading_room/specialists/roles.py`
- Create: `backend/app/trading_room/specialists/__init__.py`
- Create: `backend/tests/trading_room/test_specialists.py`

- [ ] Test role resolution defaults to current configured DeepSeek model and never hard-codes deprecated model names.
- [ ] Test each response is parsed through the role Pydantic schema; malformed output receives exactly one JSON repair request and then becomes unavailable.
- [ ] Test round-one prompts contain the same immutable context hash and do not contain other memos.
- [ ] Test Skeptic output rejects score/amount/new-market-opinion fields and rejects findings without `evidence_ref` or `missing_field`.
- [ ] Add optional JSON-output payload support to the compatible client without relying on beta strict mode.
- [ ] Build role prompts from the verified skill bundle as system constraints and data/evidence as user content.

## Task 8: Orchestrate two rounds and preserve fail-closed semantics

**Files:**
- Create: `backend/app/trading_room/context.py`
- Create: `backend/app/trading_room/orchestrator.py`
- Create: `backend/tests/trading_room/test_orchestrator.py`

- [ ] Test context creation rejects formal actionability for mock/stale/missing-time critical inputs but still creates an explainable incomplete session.
- [ ] Test router order prioritizes account risk and excludes batch planner/sell execution.
- [ ] Test independent round one, deterministic conflict extraction, and round two limited to the conflict payload.
- [ ] Test buy scores >=80 yield immediate action only with no veto; 65–79 yields conditional; <65 yields watch; a guard/preflight failure downgrades the result.
- [ ] Test the recorder cannot invent an action absent from memos and the chair cannot exceed guarded ranges.

## Task 9: Expose trading room and policy APIs

**Files:**
- Create: `backend/app/api/v1/trading_room.py`
- Modify: `backend/app/api/v1/router.py`
- Create: `backend/tests/trading_room/test_api.py`

- [ ] Implement and test `GET /agent/trading-policy/templates`, `POST /agent/trading-policy/import`, and GET/POST current policy.
- [ ] Implement and test session create/get/message/finalize/action endpoints.
- [ ] Return 409 for finalize with missing target allocations, 422 for invalid final amount, and a structured non-executable response rather than a fabricated amount for unknown preflight state.
- [ ] Ensure all endpoints return source/time/confidence/skill/policy identifiers needed by the UI audit trail.

## Task 10: Build the daily room frontend

**Files:**
- Create: `frontend/src/types/tradingRoom.ts`
- Create: `frontend/src/api/tradingRoom.ts`
- Create: `frontend/src/components/trading-room/TradingRoomPage.tsx`
- Create: `frontend/src/components/trading-room/ContextSnapshotCard.tsx`
- Create: `frontend/src/components/trading-room/ExposureCard.tsx`
- Create: `frontend/src/components/trading-room/ExecutionStatusCard.tsx`
- Create: `frontend/src/components/trading-room/SpecialistRoundtable.tsx`
- Create: `frontend/src/components/trading-room/ConflictPanel.tsx`
- Create: `frontend/src/components/trading-room/DecisionDraftPanel.tsx`
- Create: `frontend/src/components/trading-room/PolicyImportPanel.tsx`
- Create: `frontend/src/components/trading-room/TradingRoomPage.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/layout/AppLayout.tsx`

- [ ] Test cold start imports the default template and clearly asks only for missing target allocations.
- [ ] Test incomplete/mock/LOW/UNKNOWN states display reasons and disable immediate executable confirmation.
- [ ] Test the roundtable shows each role, source/hash, confidence, evidence, and unavailable status.
- [ ] Test the final panel distinguishes immediate, conditional, watch, and no-action; it shows suggested vs guarded range and lets the user choose a valid final amount.
- [ ] Add a “今日讨论室” route/menu entry and reuse P0 trust/error components.

## Task 11: End-to-end shadow-mode verification

**Files:**
- Modify if needed: `README.md`
- Create: `docs/trading-room-shadow-mode.md`

- [ ] Run all backend and frontend tests/build.
- [ ] Run a deterministic fixture session for 易方达信息产业混合、通信主题、纳斯达克主题 with mocked DeepSeek responses and assert the saved audit trail.
- [ ] In a locally configured environment, run one live read-only session; do not place an order and do not print the API key.
- [ ] Browser-check policy import, missing-target flow, context evidence, roundtable conflict, conditional/no-action decisions, final amount validation, and feedback persistence.
- [ ] Review logs and API payloads for secrets, real-time-holdings overclaims, stale data, and unconfirmed channel status.
- [ ] Run `git diff --check`, review the branch diff, commit the MVP checkpoint, and push `agent/p0-data-trust`.

