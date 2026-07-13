"""Sector multi-dimensional scoring engine for ranking and recommendation."""
from dataclasses import dataclass
from typing import Any, Optional
from datetime import datetime, timedelta


@dataclass
class SectorScore:
    """Multi-dimensional sector score."""
    code: str
    name: str
    base_score: float  # 0-10

    # Dimension scores (0-10)
    price_score: float  # 技术面：价格+K线
    flow_score: float   # 资金面：主力净流入
    heat_score: float   # 热度面：换手率+关注度
    momentum_score: float  # 动量面：连续性

    # Overall
    composite_score: float  # 加权综合分
    signal: str  # STRONG / WATCH / WEAK / AVOID
    confidence: float  # 0-1 信号置信度

    # Supporting data
    change_pct: float
    flow_value: float  # 亿元
    turnover: float
    matched_sector: str = ""
    technical: str = ""
    volume: str = ""
    opportunity: str = ""

    def __post_init__(self):
        """Auto-calculate composite score if not set."""
        if self.composite_score == 0:
            self.composite_score = (
                self.price_score * 0.25 +
                self.flow_score * 0.30 +
                self.heat_score * 0.20 +
                self.momentum_score * 0.25
            )


class SectorScoringEngine:
    """
    Multi-dimensional sector scoring system.

    Dimensions:
    - Price/Technical (25%): 价格趋势、K线形态、均线
    - Capital Flow (30%): 主力资金净流、大单持续性
    - Heat Level (20%): 换手率、成交热度、关注度
    - Momentum (25%): 涨跌连续性、相对强弱
    """

    @staticmethod
    def score_price_technical(
        change_pct: float,
        technical_signal: str = "",
        ma_status: str = "",
    ) -> float:
        """
        技术面评分 (0-10)

        输入：
        - change_pct: 涨跌幅%
        - technical_signal: "站上5/10日线" / "跌破均线" / "震荡" 等
        - ma_status: 均线状态 "上升趋势" / "修复中" / "下跌趋势"
        """
        base_score = 5.0

        # 涨跌幅权重 (-2% to +2%)
        if change_pct > 2:
            base_score += 2.0
        elif change_pct > 1:
            base_score += 1.5
        elif change_pct > 0.5:
            base_score += 1.0
        elif change_pct < -2:
            base_score -= 2.0
        elif change_pct < -1:
            base_score -= 1.5
        elif change_pct < -0.5:
            base_score -= 1.0

        # 信号权重
        if "站上" in technical_signal or "中阳" in technical_signal:
            base_score += 1.5
        elif "跌破" in technical_signal or "长阴" in technical_signal:
            base_score -= 1.5
        elif "震荡" in technical_signal:
            base_score += 0.5

        # 均线状态
        if "上升" in ma_status:
            base_score += 0.5
        elif "下跌" in ma_status:
            base_score -= 0.5

        return max(0, min(10, base_score))

    @staticmethod
    def score_capital_flow(
        net_inflow_value: float,  # 亿元 (可以为负, 范围: -10 to +20)
        flow_ratio: float = 0.5,  # 相对基准的比率
        consecutive_days: int = 1,
    ) -> float:
        """
        资金面评分 (0-10)

        输入：
        - net_inflow_value: 主力净流入金额 (亿元，范围 -10 to +20)
        - flow_ratio: 相对历史均值的比率
        - consecutive_days: 连续流入天数
        """
        base_score = 5.0

        # 净流入金额 (调整阈值以适应亿元单位)
        if net_inflow_value > 10:
            base_score += 2.0
        elif net_inflow_value > 5:
            base_score += 1.5
        elif net_inflow_value > 0:
            base_score += 1.0
        elif net_inflow_value < -10:
            base_score -= 2.0
        elif net_inflow_value < -5:
            base_score -= 1.5
        elif net_inflow_value < 0:
            base_score -= 1.0

        # 连续天数加成
        if consecutive_days >= 3:
            base_score += 1.0
        elif consecutive_days >= 2:
            base_score += 0.5

        # 流动强度
        if flow_ratio > 1.5:
            base_score += 1.0
        elif flow_ratio > 0.8:
            base_score += 0.5

        return max(0, min(10, base_score))

    @staticmethod
    def score_heat_level(
        turnover_pct: float,  # 换手率 %
        volume_ratio: float = 1.0,  # 当前成交量/5日均量
        attention_level: int = 3,  # 1-5 关注度
    ) -> float:
        """
        热度评分 (0-10)

        输入：
        - turnover_pct: 换手率 (0.5-5)
        - volume_ratio: 成交量相对5日均量的倍数
        - attention_level: 市场关注热度 1-5
        """
        base_score = 5.0

        # 换手率权重 (>1% 开始计分)
        if turnover_pct > 2:
            base_score += 1.5
        elif turnover_pct > 1:
            base_score += 1.0
        elif turnover_pct > 0.5:
            base_score += 0.5
        elif turnover_pct < 0.3:
            base_score -= 0.5

        # 量能放大
        if volume_ratio > 1.5:
            base_score += 1.5
        elif volume_ratio > 1.2:
            base_score += 1.0
        elif volume_ratio > 1.0:
            base_score += 0.5
        elif volume_ratio < 0.8:
            base_score -= 1.0

        # 关注度
        base_score += (attention_level - 3) * 0.5

        return max(0, min(10, base_score))

    @staticmethod
    def score_momentum(
        change_pct: float,
        recent_trend: str = "neutral",  # "up"/"down"/"neutral"
        relative_strength: float = 0.0,  # vs 大盘的超额涨幅
    ) -> float:
        """
        动量评分 (0-10)

        输入：
        - change_pct: 今日涨跌幅
        - recent_trend: 近期趋势
        - relative_strength: 相对大盘的强弱度
        """
        base_score = 5.0

        # 涨跌幅 + 趋势匹配
        if recent_trend == "up" and change_pct > 0:
            base_score += 1.5
        elif recent_trend == "down" and change_pct < 0:
            base_score -= 1.5
        elif recent_trend == "up" and change_pct < 0:
            base_score -= 1.0  # 上升趋势却下跌
        elif recent_trend == "down" and change_pct > 0:
            base_score += 0.5  # 下跌趋势反弹

        # 相对强弱
        if relative_strength > 2:
            base_score += 1.5
        elif relative_strength > 1:
            base_score += 1.0
        elif relative_strength < -2:
            base_score -= 1.5
        elif relative_strength < -1:
            base_score -= 1.0

        return max(0, min(10, base_score))

    @staticmethod
    def determine_signal(
        composite_score: float,
        price_score: float,
        flow_score: float,
    ) -> tuple[str, float]:
        """
        根据综合分和关键指标确定信号
        返回 (signal, confidence)
        """
        # 信号生成规则
        if composite_score >= 7.5 and price_score >= 6.5 and flow_score >= 6.5:
            return ("STRONG", min(0.95, (composite_score - 7.0) / 3))
        elif composite_score >= 7.0 and price_score >= 6.0:
            return ("STRONG", min(0.85, (composite_score - 6.5) / 3))
        elif composite_score >= 6.0 and flow_score >= 5.5:
            return ("WATCH", min(0.80, (composite_score - 5.5) / 3))
        elif composite_score >= 5.0:
            return ("WATCH", 0.6)
        elif composite_score >= 4.0:
            return ("WEAK", 0.6)
        else:
            return ("AVOID", min(0.85, (5.0 - composite_score) / 3))

    @classmethod
    def score_sector(
        cls,
        sector_data: dict[str, Any],
    ) -> SectorScore:
        """
        生成完整的板块评分

        输入字典包含:
        {
            "code": "931160",
            "name": "光模块/通信",
            "change_pct": 2.5,
            "flow_value": 82.0,  # 亿元
            "turnover": 1200.0,  # 亿元
            "technical": "放量转强，站上5日线",
            "volume": "明显放大",
            "matched_sector": "通信设备",
            ... 其他可选字段
        }
        """
        code = sector_data.get("code", "")
        name = sector_data.get("name", "")
        change_pct = float(sector_data.get("change_pct", 0))
        flow_value = float(sector_data.get("flow_value", 0))
        turnover = float(sector_data.get("turnover", 0))
        technical = sector_data.get("technical", "")

        # 计算各维度分数
        price_score = cls.score_price_technical(
            change_pct=change_pct,
            technical_signal=technical,
            ma_status="上升趋势" if change_pct > 0 else "下跌趋势",
        )

        consecutive_days = int(sector_data.get("consecutive_days", 1) or 1)
        flow_score = cls.score_capital_flow(
            net_inflow_value=flow_value,
            consecutive_days=consecutive_days,
        )

        # 换手率估算：turnover 单位是亿元，相对值用于热度评分
        turnover_pct = min(5.0, (turnover / 100)) if turnover > 0 else 0.5
        heat_level_raw = int(sector_data.get("heat_level", 3) or 3)
        attention_level = max(1, min(5, heat_level_raw)) if heat_level_raw > 0 else 3
        heat_score = cls.score_heat_level(
            turnover_pct=turnover_pct,
            volume_ratio=1.0 if "放大" in technical else 0.8,
            attention_level=attention_level,
        )

        momentum_score = cls.score_momentum(
            change_pct=change_pct,
            recent_trend="up" if change_pct > 0 else "down" if change_pct < 0 else "neutral",
            relative_strength=change_pct,
        )

        # 综合分
        composite_score = (
            price_score * 0.25 +
            flow_score * 0.30 +
            heat_score * 0.20 +
            momentum_score * 0.25
        )

        # 信号判断
        signal, confidence = cls.determine_signal(
            composite_score=composite_score,
            price_score=price_score,
            flow_score=flow_score,
        )

        return SectorScore(
            code=code,
            name=name,
            base_score=composite_score,
            price_score=price_score,
            flow_score=flow_score,
            heat_score=heat_score,
            momentum_score=momentum_score,
            composite_score=composite_score,
            signal=signal,
            confidence=confidence,
            change_pct=change_pct,
            flow_value=flow_value,
            turnover=turnover,
            matched_sector=sector_data.get("matched_sector", ""),
            technical=technical,
            volume=sector_data.get("volume", ""),
            opportunity=sector_data.get("opportunity", ""),
        )

    @classmethod
    def score_multiple(
        cls,
        sectors_data: list[dict[str, Any]],
    ) -> list[SectorScore]:
        """批量评分"""
        scores = [cls.score_sector(sector) for sector in sectors_data]
        # 按综合分排序
        return sorted(scores, key=lambda s: s.composite_score, reverse=True)
