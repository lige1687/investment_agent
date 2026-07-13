"""Strategy 2: Claude API direct via Anthropic SDK.

Medium cost. Used for pattern recognition, technical analysis, and signal generation.
"""
import json
import logging
from app.config import settings
from app.skills.base import SkillRequest, SkillResult, SkillStrategy

logger = logging.getLogger(__name__)

CLAUDE_API_SKILLS = {
    "pattern_recognition",
    "technical_analysis",
    "signal_generation",
    "sector_rotation_analysis",
    "fund_analysis",
}


class ClaudeAPIStrategy(SkillStrategy):
    """Invokes Claude API directly with structured output tools."""

    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None and settings.anthropic_api_key:
            try:
                import anthropic
                self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            except ImportError:
                logger.warning("anthropic package not installed")
        return self._client

    def can_handle(self, skill_name: str) -> bool:
        if not settings.anthropic_api_key:
            return False
        return skill_name in CLAUDE_API_SKILLS

    async def execute(self, request: SkillRequest) -> SkillResult:
        client = self._get_client()
        if client is None:
            return SkillResult(
                success=False,
                error="Anthropic API key not configured",
                strategy_used="claude_api",
            )

        prompt = request.params.get("prompt", "")
        kline_data = request.params.get("kline_data")
        indicators = request.params.get("indicators")

        messages = [{"role": "user", "content": self._build_content(prompt, kline_data, indicators)}]

        try:
            response = await client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                temperature=0.1,  # Low temp for analytical tasks
                messages=messages,
            )

            # Extract text response
            text = response.content[0].text if response.content else ""
            try:
                # Try to parse as JSON
                data = json.loads(text)
            except json.JSONDecodeError:
                data = {"analysis": text}

            return SkillResult(success=True, data=data, strategy_used="claude_api")

        except Exception as e:
            logger.error(f"Claude API error: {e}")
            return SkillResult(success=False, error=str(e), strategy_used="claude_api")

    def _build_content(self, prompt: str, kline_data=None, indicators=None) -> str:
        """Build the message content with context."""
        parts = [prompt]
        if kline_data:
            parts.append(f"\nK-line data (last {len(kline_data)} bars):")
            parts.append(json.dumps(kline_data[-20:], ensure_ascii=False, default=str))
        if indicators:
            parts.append(f"\nTechnical indicators:")
            parts.append(json.dumps(indicators, ensure_ascii=False, default=str))
        return "\n".join(parts)
