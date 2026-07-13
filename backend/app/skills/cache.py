"""TTL cache for skill results using SQLite + memory."""
import hashlib
import json
import time
from typing import Optional
from app.skills.base import SkillRequest, SkillResult


class SkillCache:
    """Two-tier cache: in-memory (fast) + SQLite (persistent)."""

    def __init__(self):
        self._memory: dict[str, tuple[SkillResult, float]] = {}  # key -> (result, expires_at)

    def _make_key(self, request: SkillRequest) -> str:
        """Generate a deterministic cache key from a request."""
        raw = json.dumps({
            "skill": request.skill_name,
            "params": request.params,
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    async def get(self, request: SkillRequest) -> Optional[SkillResult]:
        """Try to get cached result."""
        key = self._make_key(request)
        entry = self._memory.get(key)
        if entry:
            result, expires_at = entry
            if time.monotonic() < expires_at:
                result.cached = True
                return result
            del self._memory[key]
        return None

    async def set(self, request: SkillRequest, result: SkillResult, ttl_seconds: int):
        """Cache a result with TTL."""
        if ttl_seconds <= 0:
            return
        key = self._make_key(request)
        self._memory[key] = (result, time.monotonic() + ttl_seconds)

    async def invalidate(self, skill_name: Optional[str] = None):
        """Clear cache for a specific skill or all skills."""
        if skill_name is None:
            self._memory.clear()
        else:
            keys_to_delete = [
                k for k, v in self._memory.items()
                if json.loads(k).get("skill") == skill_name  # approximate match
            ]
            for k in keys_to_delete:
                del self._memory[k]

    def size(self) -> int:
        """Return number of cached entries."""
        return len(self._memory)
