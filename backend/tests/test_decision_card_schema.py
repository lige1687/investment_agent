"""DecisionCard schema — validation, deduplication, evidence collection."""
import pytest
from pydantic import ValidationError

from app.schemas.decision_card import (
    Action,
    ActionVerb,
    Conflict,
    DecisionCard,
    DecisionType,
    Dimension,
    DimensionKey,
    ExecutionPlan,
    PortfolioContext,
    PortfolioRole,
    StopLoss,
    Target,
    TargetKind,
    build_emit_decision_card_schema,
)


def _minimal_card(**overrides) -> DecisionCard:
    base = dict(
        decision_id="dec_test01",
        agent="advisor",
        type=DecisionType.BUY_CANDIDATE,
        target=Target(kind=TargetKind.FUND, code="006503", name="财通集成电路"),
        action=Action(verb=ActionVerb.BUY, confidence=0.72),
    )
    base.update(overrides)
    return DecisionCard(**base)


def test_minimal_card_is_valid():
    card = _minimal_card()
    assert card.decision_id == "dec_test01"
    assert card.agent == "advisor"
    assert card.disclaimer == "仅供参考,不构成投资建议"
    assert card.evidence_refs == []


def test_confidence_range_enforced():
    with pytest.raises(ValidationError):
        Action(verb=ActionVerb.BUY, confidence=1.5)
    with pytest.raises(ValidationError):
        Action(verb=ActionVerb.BUY, confidence=-0.1)


def test_dimension_score_range_enforced():
    with pytest.raises(ValidationError):
        Dimension(key=DimensionKey.TECHNICAL, score=11, signal="x")
    with pytest.raises(ValidationError):
        Dimension(key=DimensionKey.TECHNICAL, score=-1, signal="x")


def test_dimension_signal_cannot_be_empty():
    with pytest.raises(ValidationError):
        Dimension(key=DimensionKey.TECHNICAL, score=5, signal="")


def test_duplicate_dimension_keys_rejected():
    """Each axis appears at most once — protects the radar chart from
    ambiguous rendering."""
    dims = [
        Dimension(key=DimensionKey.TECHNICAL, score=8, signal="up"),
        Dimension(key=DimensionKey.TECHNICAL, score=6, signal="also up"),
    ]
    with pytest.raises(ValidationError):
        _minimal_card(dimensions=dims)


def test_evidence_refs_deduped_preserving_order():
    card = _minimal_card(evidence_refs=["ev_a", "ev_b", "ev_a", "ev_c"])
    assert card.evidence_refs == ["ev_a", "ev_b", "ev_c"]


def test_collect_evidence_refs_unions_top_level_and_dimensions():
    dims = [
        Dimension(key=DimensionKey.TECHNICAL, score=8, signal="up", evidence_ref="ev_d1"),
        Dimension(key=DimensionKey.CAPITAL, score=7, signal="inflow", evidence_ref="ev_d2"),
        Dimension(key=DimensionKey.NEWS, score=8, signal="policy"),  # no ref
    ]
    card = _minimal_card(evidence_refs=["ev_top", "ev_d1"], dimensions=dims)
    all_refs = card.collect_evidence_refs()
    # Order: top-level first, then any dimension refs not already present
    assert all_refs == ["ev_top", "ev_d1", "ev_d2"]


def test_conflict_requires_at_least_two_dimensions():
    with pytest.raises(ValidationError):
        Conflict(between=[DimensionKey.TECHNICAL], note="lonely")


def test_full_card_with_all_optional_fields_round_trips():
    """Serialize → parse → equal."""
    card = _minimal_card(
        headline="半导体 - 中芯国际 强势突破",
        summary="资金进场+政策利好,可小仓试探",
        dimensions=[
            Dimension(key=DimensionKey.TECHNICAL, score=8.2, signal="突破20日线", evidence_ref="ev_01"),
            Dimension(key=DimensionKey.FINANCIAL, score=5.2, signal="PE 45x偏高", evidence_ref="ev_02"),
        ],
        conflicts=[
            Conflict(
                between=[DimensionKey.TECHNICAL, DimensionKey.FINANCIAL],
                note="技术强但估值贵",
            ),
        ],
        portfolio_context=PortfolioContext(
            role=PortfolioRole.STRENGTHEN,
            overlap_with_holdings=["001513 已重仓半导体 12%"],
            warning="追加会让半导体暴露超 20%",
        ),
        execution_plan=ExecutionPlan(
            position_size_pct="3-5%",
            stop_loss=StopLoss(type="trailing", value="-8%"),
        ),
        monitoring=["5日均线跌破立即通知"],
        evidence_refs=["ev_01", "ev_02"],
    )
    dumped = card.model_dump(mode="json")
    parsed = DecisionCard.model_validate(dumped)
    assert parsed.headline == "半导体 - 中芯国际 强势突破"
    assert parsed.portfolio_context.role == "STRENGTHEN"
    assert parsed.execution_plan.stop_loss.value == "-8%"
    assert parsed.conflicts[0].between == ["technical", "financial"]


def test_emit_decision_card_schema_is_object_with_required_keys():
    schema = build_emit_decision_card_schema()
    assert schema["type"] == "object"
    for key in ("type", "target", "action"):
        assert key in schema.get("required", []), f"missing required: {key}"
