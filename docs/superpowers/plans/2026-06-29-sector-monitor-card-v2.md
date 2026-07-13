# Sector Monitor Card V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Feishu card that monitors the user's focused sectors, maps them to ETFs and real Yangjibao holdings, and presents concise graphical signals.

**Architecture:** Keep market/holding mapping in a focused service module and keep Feishu rendering in the card builder. Use public market data as the stable path and SkillBridge diagnostics as optional enrichment so notifications do not fail when proprietary skills are unavailable.

**Tech Stack:** FastAPI, Python, SQLite Yangjibao holdings, Feishu webhook interactive cards, pytest.

## Global Constraints

- Keep the message decision-oriented: conclusion first, details second.
- Show fund names, not only fund codes.
- Include watched sectors beyond current holdings: communication/optical module, battery, semiconductor, nonferrous metals, Hong Kong internet, US tech, broad US indices, consumption.
- Use Feishu-safe `lark_md` card content.
- Do not block the notification if SkillBridge analysis fails.

---

### Task 1: Watch Basket And Visual Rows

**Files:**
- Modify: `backend/app/services/sector_card_service.py`
- Modify: `backend/app/feishu/cards.py`
- Test: `backend/tests/test_feishu_cards.py`

**Interfaces:**
- Produces: `build_focus_watch_rows(sectors: list[dict]) -> list[dict]`
- Produces: `build_signal_bar(value: float, width: int = 10) -> str`
- Consumes: `build_sector_summary_card(...)`

- [ ] **Step 1: Write failing tests**

Add tests that assert watched rows include communication/optical module, battery, semiconductor, nonferrous metals, and that card content contains bar glyphs plus ETF names.

- [ ] **Step 2: Run focused tests**

Run: `cd backend && pytest tests/test_feishu_cards.py -q`
Expected: FAIL because new functions/card fields are missing.

- [ ] **Step 3: Implement watch basket and card rendering**

Add a watch basket config in `sector_card_service.py`, create visual row strings, and extend the card builder with watched rows.

- [ ] **Step 4: Verify tests pass**

Run: `cd backend && pytest tests/test_feishu_cards.py -q`
Expected: PASS.

### Task 2: Skill Diagnostics As Optional Enrichment

**Files:**
- Modify: `backend/app/services/sector_card_service.py`
- Modify: `backend/app/api/v1/feishu.py`

**Interfaces:**
- Produces: `async build_live_sector_card(use_skill: bool = True) -> dict`
- Consumes: `bridge.invoke_simple("sector_monitor", ...)`

- [ ] **Step 1: Write failing test**

Add a service test with a fake skill result proving the card includes a short skill diagnostic when available and still builds without it.

- [ ] **Step 2: Run focused tests**

Run: `cd backend && pytest tests/test_sector_card_service.py -q`
Expected: FAIL because async card builder and skill enrichment are missing.

- [ ] **Step 3: Implement optional SkillBridge enrichment**

Call sector monitor/rotation through SkillBridge with short timeout and append one concise diagnostic line. Catch exceptions and continue with public data.

- [ ] **Step 4: Verify and push**

Run tests, restart backend, call `POST /api/v1/feishu/test-sector-card`, and confirm `ok: true`.
