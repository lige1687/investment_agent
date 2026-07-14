"""REST API contracts for policy cold-start and shadow-mode sessions."""

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app


NOW = datetime.now(timezone.utc)


async def _default_fake_portfolio(self):
    return {
        "connected": True,
        "total_value": 20_000,
        "synced_at": NOW.isoformat(),
        "positions": [{
            "symbol": "001513", "name": "易方达信息产业混合A",
            "type": "fund", "market_value": 20_000,
        }],
    }


@pytest_asyncio.fixture
async def client(monkeypatch):
    from app import models as _models  # noqa: F401

    monkeypatch.setattr(
        "app.services.yangjibao_service.YangjibaoService.get_local_portfolio",
        _default_fake_portfolio,
    )

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as value:
        yield value
    app.dependency_overrides.clear()
    await engine.dispose()


def _session_payload(policy_version_id, *, preflight_status="OPEN", channel_confirmed=True):
    maximum_action = (
        "NO_ACTION" if preflight_status == "SUSPENDED"
        else "CONDITIONAL" if preflight_status == "UNKNOWN" or not channel_confirmed
        else "IMMEDIATE"
    )
    payload = {
        "policy_version_id": policy_version_id,
        "as_of": NOW.isoformat(),
        "data_mode": "live",
        "market_dates": {"CN": "2026-07-13", "US": "2026-07-10"},
        "themes": {"通信": {"phase": "startup"}},
        "skill_versions": {"batch-trading-router": "hash-1"},
        "critical_inputs": [
            {
                "key": "quotes",
                "source": "live-provider",
                "as_of": NOW.isoformat(),
                "confidence": "HIGH",
                "is_mock": False,
                "stale": False,
            }
        ],
        "start_discussion": False,
    }
    payload["trade_status_snapshots"] = [{
        "fund_code": "001513",
        "share_class": "A",
        "customer_scope": "retail",
        "manager_status": preflight_status,
        "redemption_status": "OPEN",
        "queried_at": NOW.isoformat(),
        "channel": "支付宝",
        "channel_confirmed": channel_confirmed,
        "maximum_action_class": maximum_action,
    }]
    return payload


async def _import_policy(client, targets):
    response = await client.post(
        "/api/v1/agent/trading-policy/import",
        json={"template_id": "mid-term-theme-v1", "target_allocations": targets},
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_policy_template_import_and_current_policy_cold_start(client):
    templates = await client.get("/api/v1/agent/trading-policy/templates")
    assert templates.status_code == 200
    assert templates.json()[0]["template_id"] == "mid-term-theme-v1"

    imported = await _import_policy(client, [])
    assert imported["ready"] is False
    assert imported["missing_confirmations"] == ["target_allocations"]
    assert imported["version_id"]

    current = await client.get("/api/v1/agent/trading-policy")
    assert current.status_code == 200
    assert current.json()["version_id"] == imported["version_id"]


@pytest.mark.asyncio
async def test_session_create_get_and_message_preserve_audit_identifiers(client):
    policy = await _import_policy(
        client, [{"scope": "theme", "key": "通信", "target_pct": 0.3}]
    )
    created = await client.post(
        "/api/v1/agent/trading-room/sessions",
        json=_session_payload(policy["version_id"]),
    )
    assert created.status_code == 200
    body = created.json()
    assert body["policy_version_id"] == policy["version_id"]
    assert body["context"]["context_hash"]
    assert body["context"]["critical_inputs"][0]["source"] == "live-provider"
    assert body["context"]["critical_inputs"][0]["as_of"]

    message = await client.post(
        f"/api/v1/agent/trading-room/sessions/{body['session_id']}/messages",
        json={"content": "通信目标仓位先按 30% 讨论", "payload": {"topic": "通信"}},
    )
    assert message.status_code == 200

    replay = await client.get(
        f"/api/v1/agent/trading-room/sessions/{body['session_id']}"
    )
    assert replay.status_code == 200
    assert replay.json()["messages"][0]["content"] == "通信目标仓位先按 30% 讨论"


@pytest.mark.asyncio
async def test_finalize_requires_confirmed_target_allocations(client):
    policy = await _import_policy(client, [])
    session = (
        await client.post(
            "/api/v1/agent/trading-room/sessions",
            json=_session_payload(
                policy["version_id"], preflight_status="UNKNOWN", channel_confirmed=False
            ),
        )
    ).json()

    response = await client.post(
        f"/api/v1/agent/trading-room/sessions/{session['session_id']}/finalize",
        json=_finalize_payload(),
    )
    assert response.status_code == 409
    assert "target_allocations" in response.json()["detail"]


def _finalize_payload(*, status="OPEN", confirmed=True, selected_amount=None):
    payload = {
        "score": 82,
        "has_veto": False,
        "suggested_range": {"minimum": 1000, "maximum": 3000},
        "preflight": {
            "fund_code": "001513",
            "share_class": "A",
            "customer_scope": "retail",
            "manager_status": status,
            "redemption_status": "OPEN",
            "queried_at": NOW.isoformat(),
            "channel_confirmed": confirmed,
            "maximum_action_class": (
                "CONDITIONAL" if status == "UNKNOWN" or not confirmed else "IMMEDIATE"
            ),
        },
        "execution_funding": {
            "available_cash": 20000,
            "pending_buy_amount": 0,
            "consumed_purchase_today": 0,
        },
    }
    if selected_amount is not None:
        payload["selected_amount"] = selected_amount
    return payload


@pytest.mark.asyncio
async def test_unknown_preflight_returns_non_executable_without_guarded_amount(client):
    policy = await _import_policy(
        client, [{"scope": "fund", "key": "001513", "target_pct": 0.3}]
    )
    session = (
        await client.post(
            "/api/v1/agent/trading-room/sessions",
            json=_session_payload(
                policy["version_id"], preflight_status="UNKNOWN", channel_confirmed=False
            ),
        )
    ).json()

    response = await client.post(
        f"/api/v1/agent/trading-room/sessions/{session['session_id']}/finalize",
        json=_finalize_payload(status="UNKNOWN", confirmed=False),
    )
    assert response.status_code == 200
    decision = response.json()["decision"]
    assert decision["action_class"] == "CONDITIONAL"
    assert decision["guarded_range"] is None
    assert decision["immediately_executable"] is False
    assert "preflight_unknown" in decision["reasons"]


@pytest.mark.asyncio
async def test_invalid_final_amount_returns_422_and_feedback_persists(client, monkeypatch):
    async def fake_portfolio(self):
        return {
            "connected": True, "total_value": 50_000,
            "synced_at": NOW.isoformat(),
            "positions": [{"symbol": "003095", "name": "其他基金", "type": "fund", "market_value": 50_000}],
        }
    monkeypatch.setattr(
        "app.services.yangjibao_service.YangjibaoService.get_local_portfolio",
        fake_portfolio,
    )
    policy = await _import_policy(
        client, [{"scope": "fund", "key": "001513", "target_pct": 0.3}]
    )
    payload = _session_payload(policy["version_id"])
    session = (
        await client.post(
            "/api/v1/agent/trading-room/sessions",
            json=payload,
        )
    ).json()
    session_id = session["session_id"]

    invalid = await client.post(
        f"/api/v1/agent/trading-room/sessions/{session_id}/finalize",
        json=_finalize_payload(selected_amount=5000),
    )
    assert invalid.status_code == 422

    finalized = await client.post(
        f"/api/v1/agent/trading-room/sessions/{session_id}/finalize",
        json=_finalize_payload(selected_amount=2000),
    )
    assert finalized.status_code == 200

    action = await client.post(
        f"/api/v1/agent/trading-room/sessions/{session_id}/actions",
        json={"state": "partial", "selected_amount": 1500, "note": "只买一半"},
    )
    assert action.status_code == 200
    assert action.json()["feedback_state"] == "partial"
    assert action.json()["selected_amount"] == 1500


@pytest.mark.asyncio
async def test_live_preflight_returns_manager_limit_but_keeps_channel_unconfirmed(
    client, monkeypatch
):
    async def fake_search(self, **kwargs):
        assert kwargs["fund_code"] == "001513"
        return [{
            "fund_code": "001513",
            "share_classes": ["A", "C"],
            "customer_scope": "all",
            "action": "LIMITED",
            "effective_date": "2026-06-25",
            "published_at": "2026-06-25T00:00:00+08:00",
            "purchase_limit": 10000,
            "title": "调整大额申购限制",
            "url": "https://example.test/limit.pdf",
        }]

    monkeypatch.setattr(
        "app.api.v1.trading_room.IwencaiAnnouncementProvider.search_fund",
        fake_search,
    )
    response = await client.post(
        "/api/v1/agent/trading-room/preflight",
        json={
            "fund_code": "001513",
            "fund_name": "易方达信息产业混合A",
            "share_class": "A",
            "customer_scope": "retail",
            "channel": "支付宝",
            "channel_confirmed": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["manager_status"] == "LIMITED"
    assert body["daily_purchase_limit"] == 10000
    assert body["manager_source"] == "announcement-search"
    assert body["channel"] == "支付宝"
    assert body["channel_confirmed"] is False
    assert body["maximum_action_class"] == "CONDITIONAL"


@pytest.mark.asyncio
async def test_finalize_uses_saved_preflight_instead_of_client_claim(client):
    policy = await _import_policy(
        client, [{"scope": "fund", "key": "001513", "target_pct": 0.3}]
    )
    session = (
        await client.post(
            "/api/v1/agent/trading-room/sessions",
            json=_session_payload(
                policy["version_id"], preflight_status="SUSPENDED", channel_confirmed=True
            ),
        )
    ).json()

    # The caller claims OPEN, but the immutable session snapshot says SUSPENDED.
    response = await client.post(
        f"/api/v1/agent/trading-room/sessions/{session['session_id']}/finalize",
        json=_finalize_payload(status="OPEN", confirmed=True),
    )
    assert response.status_code == 200
    assert response.json()["decision"]["action_class"] == "NO_ACTION"
    assert response.json()["decision"]["guarded_range"] is None


@pytest.mark.asyncio
async def test_live_session_replaces_client_trade_status_with_server_preflight(
    client, monkeypatch
):
    async def fake_search(self, **kwargs):
        return [{
            "fund_code": kwargs["fund_code"],
            "share_classes": [kwargs["share_class"]],
            "customer_scope": "all",
            "action": "LIMITED",
            "effective_date": "2026-06-25",
            "published_at": "2026-06-25T00:00:00+08:00",
            "purchase_limit": 10000,
            "title": "服务端查到的限购公告",
            "url": "https://example.test/server-limit.pdf",
        }]

    monkeypatch.setattr(
        "app.api.v1.trading_room.IwencaiAnnouncementProvider.search_fund",
        fake_search,
    )
    policy = await _import_policy(
        client, [{"scope": "fund", "key": "001513", "target_pct": 0.3}]
    )
    payload = _session_payload(policy["version_id"], preflight_status="OPEN")
    payload["positions"] = [{
        "symbol": "001513", "name": "易方达信息产业混合A", "type": "fund",
        "market_value": 20000,
    }]
    payload["funds"] = {"001513": {"name": "易方达信息产业混合A"}}
    payload["start_discussion"] = True

    response = await client.post("/api/v1/agent/trading-room/sessions", json=payload)
    assert response.status_code == 200
    statuses = response.json()["trade_status_snapshots"]
    assert len(statuses) == 1
    assert statuses[0]["manager_status"] == "LIMITED"
    assert statuses[0]["daily_purchase_limit"] == 10000
    assert statuses[0]["announcement_url"].endswith("server-limit.pdf")


@pytest.mark.asyncio
async def test_finalize_recomputes_cash_and_allocation_from_immutable_context(client, monkeypatch):
    async def fake_portfolio(self):
        return {
            "connected": True, "total_value": 50_000,
            "synced_at": NOW.isoformat(),
            "positions": [{"symbol": "003095", "name": "其他基金", "type": "fund", "market_value": 50_000}],
        }
    monkeypatch.setattr(
        "app.services.yangjibao_service.YangjibaoService.get_local_portfolio",
        fake_portfolio,
    )
    policy = await _import_policy(
        client, [{"scope": "fund", "key": "001513", "target_pct": 0.3}]
    )
    payload = _session_payload(policy["version_id"])
    session = (
        await client.post("/api/v1/agent/trading-room/sessions", json=payload)
    ).json()
    claimed = _finalize_payload()
    claimed["execution_funding"]["available_cash"] = 500

    response = await client.post(
        f"/api/v1/agent/trading-room/sessions/{session['session_id']}/finalize",
        json=claimed,
    )
    assert response.status_code == 200
    decision = response.json()["decision"]
    assert decision["action_class"] == "NO_ACTION"
    assert decision["guarded_range"] is None
    assert "available_cash" in decision["reasons"]


@pytest.mark.asyncio
async def test_funding_required_for_finalize(client):
    policy = await _import_policy(
        client, [{"scope": "fund", "key": "001513", "target_pct": 0.3}]
    )
    session = (
        await client.post(
            "/api/v1/agent/trading-room/sessions",
            json=_session_payload(policy["version_id"]),
        )
    ).json()

    payload = _finalize_payload()
    payload.pop("guard_inputs", None)
    payload["execution_funding"] = None
    response = await client.post(
        f"/api/v1/agent/trading-room/sessions/{session['session_id']}/finalize",
        json=payload,
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "available_cash_confirmation_required"


@pytest.mark.asyncio
async def test_client_cannot_fake_equity_or_target(client, monkeypatch):
    async def fake_portfolio(self):
        return {
            "connected": True, "total_value": 50_000,
            "synced_at": NOW.isoformat(),
            "positions": [{"symbol": "003095", "name": "其他基金", "type": "fund", "market_value": 50_000}],
        }
    monkeypatch.setattr(
        "app.services.yangjibao_service.YangjibaoService.get_local_portfolio",
        fake_portfolio,
    )
    policy = await _import_policy(
        client, [{"scope": "fund", "key": "001513", "target_pct": 0.3}]
    )
    payload = _session_payload(policy["version_id"])
    session = (
        await client.post(
            "/api/v1/agent/trading-room/sessions", json=payload,
        )
    ).json()

    payload2 = _finalize_payload()
    payload2.pop("guard_inputs", None)
    payload2["execution_funding"] = {
        "available_cash": 500,
        "pending_buy_amount": 0,
        "consumed_purchase_today": 0,
    }
    response = await client.post(
        f"/api/v1/agent/trading-room/sessions/{session['session_id']}/finalize",
        json=payload2,
    )
    decision = response.json()["decision"]
    assert decision["guarded_range"] is None
    assert "available_cash" in decision["reasons"]


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
        "app.services.yangjibao_service.YangjibaoService.get_local_portfolio",
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


@pytest.mark.asyncio
async def test_empty_server_portfolio_returns_409(client, monkeypatch):
    async def fake_portfolio(self):
        return {
            "connected": True,
            "total_value": 0,
            "synced_at": NOW.isoformat(),
            "positions": [],
        }

    monkeypatch.setattr(
        "app.services.yangjibao_service.YangjibaoService.get_local_portfolio",
        fake_portfolio,
    )
    policy = await _import_policy(
        client, [{"scope": "fund", "key": "001513", "target_pct": 0.3}],
    )
    payload = _session_payload(policy["version_id"])
    for key in ("positions", "cash", "equity", "peak_equity", "pending_orders", "funds"):
        payload.pop(key, None)

    response = await client.post("/api/v1/agent/trading-room/sessions", json=payload)

    assert response.status_code == 409
    assert response.json()["detail"] == "synced_portfolio_empty"


@pytest.mark.asyncio
async def test_current_policy_returns_latest_ready_version(client):
    first = await _import_policy(client, [])
    assert first["ready"] is False

    targets = [{"scope": "theme", "key": "通信", "target_pct": 0.25}]
    ready = await _import_policy(client, targets)
    assert ready["ready"] is True

    current = await client.get("/api/v1/agent/trading-policy")
    assert current.status_code == 200
    body = current.json()
    assert body["version_id"] == ready["version_id"]
    assert body["ready"] is True
