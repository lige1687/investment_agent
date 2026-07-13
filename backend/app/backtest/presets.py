"""Built-in backtest presets for common fund-to-signal mappings."""
from __future__ import annotations

from dataclasses import dataclass

from app.backtest.models import BacktestConfig, ProsperityConfig


@dataclass(frozen=True)
class BacktestPreset:
    preset_id: str
    title: str
    fund_code: str
    fund_name: str
    signal_symbol: str
    signal_name: str
    signal_provider: str
    signal_period: str
    description: str
    config: BacktestConfig
    etf_only: bool = False   # True = 无独立基金，直接用 ETF/指数 close 作为 NAV


_PRESETS: dict[str, BacktestPreset] = {}


def _register(preset: BacktestPreset) -> BacktestPreset:
    _PRESETS[preset.preset_id] = preset
    return preset


_register(BacktestPreset(
    preset_id="yifangda_info_industry_communication",
    title="易方达信息产业混合A + 通信ETF参考",
    fund_code="001513",
    fund_name="易方达信息产业混合A",
    signal_symbol="sh515880",
    signal_name="通信ETF参考",
    signal_provider="westock",
    signal_period="day",
    description="用通信设备/通信ETF作为信息产业基金的趋势和量能参考。",
    config=BacktestConfig(
        fund_code="001513",
        fund_name="易方达信息产业混合A",
        signal_code="sh515880",
        signal_name="通信ETF参考",
        target_position_pct=0.2,
        buy_volume_ratio=1.2,
        buy_stand_days=2,
        fund_category="high_elastic",
        profit_drawdown_trigger_pct=8.0,
        stop_loss_trigger_pct=20.0,
        max_single_position_pct=0.5,
        max_correlated_growth_exposure_pct=0.6,
        prosperity=ProsperityConfig(
            score=8.0,
            min_score_to_buy=7.0,
            reasons=["景气度高", "AI算力/通信设备方向业绩预期改善", "只在放量站稳趋势后分批买入"],
        ),
    ),
))

_register(BacktestPreset(
    preset_id="caitong_integrated_circuit_semiconductor",
    title="财通集成电路产业股票C + 半导体ETF参考",
    fund_code="006503",
    fund_name="财通集成电路产业股票C",
    signal_symbol="sh512760",
    signal_name="半导体ETF参考",
    signal_provider="westock",
    signal_period="day",
    description="用半导体ETF作为集成电路主题基金的趋势和量能参考。",
    config=BacktestConfig(
        fund_code="006503",
        fund_name="财通集成电路产业股票C",
        signal_code="sh512760",
        signal_name="半导体ETF参考",
        target_position_pct=0.2,
        buy_volume_ratio=1.25,
        buy_stand_days=2,
        fund_category="high_elastic",
        profit_drawdown_trigger_pct=10.0,
        stop_loss_trigger_pct=20.0,
        max_single_position_pct=0.5,
        max_correlated_growth_exposure_pct=0.6,
        prosperity=ProsperityConfig(
            score=8.0,
            min_score_to_buy=7.0,
            reasons=["景气度高", "半导体设备/国产替代方向弹性高", "高波动板块允许更宽回撤阈值"],
        ),
    ),
))


# ── ETF / 指数独立回测预设 ─────────────────────────────────────────────────
# etf_only=True：不需要基金代码，直接用 ETF close 作为净值

_register(BacktestPreset(
    preset_id="etf_communication",
    title="通信ETF 独立回测",
    fund_code="sh515880",
    fund_name="通信ETF",
    signal_symbol="sh515880",
    signal_name="通信ETF",
    signal_provider="westock",
    signal_period="day",
    description="直接回测通信ETF（515880）本身的买卖时机，close价格作为净值。",
    etf_only=True,
    config=BacktestConfig(
        fund_code="sh515880",
        fund_name="通信ETF",
        signal_code="sh515880",
        signal_name="通信ETF",
        target_position_pct=0.3,
        buy_volume_ratio=1.2,
        buy_stand_days=2,
        fund_category="high_elastic",
        profit_drawdown_trigger_pct=8.0,
        stop_loss_trigger_pct=15.0,
        max_single_position_pct=0.6,
        max_correlated_growth_exposure_pct=0.8,
        prosperity=ProsperityConfig(
            score=7.5,
            min_score_to_buy=7.0,
            reasons=["通信设备景气度较高", "AI算力驱动方向", "放量站稳后分批介入"],
        ),
    ),
))

_register(BacktestPreset(
    preset_id="etf_semiconductor",
    title="半导体ETF 独立回测",
    fund_code="sh512760",
    fund_name="半导体ETF",
    signal_symbol="sh512760",
    signal_name="半导体ETF",
    signal_provider="westock",
    signal_period="day",
    description="直接回测半导体ETF（512760）本身的买卖时机，close价格作为净值。",
    etf_only=True,
    config=BacktestConfig(
        fund_code="sh512760",
        fund_name="半导体ETF",
        signal_code="sh512760",
        signal_name="半导体ETF",
        target_position_pct=0.3,
        buy_volume_ratio=1.25,
        buy_stand_days=2,
        fund_category="high_elastic",
        profit_drawdown_trigger_pct=10.0,
        stop_loss_trigger_pct=18.0,
        max_single_position_pct=0.6,
        max_correlated_growth_exposure_pct=0.8,
        prosperity=ProsperityConfig(
            score=8.0,
            min_score_to_buy=7.0,
            reasons=["半导体国产替代方向", "高弹性品种允许宽回撤阈值", "量能修复后择机加仓"],
        ),
    ),
))

_register(BacktestPreset(
    preset_id="index_csi300",
    title="沪深300 指数独立回测",
    fund_code="sh000300",
    fund_name="沪深300",
    signal_symbol="sh000300",
    signal_name="沪深300",
    signal_provider="westock",
    signal_period="day",
    description="直接回测沪深300指数的买卖时机，适合宽基指数定投或波段策略验证。",
    etf_only=True,
    config=BacktestConfig(
        fund_code="sh000300",
        fund_name="沪深300",
        signal_code="sh000300",
        signal_name="沪深300",
        target_position_pct=0.4,
        buy_volume_ratio=1.1,
        buy_stand_days=3,
        fund_category="broad_index",
        profit_drawdown_trigger_pct=7.0,
        stop_loss_trigger_pct=12.0,
        max_single_position_pct=0.7,
        max_correlated_growth_exposure_pct=0.9,
        prosperity=ProsperityConfig(
            score=6.0,
            min_score_to_buy=5.5,
            reasons=["宽基指数分散风险", "企稳放量后渐进建仓", "止损线收窄避免深套"],
        ),
    ),
))


_register(BacktestPreset(
    preset_id="etf_nonferrous_metals",
    title="有色金属ETF 独立回测",
    fund_code="sh512400",
    fund_name="有色金属ETF",
    signal_symbol="sh512400",
    signal_name="有色金属ETF",
    signal_provider="westock",
    signal_period="day",
    description="直接回测华夏有色金属ETF（512400），有色金属（铜/铝/锂/稀土）板块波段策略验证。",
    etf_only=True,
    config=BacktestConfig(
        fund_code="sh512400",
        fund_name="有色金属ETF",
        signal_code="sh512400",
        signal_name="有色金属ETF",
        target_position_pct=0.3,
        buy_volume_ratio=1.2,
        buy_stand_days=2,
        fund_category="high_elastic",
        profit_drawdown_trigger_pct=9.0,
        stop_loss_trigger_pct=15.0,
        max_single_position_pct=0.6,
        max_correlated_growth_exposure_pct=0.8,
        prosperity=ProsperityConfig(
            score=7.0,
            min_score_to_buy=6.5,
            reasons=["铜铝等大宗商品需求回暖", "全球流动性拐点利好有色", "放量突破后跟进，缩量回调不追"],
        ),
    ),
))

_register(BacktestPreset(
    preset_id="etf_lithium_battery",
    title="锂电ETF 独立回测",
    fund_code="sz159937",
    fund_name="锂电ETF",
    signal_symbol="sz159937",
    signal_name="锂电ETF",
    signal_provider="westock",
    signal_period="day",
    description="直接回测国泰锂电ETF（159937），涵盖锂电池产业链（正极/负极/电解液/隔膜/电芯）。",
    etf_only=True,
    config=BacktestConfig(
        fund_code="sz159937",
        fund_name="锂电ETF",
        signal_code="sz159937",
        signal_name="锂电ETF",
        target_position_pct=0.3,
        buy_volume_ratio=1.25,
        buy_stand_days=2,
        fund_category="high_elastic",
        profit_drawdown_trigger_pct=10.0,
        stop_loss_trigger_pct=18.0,
        max_single_position_pct=0.6,
        max_correlated_growth_exposure_pct=0.8,
        prosperity=ProsperityConfig(
            score=7.0,
            min_score_to_buy=6.5,
            reasons=["新能源车销量持续增长", "锂矿价格企稳利好产业链利润修复", "高弹性品种宽止损，量能修复后介入"],
        ),
    ),
))


def list_backtest_presets() -> list[BacktestPreset]:
    return list(_PRESETS.values())


def get_backtest_preset(preset_id: str) -> BacktestPreset:
    try:
        return _PRESETS[preset_id]
    except KeyError as exc:
        raise ValueError(f"Unknown backtest preset: {preset_id}") from exc
