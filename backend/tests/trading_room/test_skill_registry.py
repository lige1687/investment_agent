"""Whitelist and version-integrity tests for professional trading skills."""

from pathlib import Path

import pytest


def _write_skill(root: Path, name: str, body: str, reference: tuple[str, str] | None = None):
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")
    if reference:
        relative, content = reference
        ref_path = skill_dir / relative
        ref_path.parent.mkdir(parents=True)
        ref_path.write_text(content, encoding="utf-8")


def test_registry_loads_only_declared_files_and_produces_stable_hash(tmp_path):
    from app.trading_room.skill_registry import TradingSkillRegistry

    trading = tmp_path / "trading"
    market = tmp_path / "market"
    _write_skill(
        trading,
        "batch-trading-router",
        "# Router\r\nProtect account.\r\n",
        ("references/router-priority.md", "risk > buy\n"),
    )

    first = TradingSkillRegistry(trading_root=trading, market_root=market)
    second = TradingSkillRegistry(trading_root=trading, market_root=market)
    bundle = first.load("batch-trading-router")

    assert bundle.files == ("SKILL.md", "references/router-priority.md")
    assert "Protect account." in bundle.content
    assert "risk > buy" in bundle.content
    assert bundle.sha256 == second.load("batch-trading-router").sha256
    assert len(bundle.sha256) == 64


def test_registry_rejects_non_whitelisted_and_traversal_names(tmp_path):
    from app.trading_room.skill_registry import SkillUnavailableError, TradingSkillRegistry

    registry = TradingSkillRegistry(
        trading_root=tmp_path / "trading",
        market_root=tmp_path / "market",
    )

    with pytest.raises(SkillUnavailableError):
        registry.load("batch-trading-batch-planner")
    with pytest.raises(SkillUnavailableError):
        registry.load("../escape")


def test_registry_rejects_missing_or_symlinked_skill_files(tmp_path):
    from app.trading_room.skill_registry import SkillUnavailableError, TradingSkillRegistry

    trading = tmp_path / "trading"
    market = tmp_path / "market"
    registry = TradingSkillRegistry(trading_root=trading, market_root=market)
    with pytest.raises(SkillUnavailableError):
        registry.load("batch-trading-router")

    outside = tmp_path / "outside.md"
    outside.write_text("untrusted", encoding="utf-8")
    skill_dir = trading / "batch-trading-router"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").symlink_to(outside)
    with pytest.raises(SkillUnavailableError):
        registry.load("batch-trading-router")


def test_registry_detects_skill_changes_after_session_snapshot(tmp_path):
    from app.trading_room.skill_registry import SkillChangedError, TradingSkillRegistry

    trading = tmp_path / "trading"
    market = tmp_path / "market"
    _write_skill(
        trading,
        "batch-trading-router",
        "# Router\nProtect account.\n",
        ("references/router-priority.md", "risk > buy\n"),
    )
    registry = TradingSkillRegistry(trading_root=trading, market_root=market)
    registry.load("batch-trading-router")

    (trading / "batch-trading-router" / "SKILL.md").write_text(
        "# Router\nChanged while session active.\n",
        encoding="utf-8",
    )

    with pytest.raises(SkillChangedError):
        registry.load("batch-trading-router")


def test_new_hithink_skills_are_loadable(tmp_path):
    from app.config import settings
    from app.trading_room.skill_registry import TradingSkillRegistry

    registry = TradingSkillRegistry(
        trading_root=settings.trading_skill_root,
        market_root=settings.market_skill_root,
    )
    for name in ("hithink-sector-selector", "hithink-fund-selector", "sector-rotation-analysis"):
        bundle = registry.load(name)
        assert bundle.name == name
        assert bundle.sha256
        assert bundle.content.strip()

