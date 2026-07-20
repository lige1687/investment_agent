"""Read-only whitelist and version registry for trading-room skills."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


class SkillUnavailableError(RuntimeError):
    """Raised when an approved skill cannot be loaded safely."""


class SkillChangedError(SkillUnavailableError):
    """Raised when skill content changes after a registry snapshot."""


@dataclass(frozen=True)
class SkillDefinition:
    root: str
    directory: str
    files: tuple[str, ...]


@dataclass(frozen=True)
class SkillBundle:
    name: str
    files: tuple[str, ...]
    content: str
    sha256: str


APPROVED_SKILLS: dict[str, SkillDefinition] = {
    "batch-trading-router": SkillDefinition(
        "trading", "batch-trading-router", ("SKILL.md", "references/router-priority.md")
    ),
    "batch-trading-market-regime": SkillDefinition(
        "trading", "batch-trading-market-regime", ("SKILL.md", "references/market-regime-rules.md")
    ),
    "batch-trading-position-risk": SkillDefinition(
        "trading", "batch-trading-position-risk", ("SKILL.md", "references/position-risk-rules.md")
    ),
    "batch-trading-buy-signal": SkillDefinition(
        "trading", "batch-trading-buy-signal", ("SKILL.md", "references/buy-signal-rules.md")
    ),
    "batch-trading-stop-loss": SkillDefinition(
        "trading", "batch-trading-stop-loss", ("SKILL.md", "references/stop-loss-rules.md")
    ),
    "batch-trading-take-profit": SkillDefinition(
        "trading", "batch-trading-take-profit", ("SKILL.md", "references/take-profit-rules.md")
    ),
    "hithink-fund-query": SkillDefinition(
        "market", "hithink-fund-query", ("SKILL.md",)
    ),
    "announcement-search": SkillDefinition(
        "market", "announcement-search", ("SKILL.md", "references/api.md")
    ),
    "fund-analysis": SkillDefinition(
        "market", "基金分析与筛选/fund-analysis", ("SKILL.md",)
    ),
    "hithink-sector-selector": SkillDefinition(
        "market", "hithink-sector-selector", ("SKILL.md",)
    ),
    "hithink-fund-selector": SkillDefinition(
        "market", "hithink-fund-selector", ("SKILL.md",)
    ),
    "sector-rotation-analysis": SkillDefinition(
        "market", "行业轮动分析/sector-rotation", ("SKILL.md",)
    ),
}


def _normalize_text(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.replace("\r\n", "\n").split("\n")).rstrip() + "\n"


class TradingSkillRegistry:
    """Loads full approved skill instructions and detects mid-session changes."""

    def __init__(self, *, trading_root: str | Path, market_root: str | Path):
        self._roots = {
            "trading": Path(trading_root).expanduser().resolve(),
            "market": Path(market_root).expanduser().resolve(),
        }
        self._snapshots: dict[str, str] = {}

    def load(self, name: str) -> SkillBundle:
        definition = APPROVED_SKILLS.get(name)
        if definition is None:
            raise SkillUnavailableError(f"skill is not approved: {name}")

        root = self._roots[definition.root]
        skill_dir = root / definition.directory
        parts: list[str] = []
        for relative in definition.files:
            file_path = skill_dir / relative
            self._validate_path(root, file_path)
            try:
                text = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise SkillUnavailableError(f"cannot read approved skill file: {name}/{relative}") from exc
            parts.append(f"--- {relative} ---\n{_normalize_text(text)}")

        content = "\n".join(parts)
        digest = sha256(content.encode("utf-8")).hexdigest()
        previous = self._snapshots.setdefault(name, digest)
        if previous != digest:
            raise SkillChangedError(f"skill changed after registry snapshot: {name}")
        return SkillBundle(
            name=name,
            files=definition.files,
            content=content,
            sha256=digest,
        )

    @staticmethod
    def _validate_path(root: Path, file_path: Path) -> None:
        try:
            resolved = file_path.resolve(strict=True)
            resolved.relative_to(root)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise SkillUnavailableError("approved skill path is missing or escapes its root") from exc

        current = file_path
        while current != root:
            if current.is_symlink():
                raise SkillUnavailableError("symlinked skill paths are not allowed")
            current = current.parent

