# P0 Data Trust Implementation Plan

> **For Codex:** Execute this plan inline with `executing-plans`, one task at a time. Use `test-driven-development` for every behavior change and `verification-before-completion` before claiming completion.

**Goal:** Make live mode fail closed, label demo data unmistakably, normalize market API fields, harden settings secrets/numbers, and prevent one React subtree failure from blanking the application.

**Architecture:** Add one backend trust contract (`MarketDataMeta`) and make `MarketService` own source selection and validation. Keep existing response payloads compatible by adding `meta` at the top level. Add one frontend adapter boundary and one reusable state component so page components consume normalized models instead of guessing backend field names.

**Tech Stack:** FastAPI, Pydantic v2, pytest/pytest-asyncio, React 18, TypeScript, Axios, Ant Design, Vitest, Testing Library.

---

## Scope and acceptance

- `MARKET_DATA_MODE=live` is the default; no mock provider is called when a live source fails.
- `MARKET_DATA_MODE=demo` may call the current provider, but every response says `mode=demo`, `source=demo/mock`, and `is_mock=true`.
- Quotes, K-line, indices, heatmap, diagnosis, and sector rankings include compatible `meta`.
- Invalid critical market values return `meta.status=invalid` and are not treated as decision-grade data.
- Frontend maps snake_case once, distinguishes loading/empty/unavailable/invalid/stale/demo, and never substitutes `change` for `change_pct`.
- Feishu config never returns the complete webhook; blank updates preserve the stored value.
- Missing position numbers render `--`; a subtree exception renders a recovery panel.

## Task 1: Lock the backend trust contract with failing tests

**Files:**
- Create: `backend/tests/test_market_data_trust.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/schemas/market.py`

- [ ] Add tests that instantiate `MarketService` with a mocked failed bridge and assert live mode does not call `MarketDataProvider`.
- [ ] Add a demo-mode test asserting provider fallback and complete `meta`.
- [ ] Add an index validation test for non-positive price and non-finite/out-of-range `change_pct` returning `invalid`.
- [ ] Run `cd backend && pytest tests/test_market_data_trust.py -q`; expect import/schema failures.
- [ ] Add `market_data_mode: Literal["live", "demo"] = "live"` to settings and `MarketDataMeta` plus `meta` fields to all market response schemas.
- [ ] Re-run only the schema/config tests until they pass; service behavior remains red.

Contract to implement:

```python
class MarketDataMeta(BaseModel):
    source: str
    fetched_at: datetime
    mode: Literal["live", "demo"]
    status: Literal["ok", "empty", "unavailable", "invalid"]
    stale: bool = False
    is_mock: bool = False
    message: str | None = None
```

## Task 2: Centralize source selection and validation

**Files:**
- Create: `backend/app/services/market_data_trust.py`
- Modify: `backend/app/services/market_service.py`
- Modify: `backend/tests/test_market_data_trust.py`

- [ ] Test a pure `validate_index_rows` function: valid values survive, invalid rows are removed, and any rejected critical row marks the response `invalid`.
- [ ] Test live failures for indices, heatmap, diagnosis sub-sources, and sector rankings never enter mock functions.
- [ ] Implement helpers for `ok`, `empty`, `unavailable`, `invalid`, and `demo` metadata using timezone-aware timestamps.
- [ ] Update `get_quotes`, `get_kline`, `get_global_indices`, `get_heatmap`, `get_diagnosis`, and `get_sector_rankings` to use one source-selection rule.
- [ ] In demo mode only, preserve current generated rows and label them `demo/mock`.
- [ ] Ensure logs contain exception class/source name only, never API keys, URLs with tokens, or raw provider payloads.
- [ ] Run `cd backend && pytest tests/test_market_data_trust.py -q`; expect green.

Decision rule:

```python
if live_result_is_valid:
    return payload_with(ok_meta(source))
if settings.market_data_mode == "demo":
    return payload_with(demo_meta(), mock_rows)
return payload_with(unavailable_meta(source), empty_payload)
```

## Task 3: Secure Feishu configuration updates

**Files:**
- Create: `backend/tests/test_feishu_config_security.py`
- Modify: `backend/app/api/v1/feishu.py`
- Modify: `frontend/src/components/feishu/FeishuConfigCard.tsx`

- [ ] Test `GET /feishu/config` exposes `configured` and `webhook_hint`, but no `webhook_url`.
- [ ] Test a blank `PUT /feishu/config` preserves the newest configured webhook while saving notification flags.
- [ ] Test a nonblank update replaces the webhook and the response remains secret-free.
- [ ] Implement a URL masker that retains only a safe prefix and last four characters.
- [ ] Make `webhook_url` optional/default blank in the update schema and resolve the effective value server-side.
- [ ] Change the frontend input to stay empty after load and show “已配置，留空则不修改” plus the masked hint.
- [ ] Run `cd backend && pytest tests/test_feishu_config_security.py -q`.

## Task 4: Add the frontend trust adapter and tests

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/vite.config.ts`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/types/dataTrust.ts`
- Create: `frontend/src/api/adapters/market.ts`
- Create: `frontend/src/api/adapters/market.test.ts`
- Modify: `frontend/src/api/market.ts`
- Modify: `frontend/src/types/market.ts`

- [ ] Install Vitest, jsdom, Testing Library React, and jest-dom as dev dependencies.
- [ ] Add `test` and `test:run` scripts plus jsdom setup.
- [ ] Write adapter tests proving `change_pct -> changePct`, `fetched_at -> fetchedAt`, and `is_mock -> isMock`.
- [ ] Add the regression test: `{change: 12.5}` without `change_pct` is invalid instead of becoming `12.5%`.
- [ ] Add tests for `ok`, `empty`, `unavailable`, `invalid`, `stale`, and demo mapping.
- [ ] Implement `MarketDataMeta`, `TrustedData<T>`, finite-number guards, and endpoint-specific adapters.
- [ ] Change `marketApi` methods to return normalized `TrustedData<T>` objects.
- [ ] Run `cd frontend && npm run test:run -- src/api/adapters/market.test.ts`.

## Task 5: Render trustworthy states on critical pages

**Files:**
- Create: `frontend/src/components/common/DataStatePanel.tsx`
- Create: `frontend/src/components/common/DataStatePanel.test.tsx`
- Create: `frontend/src/components/common/DemoDataBanner.tsx`
- Modify: `frontend/src/components/dashboard/DashboardPage.tsx`
- Modify: `frontend/src/components/market/MarketPage.tsx`
- Modify: `frontend/src/components/sector/SectorRankingBoard.tsx`
- Modify: `frontend/src/components/layout/AppLayout.tsx`

- [ ] Test the six state presentations and retry callback.
- [ ] Implement the shared panel with explicit Chinese copy and fetched time for stale data.
- [ ] Use normalized query results on dashboard, market, and sector pages.
- [ ] Render a fixed demo warning whenever any active critical query is mock/demo; never use normal positive/negative coloring as the only demo indicator.
- [ ] Keep existing tables/charts when status is `ok`; show empty/unavailable/invalid panels before rendering data widgets.
- [ ] Run focused frontend tests and `npm run build`.

## Task 6: Harden number formatting and React failure recovery

**Files:**
- Create: `frontend/src/utils/format.ts`
- Create: `frontend/src/utils/format.test.ts`
- Create: `frontend/src/components/common/AppErrorBoundary.tsx`
- Create: `frontend/src/components/common/AppErrorBoundary.test.tsx`
- Modify: `frontend/src/components/settings/SettingsPage.tsx`
- Modify: `frontend/src/main.tsx`

- [ ] Test that `null`, `undefined`, `NaN`, and infinities render `--`; valid values retain requested decimals.
- [ ] Replace unsafe position `.toFixed()` calls in Settings with the shared formatter.
- [ ] Test a throwing child is caught and a reload action is shown without stack/request content.
- [ ] Wrap the router/application subtree in the error boundary.
- [ ] Run all frontend tests and build.

## Task 7: Regression verification and browser evidence

**Files:**
- Modify if needed: `backend/.env.example`
- Modify if needed: `README.md`

- [ ] Document `MARKET_DATA_MODE=live|demo` and the fact that live mode intentionally displays unavailable states.
- [ ] Run `cd backend && pytest -q`.
- [ ] Run `cd frontend && npm run test:run && npm run build`.
- [ ] Start backend/frontend locally and verify dashboard, market, sectors, and settings in live-failure mode.
- [ ] Repeat in demo mode and verify the fixed demo warning plus response metadata.
- [ ] Review `git diff --check`, `git status --short`, and scan changed files for secrets.
- [ ] Commit as one coherent P0 checkpoint before starting the discussion room plan.

