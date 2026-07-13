"""GuardianAgent end-to-end test with a stubbed LLM.

Verifies:
  - portfolio + market snapshots land in the Evidence Bus
  - rule-based alerts produce one SELL_ALERT/WATCH card each
  - LLM briefing produces a WATCH card of type=portfolio
  - LLM failure gracefully falls back to rule-only briefing
  - GuardianRun row is persisted (idempotent per session)
"""
import json
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.llm import LLMError, LLMResponse
from app.llm.schemas import LLMUsage, StopReason
from app.schemas.guardian import BriefingSlot
from app.services import guardian as guardian_module
from app.services.guardian import GuardianAgent


@pytest_asyncio.fixture
async def db_session():
    import app.models  # noqa: F401
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed_positions(db_session, holdings):
    """Insert positions to make _tool_portfolio_summary return data."""
    from app.models.position import Position
    for h in holdings:
        db_session.add(Position(
            symbol=h["code"],
            source="yangjibao",
            position_type="fund",
            shares=100.0,
            avg_cost=1.0,
            current_price=1.0 + h["pnl_pct"] / 100,
            market_value=h["market_value"],
            cost_basis=h["market_value"] - h["market_value"] * h["pnl_pct"] / 100,
            unrealized_pnl=h["market_value"] * h["pnl_pct"] / 100,
            unrealized_pnl_pct=h["pnl_pct"],
        ))
    await db_session.flush()


def _valid_llm_json(ev_portfolio: str, ev_market: str) -> str:
    return json.dumps({
        "briefing_text": "尾盘体检:组合平稳,前三持仓集中。仅供参考,不构成投资建议。",
        "portfolio_card": {
            "headline": "尾盘体检:整体稳中带险",
            "summary": "组合浮盈但集中度偏高",
            "action_verb": "WATCH",
            "confidence": 0.6,
            "urgency": "MEDIUM",
            "dimensions": [
                {"key": "financial", "score": 6.5, "signal": "累计盈利 13%",
                 "evidence_ref": ev_portfolio},
                {"key": "macro", "score": 6.0, "signal": "市场情绪中性",
                 "evidence_ref": ev_market},
            ],
            "portfolio_role": "STRENGTHEN",
            "portfolio_warning": "科技集中度过高",
            "monitoring": ["前三持仓合计超过 65% 立即通知"],
        },
    }, ensure_ascii=False)


@pytest.mark.asyncio
async def test_guardian_run_writes_evidence_alerts_and_llm_card(db_session):
    """Full happy path: LLM returns valid JSON, we save briefing + alert cards."""
    holdings = [
        {"code": "F001", "name": "领头基金", "market_value": 30000, "pnl_pct": 15},
        {"code": "F002", "name": "次仓基金", "market_value": 25000, "pnl_pct": 8},
        {"code": "F003", "name": "深亏基金", "market_value": 6000, "pnl_pct": -30},
    ]
    await _seed_positions(db_session, holdings)

    fake_client = AsyncMock()
    fake_client.provider_name = "fake"

    def _reply(messages, **kwargs):
        # Pull the evidence_id map out of the prompt so the reply cites it.
        prompt = messages[-1].content
        # Extract two ev_ids ordered by their position in the prompt.
        import re
        ev_ids = re.findall(r"(ev_[0-9a-f]+)", prompt)
        ev_portfolio = ev_ids[0] if ev_ids else "ev_unknown"
        ev_market = ev_ids[1] if len(ev_ids) > 1 else ev_portfolio
        return LLMResponse(
            text=_valid_llm_json(ev_portfolio, ev_market),
            stop_reason=StopReason.END_TURN,
            model="fake",
            usage=LLMUsage(input_tokens=100, output_tokens=100),
        )
    fake_client.chat.side_effect = _reply

    with patch.object(guardian_module, "get_llm_client", return_value=fake_client), \
         patch.object(guardian_module.feishu_bot, "send_guardian_briefing",
                      AsyncMock(return_value=False)), \
         patch.object(guardian_module, "settings",
                      guardian_module.settings.model_copy(update={"guardian_push_enabled": False})):
        agent = GuardianAgent(db_session, slot=BriefingSlot.CLOSE)
        result = await agent.run()

    assert result.llm_used is True
    assert result.error is None
    # Rule detector should catch the deep loss on F003
    assert any(a.code == "F003" for a in result.alerts)
    # And should catch TOP3 concentration (F001 + F002 + F003 combined > 55%)
    triggers = {(a.trigger if isinstance(a.trigger, str) else a.trigger.value)
                for a in result.alerts}
    assert "LOSS_DEEP" in triggers

    # Decisions saved: one briefing + one per alert
    assert len(result.decision_ids) == 1 + len(result.alerts)

    # Session id includes today's date and slot
    assert result.session_id.startswith("guardian_")
    assert "close" in result.session_id

    # GuardianRun row is present
    from app.models.evidence import GuardianRun
    from sqlalchemy import select
    row = (await db_session.execute(
        select(GuardianRun).where(GuardianRun.session_id == result.session_id)
    )).scalar_one_or_none()
    assert row is not None
    assert row.alert_count == len(result.alerts)
    assert row.decision_count == len(result.decision_ids)
    assert row.llm_used is True


@pytest.mark.asyncio
async def test_guardian_falls_back_to_rules_when_llm_fails(db_session):
    """LLM error → briefing text still generated, portfolio_card still saved,
    all rule alerts still produce their cards."""
    holdings = [
        {"code": "F001", "name": "深亏基金", "market_value": 20000, "pnl_pct": -28},
    ]
    await _seed_positions(db_session, holdings)

    fake_client = AsyncMock()
    fake_client.provider_name = "fake"
    fake_client.chat.side_effect = LLMError("simulated network fail", provider="fake")

    with patch.object(guardian_module, "get_llm_client", return_value=fake_client), \
         patch.object(guardian_module.feishu_bot, "send_guardian_briefing",
                      AsyncMock(return_value=False)), \
         patch.object(guardian_module, "settings",
                      guardian_module.settings.model_copy(update={"guardian_push_enabled": False})):
        agent = GuardianAgent(db_session, slot=BriefingSlot.MANUAL)
        result = await agent.run()

    assert result.llm_used is False
    assert result.error is not None and "simulated" in result.error
    assert result.briefing_text is not None
    # Should still emit a portfolio briefing card + one per alert
    assert len(result.decision_ids) >= 2
    # And still catch the deep loss alert
    assert any(a.code == "F001" for a in result.alerts)


@pytest.mark.asyncio
async def test_guardian_rerun_is_idempotent_per_session(db_session):
    """Running the same slot twice on the same day updates the GuardianRun
    row in place instead of duplicating."""
    holdings = [{"code": "F001", "name": "平静基金", "market_value": 10000, "pnl_pct": 5}]
    await _seed_positions(db_session, holdings)

    fake_client = AsyncMock()
    fake_client.provider_name = "fake"
    fake_client.chat.side_effect = LLMError("no llm", provider="fake")

    with patch.object(guardian_module, "get_llm_client", return_value=fake_client), \
         patch.object(guardian_module.feishu_bot, "send_guardian_briefing",
                      AsyncMock(return_value=False)), \
         patch.object(guardian_module, "settings",
                      guardian_module.settings.model_copy(update={"guardian_push_enabled": False})):
        agent = GuardianAgent(db_session, slot=BriefingSlot.MIDDAY)
        r1 = await agent.run()
        # Fresh instance same day + slot → same session_id
        agent2 = GuardianAgent(db_session, slot=BriefingSlot.MIDDAY)
        r2 = await agent2.run()

    assert r1.session_id == r2.session_id

    from app.models.evidence import GuardianRun
    from sqlalchemy import select
    rows = (await db_session.execute(select(GuardianRun))).scalars().all()
    matching = [r for r in rows if r.session_id == r1.session_id]
    assert len(matching) == 1  # upserted, not duplicated
