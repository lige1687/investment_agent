"""AI Investment Agent — Q&A with portfolio context + THS skills.

Runs a provider-agnostic tool-use loop and emits *structured decision cards*
(not free-form prose) whenever the model has a real recommendation.

Two special behaviors on top of the plain tool loop:

  1. Every tool result is snapshotted into the Evidence Bus and returned to
     the model with an `[evidence_id: ev_xxx]` header. The model then cites
     those ids in the `dimensions[*].evidence_ref` field of its decision
     card, so the UI can click through to raw evidence.

  2. A special tool `emit_decision_card` is intercepted rather than executed:
     its arguments are validated as a DecisionCard, persisted, and the
     model is told success. The final chat response carries the card.
"""
import json
import logging
import uuid
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.llm import (
    LLMAuthError,
    LLMError,
    Message,
    ToolDef,
    ToolResult,
    get_llm_client,
)
from app.models.position import Position
from app.models.fund import FundProfile
from app.schemas.decision_card import DecisionCard, build_emit_decision_card_schema
from app.services.agent_context_service import AgentContextService
from app.services.decision_store import DecisionCardStore
from app.services.evidence_bus import EvidenceBus
from app.skills.bridge import bridge

logger = logging.getLogger(__name__)


# ── Tool catalog ──────────────────────────────────────────────────────────
# Data-fetch tools. `default_ttl` is the evidence TTL suggestion — cheap
# real-time data expires fast, screened lists live longer.
AGENT_TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_portfolio_summary",
        "description": "获取用户当前持仓概况:总市值、总盈亏、各基金持仓明细。用户询问持仓相关问题时先调用此工具。",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "default_ttl": 60,
    },
    {
        "name": "get_fund_detail",
        "description": "查询单只基金的详细信息:净值、业绩、风险指标、基金经理等。",
        "input_schema": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "基金代码,如022184"}},
            "required": ["code"],
        },
        "default_ttl": 300,
    },
    {
        "name": "search_funds",
        "description": "筛选公募基金。可按类型、业绩、风险等级、基金经理、基金公司等条件筛选。调用同花顺 hithink-fund-selector 技能。",
        "input_schema": {
            "type": "object",
            "properties": {
                "fund_type": {"type": "string", "description": "基金类型:股票型/混合型/债券型/指数型/QDII"},
                "min_return_1y": {"type": "number", "description": "近1年最低收益率(%)"},
                "max_risk": {"type": "string", "description": "最高风险等级:R1-R5"},
                "keyword": {"type": "string", "description": "搜索关键词:板块名/经理名/公司名"},
            },
        },
        "default_ttl": 3600,
    },
    {
        "name": "search_sectors",
        "description": "查询板块/行业表现。返回板块涨跌幅、资金流向、估值等。调用同花顺 hithink-sector-selector。",
        "input_schema": {
            "type": "object",
            "properties": {
                "sector_name": {"type": "string", "description": "板块名称,如半导体、新能源、医药"},
                "sort_by": {"type": "string", "description": "排序方式:change_pct/capital_flow/volume"},
            },
        },
        "default_ttl": 900,
    },
    {
        "name": "compare_funds",
        "description": "对比多只基金的业绩、风险、费用等指标。",
        "input_schema": {
            "type": "object",
            "properties": {
                "codes": {"type": "array", "items": {"type": "string"}, "description": "基金代码列表,如 ['022184','001513']"},
            },
            "required": ["codes"],
        },
        "default_ttl": 300,
    },
    {
        "name": "get_market_overview",
        "description": "获取当前市场概况:全球指数、市场情绪、资金流向、板块轮动。",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "default_ttl": 60,
    },
    {
        "name": "analyze_portfolio_risk",
        "description": "分析用户持仓的风险状况:行业集中度、风险等级分布、最大回撤等。",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "default_ttl": 300,
    },
    {
        "name": "lookup_fund_names",
        "description": (
            "根据一批基金代码,返回 {code: 中文名} 映射。"
            "在决策卡/文本里提到基金时,如果你不知道代码对应的中文名,先调这个查一下,"
            "再按「中文名(代码)」格式输出。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "基金代码列表,如 ['001513','022184']",
                },
            },
            "required": ["codes"],
        },
        "default_ttl": 86400,
    },
]

# Ttl lookup for the exec loop.
_TOOL_TTL: dict[str, int] = {t["name"]: int(t.get("default_ttl", 300)) for t in AGENT_TOOLS}

# Special tool: intercepted, not executed. Its arguments ARE the decision card.
EMIT_DECISION_CARD_TOOL_NAME = "emit_decision_card"
EMIT_DECISION_CARD_TOOL: dict[str, Any] = {
    "name": EMIT_DECISION_CARD_TOOL_NAME,
    "description": (
        "当你对用户问题得出一个具体的买入/卖出/持有/关注建议时,通过此工具提交一张结构化 "
        "决策卡。前端将其渲染成可交互卡片。使用规则:\n"
        " - 你必须先调用数据类工具(如 get_portfolio_summary、search_funds)得到证据,"
        "再提交决策卡;不要凭空判断。\n"
        " - 决策卡里的 dimensions[*].evidence_ref 请引用你之前工具结果里的 [evidence_id: ev_xxx]。\n"
        " - 6 个维度只写你有依据的那几个,不要凑数。\n"
        " - 冲突维度必须在 conflicts 字段显式列出,不要平均分数。\n"
        " - 一次对话最多提交一张决策卡;如果问题不是决策类,直接回文本即可,不要调用此工具。\n"
        " - 提交完决策卡后,再用简短文本对用户说一句总结(≤3 句)。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": ["BUY_CANDIDATE", "SELL_ALERT", "REBALANCE", "WATCH", "NONE"],
                "description": "决策类型",
            },
            "target": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["fund", "stock", "etf", "sector", "index", "portfolio"],
                    },
                    "code": {"type": "string", "description": "标的代码(可选)"},
                    "name": {"type": "string", "description": "标的中文名"},
                },
                "required": ["kind", "name"],
            },
            "action": {
                "type": "object",
                "properties": {
                    "verb": {
                        "type": "string",
                        "enum": ["BUY", "ADD", "HOLD", "REDUCE", "SELL", "WATCH", "AVOID"],
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "urgency": {
                        "type": "string",
                        "enum": ["LOW", "MEDIUM", "HIGH"],
                    },
                },
                "required": ["verb", "confidence"],
            },
            "headline": {"type": "string", "description": "一句话标题"},
            "summary": {"type": "string", "description": "2-4 句核心理由"},
            "dimensions": {
                "type": "array",
                "description": "6 维评估,只填有依据的",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "enum": [
                                "technical", "capital", "macro",
                                "news", "financial", "consensus",
                            ],
                        },
                        "score": {"type": "number", "minimum": 0, "maximum": 10},
                        "signal": {"type": "string"},
                        "evidence_ref": {
                            "type": "string",
                            "description": "引用之前工具结果里的 evidence_id,如 ev_abc12",
                        },
                    },
                    "required": ["key", "score", "signal"],
                },
            },
            "conflicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "between": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 2,
                        },
                        "note": {"type": "string"},
                    },
                    "required": ["between", "note"],
                },
            },
            "portfolio_context": {
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "enum": ["COMPLEMENT", "STRENGTHEN", "DUPLICATE", "NEW"],
                    },
                    "overlap_with_holdings": {
                        "type": "array", "items": {"type": "string"},
                    },
                    "warning": {"type": "string"},
                },
            },
            "execution_plan": {
                "type": "object",
                "properties": {
                    "position_size_pct": {"type": "string"},
                    "entry": {
                        "type": "object",
                        "properties": {
                            "style": {"type": "string"},
                            "batches": {"type": "integer"},
                            "trigger": {"type": "string"},
                        },
                    },
                    "stop_loss": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "value": {"type": "string"},
                        },
                    },
                    "take_profit": {
                        "type": "object",
                        "properties": {
                            "levels": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "at": {"type": "string"},
                                        "action": {"type": "string"},
                                    },
                                },
                            },
                        },
                    },
                },
            },
            "monitoring": {"type": "array", "items": {"type": "string"}},
            "evidence_refs": {
                "type": "array", "items": {"type": "string"},
                "description": "所有引用的 evidence_id 的合集",
            },
        },
        "required": ["type", "target", "action"],
    },
}


SYSTEM_PROMPT = """你是基金投资 AI 助手,帮用户分析持仓、推荐基金、解读市场。

## 工具使用原则
- 只调用回答用户问题真正需要的工具;不要一次性把所有工具都拉一遍。
- 用户询问"我的持仓/风险/该不该卖"时,先调 get_portfolio_summary;涉及集中度/回撤时叠加 analyze_portfolio_risk。
- 用户问"推荐/筛选基金"时,调用 search_funds;涉及板块行情时叠加 search_sectors。
- 用户问"市场怎么样/今天热点"时,调用 get_market_overview。
- 涉及具体基金代码时,调用 get_fund_detail;不知道代码对应中文名时调 lookup_fund_names。
- 有对比意图时,调用 compare_funds。

## 硬性规范

### 1. 基金和板块必须写中文名
所有面向用户的输出(summary、headline、signal、conflicts.note、监控条件),
出现基金或板块代码时,**必须**用「中文名(代码)」格式,例如:
  ✅ 易方达信息产业混合A(001513)、富国全球科技互联网(QDII)C(022184)、半导体板块
  ❌ 001513、022184、BK8001
如果你不知道某个代码对应的中文名,调用 lookup_fund_names 查一下,不要直接写代码。
target.code 字段本身还是填代码;这一条只管人类可读的文本字段。

### 2. 数据不可信时的处理
每个工具返回的数据可能有一个 `data_source` 字段:
- `live` = 真实数据,可作为方向性依据
- `simulated` = 模拟数据(尚未接通同花顺 skill),**绝不能**据此得出方向性结论(涨跌、资金进出、板块领涨等)
如果关键工具返回 `data_source: simulated`:
  - 决策卡的 summary **首句必须**说明「当前市场数据为模拟数据,以下结论仅基于持仓自身」
  - action.confidence **上限 0.5**
  - 不要写 technical / capital / macro / news / consensus 相关的维度评分(这些依赖真实市场数据)
  - financial 维度基于持仓自身盈亏、集中度,可以照常写

### 3. 6 维评估:有数据才写,不要凑数
`dimensions[]` 列表里,**只写你真的有证据支持的维度**。缺少数据就省略。
例如:如果没有工具查新闻,就不要写 `news` 维度;如果没查过机构评级,就不要写 `consensus`。
如果因为数据缺失少于 3 维,summary 里明确列出"缺失维度:XX、XX(该维度暂无数据源)"。

### 4. 冲突和上下文
- 有维度分歧就在 `conflicts` 里列出,不要平均分数
- 涉及具体标的时填 target.code + target.name
- portfolio_context.role 要点明:补齐 / 加强 / 重叠 / 全新

## 证据总线 (Evidence Bus)
每次工具返回的数据前面都有 `[evidence_id: ev_xxx]` 标签。这是这份证据的引用 id。
当你在决策卡里描述某个信号,必须在 dimensions[*].evidence_ref 字段填入对应的 ev_id,
这样前端可以点开看原始数据。

## 决策卡 (emit_decision_card)
如果用户问题是决策类(买不买/卖不卖/调不调仓/推不推荐),收集完证据后调用 emit_decision_card。
如果用户问题只是查询或闲聊,不要调用 emit_decision_card,直接文本回复即可。

## 回答风格
- 提交决策卡后,再用 ≤3 句话对用户口头总结即可。
- 未提交决策卡时(纯查询/闲聊),文本控制在 250-600 字,结论优先。
- 数据不足就直说缺哪一类,仍要基于已有数据给判断。
- 中文回复。涉及操作建议时结尾加一句"仅供参考,不构成投资建议"。
"""

MAX_TOOL_TURNS = 6
MAX_TOOL_RESULT_CHARS = 8000


def _build_tool_defs() -> list[ToolDef]:
    defs = [
        ToolDef(name=t["name"], description=t["description"], input_schema=t["input_schema"])
        for t in AGENT_TOOLS
    ]
    defs.append(ToolDef(
        name=EMIT_DECISION_CARD_TOOL["name"],
        description=EMIT_DECISION_CARD_TOOL["description"],
        input_schema=EMIT_DECISION_CARD_TOOL["input_schema"],
    ))
    return defs


def _truncate(text: str, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


def _new_session_id() -> str:
    return f"sess_{uuid.uuid4().hex[:16]}"


def _new_decision_id() -> str:
    return f"dec_{uuid.uuid4().hex[:12]}"


class InvestmentAgent:
    """AI agent that answers investment questions via a real tool-use loop."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        session_id: Optional[str] = None,
        agent_role: str = "advisor",
    ):
        self._db = db
        self.session_id = session_id or _new_session_id()
        self.agent_role = agent_role

    # ── Tool dispatch ──

    async def _execute_tool(self, name: str, params: dict[str, Any]) -> str:
        try:
            if name == "get_portfolio_summary":
                return await self._tool_portfolio_summary()
            elif name == "get_fund_detail":
                return await self._tool_fund_detail(params.get("code", ""))
            elif name == "search_funds":
                return await self._tool_search_funds(params)
            elif name == "search_sectors":
                return await self._tool_search_sectors(params)
            elif name == "compare_funds":
                return await self._tool_compare_funds(params.get("codes", []))
            elif name == "get_market_overview":
                return await self._tool_market_overview()
            elif name == "analyze_portfolio_risk":
                return await self._tool_analyze_risk()
            elif name == "lookup_fund_names":
                return await self._tool_lookup_fund_names(params.get("codes") or [])
            else:
                return json.dumps({"error": f"Unknown tool: {name}"})
        except Exception as e:
            logger.exception("Tool %s failed", name)
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ── Tool implementations ──

    async def _tool_portfolio_summary(self) -> str:
        stmt = select(Position).where(Position.source == "yangjibao")
        result = await self._db.execute(stmt)
        positions = result.scalars().all()

        if not positions:
            return json.dumps({"message": "暂无持仓数据,请先在设置页同步养基宝持仓"}, ensure_ascii=False)

        codes = [p.symbol for p in positions]
        name_map: dict[str, str] = {}
        if codes:
            stmt2 = select(FundProfile.code, FundProfile.name).where(FundProfile.code.in_(codes))
            result2 = await self._db.execute(stmt2)
            for code, name in result2.all():
                name_map[code] = name

        total_value = sum(p.market_value or 0 for p in positions)
        total_cost = sum(p.cost_basis or (p.shares * p.avg_cost) for p in positions)
        total_pnl = total_value - total_cost

        holdings = []
        for p in positions:
            name = name_map.get(p.symbol, p.symbol)
            holdings.append({
                "code": p.symbol,
                "name": name,
                "type": p.position_type,
                "shares": round(p.shares, 2),
                "avg_cost": round(p.avg_cost, 4),
                "current_price": round(p.current_price, 4) if p.current_price else None,
                "market_value": round(p.market_value, 2) if p.market_value else None,
                "pnl": round(p.unrealized_pnl, 2) if p.unrealized_pnl else None,
                "pnl_pct": round(p.unrealized_pnl_pct, 2) if p.unrealized_pnl_pct else None,
                "allocation_pct": (
                    round(p.market_value / total_value * 100, 1)
                    if total_value > 0 and p.market_value else 0
                ),
            })

        return json.dumps({
            "total_value": round(total_value, 2),
            "total_cost": round(total_cost, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl / total_cost * 100, 2) if total_cost > 0 else 0,
            "position_count": len(holdings),
            "holdings": sorted(holdings, key=lambda x: x["market_value"] or 0, reverse=True),
        }, ensure_ascii=False)

    async def _tool_fund_detail(self, code: str) -> str:
        stmt = select(Position).where(Position.symbol == code)
        result = await self._db.execute(stmt)
        pos = result.scalar_one_or_none()

        stmt2 = select(FundProfile).where(FundProfile.code == code)
        result2 = await self._db.execute(stmt2)
        profile = result2.scalar_one_or_none()

        data: dict[str, Any] = {"code": code, "in_portfolio": pos is not None}
        if pos:
            data["holding"] = {
                "shares": pos.shares,
                "avg_cost": pos.avg_cost,
                "market_value": pos.market_value,
                "pnl_pct": pos.unrealized_pnl_pct,
            }
        if profile:
            data.update({
                "name": profile.name,
                "type": profile.fund_type,
                "nav": profile.nav,
                "risk_level": profile.risk_level,
                "manager": profile.manager_name,
                "company": profile.fund_company,
                "sharpe": profile.sharpe_ratio,
                "return_1y": profile.performance_1y,
                "max_drawdown": profile.max_drawdown,
            })
        return json.dumps(data, ensure_ascii=False)

    async def _tool_search_funds(self, params: dict) -> str:
        result = await bridge.invoke_simple("fund_select", params=params, cache_ttl=3600)
        if result.success:
            return json.dumps(result.data, ensure_ascii=False)
        return json.dumps({
            "message": f"基金筛选功能需要同花顺 Skill 支持。当前查询条件:{params}",
            "note": "SkillBridge returned no data. THS API may need configuration.",
        }, ensure_ascii=False)

    async def _tool_search_sectors(self, params: dict) -> str:
        result = await bridge.invoke_simple("sector_select", params=params, cache_ttl=3600)
        if result.success:
            payload = result.data if isinstance(result.data, dict) else {"items": result.data}
            payload.setdefault("data_source", "live")
            return json.dumps(payload, ensure_ascii=False)

        from app.services.market_data_provider import MarketDataProvider
        provider = MarketDataProvider()
        sectors = provider.get_heatmap_sectors()
        name = params.get("sector_name", "").lower()
        if name:
            sectors = [s for s in sectors if name in s.get("name", "").lower()]
        return json.dumps({
            "data_source": "simulated",
            "reliability_note": (
                "同花顺板块数据 skill 未接通;当前为随机模拟数据,"
                "禁止基于此得出'涨跌方向''资金流向''板块领涨'类结论。"
            ),
            "items": sectors[:10],
        }, ensure_ascii=False)

    async def _tool_compare_funds(self, codes: list[str]) -> str:
        results = []
        for code in codes:
            stmt = select(Position).where(Position.symbol == code)
            result = await self._db.execute(stmt)
            pos = result.scalar_one_or_none()

            stmt2 = select(FundProfile).where(FundProfile.code == code)
            result2 = await self._db.execute(stmt2)
            profile = result2.scalar_one_or_none()

            item: dict[str, Any] = {"code": code, "name": profile.name if profile else code}
            if pos:
                item["pnl_pct"] = pos.unrealized_pnl_pct
                item["market_value"] = pos.market_value
            if profile:
                item["return_1y"] = profile.performance_1y
                item["sharpe"] = profile.sharpe_ratio
                item["max_drawdown"] = profile.max_drawdown
                item["risk_level"] = profile.risk_level
            results.append(item)
        return json.dumps(results, ensure_ascii=False)

    async def _tool_market_overview(self) -> str:
        from app.services.market_data_provider import MarketDataProvider
        provider = MarketDataProvider()
        indices = provider.get_global_indices()[:6]
        sentiment = provider.get_sentiment()
        flow_data = provider.get_capital_flow()
        inflow = flow_data.get("inflow", flow_data.get("top_inflow", []))
        rotation = provider.get_sector_rotation()[:5]
        # MarketDataProvider produces deterministic per-day random data — it
        # does NOT reflect the real market. Flag this so the LLM refuses to
        # cite it as evidence for a technical/capital call.
        data_source = "simulated"
        reliability_note = (
            "行情/情绪/资金流为随机模拟数据(尚未接同花顺 skill),"
            "禁止基于此得出方向性结论;涉及此类维度时应在决策卡中省略,"
            "或明确标注为'数据缺失'。"
        )

        return json.dumps({
            "data_source": data_source,
            "reliability_note": reliability_note,
            "indices": indices,
            "sentiment": sentiment,
            "top_inflow_sectors": inflow[:3],
            "leading_sectors": [
                {"name": r["sector_name"], "trend": r["trend"]}
                for r in rotation if r["trend"] == "leading"
            ],
        }, ensure_ascii=False)

    async def _tool_lookup_fund_names(self, codes: list[str]) -> str:
        """Fund code → Chinese name lookup. Combines FundProfile + user's
        own Position table (养基宝 sometimes gives us the name on positions
        that isn't yet in fund_profiles)."""
        codes = [str(c).strip() for c in codes if str(c).strip()]
        if not codes:
            return json.dumps({"data_source": "live", "names": {}}, ensure_ascii=False)

        name_map: dict[str, str] = {}

        # First pass: FundProfile
        stmt = select(FundProfile.code, FundProfile.name).where(
            FundProfile.code.in_(codes)
        )
        for code, name in (await self._db.execute(stmt)).all():
            if name:
                name_map[code] = name

        # Second pass: positions may carry a name the profile table lacks
        missing = [c for c in codes if c not in name_map]
        if missing:
            stmt2 = select(Position).where(Position.symbol.in_(missing))
            for pos in (await self._db.execute(stmt2)).scalars().all():
                notes = (pos.notes or "").strip()
                if notes and pos.symbol not in name_map:
                    name_map[pos.symbol] = notes

        # Anything we still can't resolve — mark explicitly so the LLM knows
        # to say "代码 XXX(名称未知)" instead of pretending it knows.
        for c in codes:
            if c not in name_map:
                name_map[c] = None  # type: ignore[assignment]

        return json.dumps({
            "data_source": "live",
            "names": name_map,
            "note": (
                "值为 null 的代码表示本地库暂无中文名,你必须写「代码 XXX(名称未知)」而非直接写代码。"
            ),
        }, ensure_ascii=False)

    async def _tool_analyze_risk(self) -> str:
        stmt = select(Position).where(Position.source == "yangjibao")
        result = await self._db.execute(stmt)
        positions = result.scalars().all()

        if not positions:
            return json.dumps({"message": "无持仓数据"})

        total_value = sum(p.market_value or 0 for p in positions)
        allocations = [(p.symbol, (p.market_value or 0) / total_value * 100) for p in positions]
        allocations.sort(key=lambda x: x[1], reverse=True)

        top3_conc = sum(a[1] for a in allocations[:3])
        top5_conc = sum(a[1] for a in allocations[:5])

        risk_level = "中等"
        if top3_conc > 60:
            risk_level = "偏高(前3大持仓占比超60%)"
        elif top5_conc < 40:
            risk_level = "较低(持仓较分散)"

        return json.dumps({
            "position_count": len(positions),
            "total_value": round(total_value, 2),
            "top3_concentration": round(top3_conc, 1),
            "top5_concentration": round(top5_conc, 1),
            "risk_level": risk_level,
            "top_holdings": [
                {"code": a[0], "allocation_pct": round(a[1], 1)} for a in allocations[:5]
            ],
        }, ensure_ascii=False)

    # ── Decision card interception ──

    def _try_build_decision_card(self, args: dict[str, Any]) -> tuple[Optional[DecisionCard], Optional[str]]:
        """Validate the emit_decision_card tool arguments.

        Returns (card, None) on success, (None, error_msg) on failure.
        The model is expected to accept our fixes for optional fields:
        we supply decision_id, session_id, and agent if missing.
        """
        payload = dict(args or {})
        payload.setdefault("decision_id", _new_decision_id())
        payload.setdefault("agent", self.agent_role)
        payload["session_id"] = self.session_id

        try:
            card = DecisionCard.model_validate(payload)
        except Exception as e:
            return None, f"decision card validation failed: {e}"
        return card, None

    # ── Chat entry point ──

    async def chat(
        self,
        message: str,
        history: Optional[list[dict]] = None,
    ) -> dict:
        """Answer a user question. Returns a dict with:
          - answer:         final assistant text
          - decision_card:  the emitted DecisionCard, or None
          - tool_calls:     trace of tool invocations (name/args/preview)
          - evidence_refs:  ev_ids referenced by the decision card (if any)
          - session_id:     assigned session id (echo back so client can reuse)
          - stop_reason, turns, usage: diagnostics
        """
        try:
            client = get_llm_client("advisor")
        except LLMError as e:
            logger.error("LLM client init failed: %s", e)
            return await self._fallback_response(message, error=str(e))

        evidence_bus = EvidenceBus(self._db, self.session_id, agent=self.agent_role)
        decision_store = DecisionCardStore(self._db)

        messages: list[Message] = self._build_history(history)
        messages.append(Message.user(message))

        system_prompt = SYSTEM_PROMPT
        if self._db is not None:
            recent_ctx = await AgentContextService(self._db).build_recent_context_block(message)
            if recent_ctx:
                system_prompt = SYSTEM_PROMPT + "\n\n" + recent_ctx

        tool_defs = _build_tool_defs()
        tool_call_log: list[dict[str, Any]] = []
        evidence_refs: list[str] = []
        emitted_card: Optional[DecisionCard] = None
        stored_card_id: Optional[int] = None
        total_input_tokens = 0
        total_output_tokens = 0

        for turn in range(MAX_TOOL_TURNS):
            try:
                resp = await client.chat(
                    messages,
                    tools=tool_defs,
                    system=system_prompt,
                    temperature=0.3,
                    max_tokens=2048,
                )
            except LLMAuthError as e:
                logger.error("LLM auth failed: %s", e)
                return await self._fallback_response(message, error=f"auth: {e}")
            except LLMError as e:
                logger.error("LLM chat failed at turn %d: %s", turn, e)
                return await self._fallback_response(message, error=str(e))

            total_input_tokens += resp.usage.input_tokens
            total_output_tokens += resp.usage.output_tokens
            messages.append(resp.to_assistant_message())

            if not resp.has_tool_calls:
                return {
                    "answer": resp.text or "(模型未产出文本)",
                    "decision_card": emitted_card.model_dump(mode="json") if emitted_card else None,
                    "stored_card_id": stored_card_id,
                    "evidence_refs": evidence_refs,
                    "tool_calls": tool_call_log,
                    "session_id": self.session_id,
                    "fallback": False,
                    "turns": turn + 1,
                    "usage": {
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                        "model": resp.model,
                        "provider": client.provider_name,
                    },
                    "stop_reason": resp.stop_reason.value,
                }

            results: list[ToolResult] = []
            for tc in resp.tool_calls:
                if tc.name == EMIT_DECISION_CARD_TOOL_NAME:
                    # Intercept: DO NOT execute. Validate + persist.
                    card, err = self._try_build_decision_card(tc.arguments)
                    if err is not None:
                        results.append(ToolResult(
                            tool_call_id=tc.id,
                            content=json.dumps({"ok": False, "error": err}, ensure_ascii=False),
                            is_error=True,
                        ))
                        tool_call_log.append({
                            "turn": turn, "name": tc.name,
                            "arguments": tc.arguments,
                            "result_preview": f"validation error: {err}",
                        })
                    else:
                        assert card is not None
                        emitted_card = card
                        stored_card_id = await decision_store.save(card, session_id=self.session_id)
                        # Union of card-level + per-dim evidence refs
                        for ref in card.collect_evidence_refs():
                            if ref not in evidence_refs:
                                evidence_refs.append(ref)
                        results.append(ToolResult(
                            tool_call_id=tc.id,
                            content=json.dumps({
                                "ok": True,
                                "decision_id": card.decision_id,
                                "note": "决策卡已保存;请用 ≤3 句总结回复用户,不要重复卡片内容。",
                            }, ensure_ascii=False),
                        ))
                        tool_call_log.append({
                            "turn": turn, "name": tc.name,
                            "arguments": tc.arguments,
                            "result_preview": f"decision_id={card.decision_id}",
                        })
                    continue

                # Normal data-fetch tool
                output = await self._execute_tool(tc.name, tc.arguments)
                truncated = _truncate(output)
                ttl = _TOOL_TTL.get(tc.name, 300)
                ev = await evidence_bus.store(
                    source=tc.name,
                    query=tc.arguments,
                    data=truncated,
                    ttl_seconds=ttl,
                )
                # Return to LLM with evidence_id header so it can cite it
                content_for_llm = f"[evidence_id: {ev.ev_id}]\n{truncated}"
                results.append(ToolResult(tool_call_id=tc.id, content=content_for_llm))
                tool_call_log.append({
                    "turn": turn,
                    "name": tc.name,
                    "arguments": tc.arguments,
                    "evidence_id": ev.ev_id,
                    "result_preview": truncated[:400],
                })

            messages.append(Message.tool(results))

        logger.warning(
            "Agent hit MAX_TOOL_TURNS=%d for message: %s", MAX_TOOL_TURNS, message[:80]
        )
        last_text = ""
        for m in reversed(messages):
            if m.content:
                last_text = m.content
                break
        return {
            "answer": last_text or "抱歉,我在多轮工具调用后仍未得出结论,请将问题拆得更具体一些。",
            "decision_card": emitted_card.model_dump(mode="json") if emitted_card else None,
            "stored_card_id": stored_card_id,
            "evidence_refs": evidence_refs,
            "tool_calls": tool_call_log,
            "session_id": self.session_id,
            "fallback": False,
            "turns": MAX_TOOL_TURNS,
            "stop_reason": "max_turns",
        }

    # ── Helpers ──

    def _build_history(self, history: Optional[list[dict]]) -> list[Message]:
        out: list[Message] = []
        if not history:
            return out
        for entry in history:
            role = (entry.get("role") or "").lower()
            content = entry.get("content") or ""
            if not content:
                continue
            if role == "user":
                out.append(Message.user(content))
            elif role == "assistant":
                out.append(Message.assistant(text=content))
        return out

    async def _fallback_response(self, message: str, error: str = "") -> dict:
        answer = await self._fallback_answer(message)
        return {
            "answer": answer,
            "decision_card": None,
            "stored_card_id": None,
            "evidence_refs": [],
            "tool_calls": [],
            "session_id": self.session_id,
            "fallback": True,
            "error": error or None,
        }

    async def _fallback_answer(self, message: str) -> str:
        portfolio = json.loads(await self._tool_portfolio_summary())
        market = json.loads(await self._tool_market_overview())

        msg_lower = message.lower()

        if any(w in msg_lower for w in ["持仓", "portfolio", "我的", "持有"]):
            holdings = portfolio.get("holdings", [])
            lines = ["## 📊 你的持仓概览\n"]
            lines.append(f"- 总市值:¥{portfolio.get('total_value', 0):,.2f}")
            lines.append(
                f"- 总盈亏:¥{portfolio.get('total_pnl', 0):,.2f}"
                f"({portfolio.get('total_pnl_pct', 0):.2f}%)"
            )
            lines.append(f"- 持仓数量:{portfolio.get('position_count', 0)} 只\n")
            lines.append("**TOP5 持仓:**")
            for h in holdings[:5]:
                lines.append(
                    f"- {h['code']} | 市值 ¥{h['market_value']:,.2f} | 盈亏 {h['pnl_pct']:.2f}%"
                )
            return "\n".join(lines)

        if any(w in msg_lower for w in ["推荐", "筛选", "选基", "好基"]):
            return (
                "## 🔍 基金筛选\n\n"
                "请告诉我你的具体需求:\n"
                "- 偏好类型?(股票型/混合型/债券型/指数型)\n"
                "- 风险承受?(R1保守-R5激进)\n"
                "- 关注板块?(半导体/AI/新能源/医药/消费...)\n\n"
                "我可以调用同花顺技能为你精准筛选。"
            )

        if any(w in msg_lower for w in ["板块", "行业", "sector", "热点"]):
            inflow = market.get("top_inflow_sectors", [])
            lines = ["## 📈 市场热点\n"]
            if inflow:
                lines.append("**资金流入TOP3:**")
                for s in inflow:
                    lines.append(f"- {s['sector_name']}:净流入 {s.get('net_flow', 0):+.1f}亿")
            return "\n".join(lines)

        if any(w in msg_lower for w in ["风险", "risk"]):
            risk = json.loads(await self._tool_analyze_risk())
            return (
                f"## ⚠️ 持仓风险分析\n\n"
                f"- 风险等级:{risk.get('risk_level', '未知')}\n"
                f"- 前3大持仓集中度:{risk.get('top3_concentration', 0)}%\n"
                f"- 前5大持仓集中度:{risk.get('top5_concentration', 0)}%\n\n"
                f"*以上为简化分析,仅供参考*"
            )

        return (
            "我可以帮你:\n"
            "📊 **查看持仓** — 问问「我的持仓怎么样?」\n"
            "🔍 **筛选基金** — 说「推荐新能源基金」\n"
            "📈 **分析板块** — 问「半导体板块最近如何?」\n"
            "⚖️ **对比基金** — 试试「对比022184和001513」\n"
            "⚠️ **风险评估** — 问「我的持仓风险大吗?」"
        )
