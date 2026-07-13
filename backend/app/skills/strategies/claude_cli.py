"""Strategy 3: Claude CLI subprocess.

Slowest and most expensive. Used as fallback for proprietary skills
that require the full Claude Code environment (hithink-* skills).
"""
import asyncio
import json
import logging
import re
from app.skills.base import SkillRequest, SkillResult, SkillStrategy

logger = logging.getLogger(__name__)

CLAUDE_CLI_SKILLS = {
    # Fund-related
    "fund_select",          # → hithink-fund-selector
    "sector_select",        # → hithink-sector-selector
    "etf_screen",           # → 问财选ETF
    "fund_analysis",        # → 基金理财查询
    # Market diagnosis
    "sentiment_analysis",   # → 市场情绪分析 (#120)
    "sector_rotation_analysis",  # → 行业轮动分析 (#119)
    "north_bound_flow",     # → 沪深港通资金流分析 (#108)
    "macro_analysis",       # → 全球宏观分析框架 (#134)
    "sector_monitor",       # → 行业轮动监控 (#187)
    "sentiment_divergence", # → 市场情绪偏离分析 (#164)
}

SKILL_NAME_MAP = {
    "fund_select": "hithink-fund-selector",
    "sector_select": "hithink-sector-selector",
    "sentiment_analysis": "市场情绪分析",
    "sector_rotation_analysis": "行业轮动分析",
    "north_bound_flow": "沪深港通资金流分析",
    "macro_analysis": "全球宏观分析框架",
    "sector_monitor": "行业轮动监控",
    "sentiment_divergence": "市场情绪偏离分析",
}


class ClaudeCLIStrategy(SkillStrategy):
    """Invokes skills via Claude Code CLI subprocess."""

    def can_handle(self, skill_name: str) -> bool:
        return skill_name in CLAUDE_CLI_SKILLS

    async def execute(self, request: SkillRequest) -> SkillResult:
        prompt = self._build_prompt(request)

        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "-p", prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=request.timeout_seconds,
            )

            if proc.returncode != 0:
                error_msg = stderr.decode()[:500]
                logger.error(f"Claude CLI exit {proc.returncode}: {error_msg}")
                return SkillResult(
                    success=False,
                    error=f"CLI error (exit {proc.returncode}): {error_msg}",
                    strategy_used="claude_cli",
                )

            output = stdout.decode()
            data = self._parse_output(output)

            return SkillResult(success=True, data=data, strategy_used="claude_cli")

        except asyncio.TimeoutError:
            return SkillResult(
                success=False,
                error=f"CLI timed out after {request.timeout_seconds}s",
                strategy_used="claude_cli",
            )
        except FileNotFoundError:
            return SkillResult(
                success=False,
                error="Claude CLI not found. Please install Claude Code.",
                strategy_used="claude_cli",
            )
        except Exception as e:
            logger.error(f"Claude CLI unexpected error: {e}")
            return SkillResult(success=False, error=str(e), strategy_used="claude_cli")

    def _build_prompt(self, request: SkillRequest) -> str:
        """Build a structured prompt for Claude CLI."""
        skill_display = SKILL_NAME_MAP.get(request.skill_name, request.skill_name)
        params_json = json.dumps(request.params, ensure_ascii=False)

        return (
            f"Use the {skill_display} skill to query with these parameters:\n"
            f"{params_json}\n\n"
            f"IMPORTANT: Return ONLY a valid JSON array. No markdown, no explanation, "
            f"no code fences. Just the raw JSON."
        )

    def _parse_output(self, output: str) -> list | dict:
        """Extract JSON from Claude CLI output. Handles various formats."""
        # Try direct parse first
        output = output.strip()
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            pass

        # Try to extract from code fences
        fence_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', output)
        if fence_match:
            try:
                return json.loads(fence_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Try to find JSON array or object in text
        json_match = re.search(r'(\[.*\]|\{.*\})', output, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Fallback - return as raw text
        logger.warning(f"Could not parse JSON from CLI output: {output[:200]}...")
        return {"raw_output": output}
