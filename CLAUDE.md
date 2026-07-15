# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

Two apps in one repo, driven from the top-level `Makefile`:

- `backend/` — FastAPI + SQLAlchemy (async, aiosqlite) + APScheduler. Package name `fund-investment-agent`, installed with `pip install -e ".[dev]"`. Entry point `app.main:app`.
- `frontend/` — React 18 + TypeScript + Vite + Ant Design + Zustand + TanStack Query + ECharts. Vite dev server proxies `/api` and `/ws` to `http://localhost:8000`.
- `skills/` and `~/.codex/skills` / `~/.openclaw/workspace/skills` — external Skill packages the backend invokes via the SkillBridge (see below). Paths are configurable through `trading_skill_root` / `market_skill_root`.
- `docs/` — authoritative behavioural specs (`market-data-modes.md`, `trading-room-shadow-mode.md`, `plans/`). Root-level `*.md` (`ARCHITECTURE_REDESIGN_V2.md`, `CORE_ARCHITECTURE_REFINED.md`, `SKILL_INTEGRATION_*.md`, …) are design proposals, not always the current state — verify against code before quoting them.

## Common commands

Backend (run from repo root):

```bash
make install                 # pip install -e "backend[.dev]"
make dev                     # uvicorn app.main:app --reload --port 8000
make test                    # pytest backend/tests -v
cd backend && pytest tests/trading_room/test_orchestrator.py -v      # one file
cd backend && pytest tests/trading_room/test_orchestrator.py::TestX::test_y  # one test
cd backend && ruff check app tests
cd backend && black app tests
```

Frontend:

```bash
make fe-install              # npm install
make fe-dev                  # vite dev server on :5173
make fe-build                # tsc && vite build
cd frontend && npm run lint
cd frontend && npm test                                # vitest --watch
cd frontend && npm run test:run                        # single pass
cd frontend && npx vitest run src/components/foo.test.tsx   # one file
```

`make clean` wipes `backend/data/*.db`. There is no combined `all-dev` — run `make dev` and `make fe-dev` in separate terminals.

## LLM layer — **do not import provider SDKs directly**

Every model call must go through `app.llm.registry.get_llm_client(role)` (`backend/app/llm/registry.py`). The registry resolves a role → `LLMConfig` and returns a cached `LLMClient` implementation (`AnthropicClient` or `OpenAICompatClient`). New providers plug in there, not at call sites. The Anthropic Python SDK is deliberately not a dependency — DeepSeek / Qwen / Moonshot / Kimi / Zhipu / OpenAI-compatible endpoints all share `OpenAICompatClient`, and tool-use format translation lives inside the client, not in agents.

Configuration comes from `app.config.settings` (pydantic-settings, reads `.env` and `.env.local`; `.env.local` holds secrets):

- Default: `llm_provider` / `llm_model` / `llm_api_key` / `llm_base_url`.
- Per-role overrides (empty = fall back to default): `llm_<role>_*` where role ∈ `{intent_router, advisor, scout, guardian}`.
- Trading-room specialists share a single credential set: `trading_room_llm_*`. All trading-room roles (`market_regime`, `theme_fund`, `portfolio_risk`, `buy`, `sell_protection`, `skeptic`, `recorder`, `chair`) route through those variables so the room can run on DeepSeek while the rest of the app runs on Claude.
- Legacy `anthropic_*` fields still seed the default when `llm_provider=anthropic` and the corresponding `llm_*` value is empty. For `anthropic`, `anthropic_auth_token` (Bearer, e.g. ark proxy) is honored in addition to `x-api-key`.
- `llm_credentials_configured(role)` is the gate — it returns true if either an API key or a Bearer token is present.

## Backend architecture

FastAPI app is composed in `app/main.py`:

1. `init_db()` runs on startup (SQLAlchemy async engine over `data/financial.db` by default).
2. Skill strategies register into the module-level `SkillBridge` (`app/skills/bridge.py`) in priority order: `DirectAPIStrategy` (real data pulls, cheap), `ClaudeAPIStrategy` (only if `anthropic_api_key` is set), `ClaudeCLIStrategy` (falls back to the Claude Code CLI for proprietary skills). Requests are cached with a per-call `cache_ttl_seconds`.
3. `setup_scheduler()` starts APScheduler jobs (guardian, monitoring alerts, sector monitors).
4. All routes live under `app/api/v1/router.py` → `market`, `yangjibao`, `agent`, `backtest`, `feishu`, `trading_room`. WebSockets live in `app/api/ws/`.
5. CORS is open to `http://localhost:5173` and `:3000`; the root `/` redirects to the Vite dev server for browser visits.

Domain modules under `app/`:

- `trading_room/` — the daily discussion room (currently shadow-only, no broker link). Read `docs/trading-room-shadow-mode.md` before touching it. Two-round orchestration is in `orchestrator.py`: round 1 fans a hash-pinned `TradingContextSnapshot` (`context.py`) out to specialists in `ROUND_ONE_ROUTE` order; `LightTradeGuard` (`guard.py`) applies `TradingPolicy` caps (`policy.py`); the `chair` and `recorder` roles synthesize round 2. Persistence for sessions, memos, and policy versions goes through `store.py`. `execution_preflight.py` gates immediate execution on channel confirmation and data freshness (`execution_preflight_fresh_minutes`).
- `services/` — data-provider and decision services. `market_data_provider.py` + `market_data_trust.py` enforce the trust boundary described below. `evidence_bus.py`, `decision_store.py`, `outcome_tracker.py`, `holding_health.py`, `portfolio_advice_service.py`, `guardian.py`, `sector_*` are the main entry points for other layers.
- `skills/` — SkillBridge + strategies. `direct_api.py` handles ETF/fund data via real HTTP APIs; `claude_api.py` uses Anthropic Messages when configured; `claude_cli.py` shells out to the Claude Code CLI for skills that ship as prompt packages (e.g. `announcement-search`, `hithink-fund-selector`).
- `agents/`, `analysis/`, `backtest/` — LLM-orchestrated agents (prompt registry in `agents/prompts/`), analysis helpers, and the backtest strategy compiler (`backtest/strategy_compiler_agent.py`).
- `models/`, `schemas/` — SQLAlchemy ORM models and Pydantic schemas. Trading-room ORM lives in `models/trading_room.py`.
- `feishu/`, `tasks/`, `yangjibao/` — Feishu (Lark) card push, APScheduler jobs, and Yangjibao (养基宝) fund-valuation integration (`browser-plug-api`).

### Market-data trust boundary

Enforced across the backend, treat as a hard invariant. See `docs/market-data-modes.md`.

- `settings.market_data_mode` is `"live"` (default) or `"demo"`.
- `live` mode fails closed: if a data source is down, a critical field is missing, or a number is out of range, the response returns `unavailable` / `invalid` with a `meta` block (source, as-of, mode, is_mock, freshness, safety note). Never silently substitute mock data in live mode.
- `demo` mode always tags responses `mode=demo`, `source=demo/mock`, `is_mock=true`. UI must render the "not for real trading" banner.
- Numeric fields: `change` is absolute change, `change_pct` is percent change — they are not interchangeable.
- Trading-room specialists must receive `TradingContextSnapshot` inputs with `DataConfidence` set; mock / stale / low-confidence inputs may inform discussion but can never be used to justify `immediately_executable = true`.

## Frontend architecture

- Bundler + tests via Vite + Vitest (jsdom, `src/test/setup.ts`). `@/` alias resolves to `src/`.
- `src/api/` — Axios clients (`client.ts`, `tradingRoom.ts`, ...). All backend calls proxy through `/api`.
- `src/components/` — feature-scoped folders (`trading-room/`, `sector/`, `guardian/`, `market/`, `portfolio/`, `fund/`, `alerts/`, `signal/`, `backtest/`, `agent/`, `settings/`, `dashboard/`, `layout/`, `common/`). Each feature owns its page component and sub-components.
- `src/types/` — TS mirrors of backend Pydantic schemas. Keep them in sync when API changes.
- State: TanStack Query for server state (session-scoped caching), Zustand for local UI state. No Redux.
- Charts: `echarts-for-react`. Markdown: `react-markdown`.

## Testing conventions

- Backend uses `pytest` + `pytest-asyncio`. Fixtures live in `backend/tests/fixtures/`. Trading-room tests are namespaced under `backend/tests/trading_room/`.
- Frontend uses Vitest + React Testing Library (`@testing-library/react`, `@testing-library/jest-dom`). `puppeteer-core` is available for browser-driven checks.
- Full backend suite: `make test`. Full frontend suite: `cd frontend && npm run test:run`. There is no combined runner — CI-style verification runs both.

## Working with this repo

- Branch naming used in-tree: `agent/<topic>` (e.g. `agent/p0-data-trust`). PRs target `main`.
- Recent commits show the preferred commit-message shape: short imperative subject like `feat: derive account peak from trusted snapshots`.
- The `docs/plans/` directory is where multi-step plans get checked in; consult it before starting new work that overlaps ongoing efforts.
