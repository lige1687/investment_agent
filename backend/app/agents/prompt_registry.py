"""Versioned prompt template loader for investment agents."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: str
    content: str


class PromptRegistry:
    def __init__(self, prompt_dir: Path = PROMPT_DIR):
        self._prompt_dir = prompt_dir

    def get(self, name: str) -> PromptTemplate:
        path = self._prompt_dir / f"{name}.md"
        if not path.exists():
            raise KeyError(f"Prompt template not found: {name}")
        content = path.read_text(encoding="utf-8")
        version = "unversioned"
        for line in content.splitlines():
            if line.startswith("version:"):
                version = line.split(":", 1)[1].strip()
                break
        return PromptTemplate(name=name, version=version, content=content)
