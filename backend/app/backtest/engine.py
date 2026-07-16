"""Daily fund backtest replay engine."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from math import pow

from app.backtest.batch_skill_router import BatchTradingSkillRouter
from app.backtest.events import BacktestEvent, EventDetector
from app.backtest.execution_logger import ExecutionLogger
from app.backtest.fees import FundFeeModel
from app.backtest.indicators import expma
from app.backtest.models import (
    BacktestConfig,
    BacktestMetrics,
    BacktestResult,
    FundNavPoint,
    PortfolioSnapshot,
    SignalBar,
    TradeRecord,
)
from app.backtest.observation.judge import DeterministicJudge, OBSERVATION_DAYS
from app.backtest.report_agent import ReportAgent
from app.backtest.strategy import RuleBasedStrategyAgent, StrategyDecision
from app.backtest.trigger_engine import TriggerEngine, TriggerSignal
from app.backtest.trigger_scanner import TriggerPoint, TriggerScanner


@dataclass
class HoldingBatch:
    batch_type: str
    shares: float
    buy_date: date
    cost_nav: float
    peak_return_pct: float = 0.0


_CORE_TIER_CONFIG: dict[str, dict[str, str]] = {
    "stop_loss": {
        "priority": "P0",
        "trigger_family": "stop_loss",
        "trigger_type": "core_batch_stop_loss",
        "reason_template": (
            "{label}基金批次亏损达 {current:.2f}%，触发核心仓止损保护，避免深套"
        ),
    },
    "tier1_high_peak_takeprofit": {
        "priority": "P1",
        "trigger_family": "take_profit",
        "trigger_type": "core_batch_high_peak_takeprofit",
        "reason_template": (
            "{label}基金批次最高浮盈 {peak:.2f}% 从峰值回撤 {drawdown:.2f}%，"
            "触发核心仓高位止盈保护（tier1）"
        ),
    },
    "tier2_mid_peak_takeprofit": {
        "priority": "P1",
        "trigger_family": "take_profit",
        "trigger_type": "core_batch_mid_peak_takeprofit",
        "reason_template": (
            "{label}基金批次最高浮盈 {peak:.2f}% 从峰值回撤 {drawdown:.2f}%，"
            "触发核心仓中位止盈保护（tier2）"
        ),
    },
    "tier2_dynamic": {
        "priority": "P1",
        "trigger_family": "take_profit",
        "trigger_type": "core_batch_dynamic_stop_profit",
        "reason_template": (
            "{label}基金批次最高浮盈 {peak:.2f}% 回吐至 {current:.2f}%，"
            "根据赛道牛熊调整止盈阈值，触发动态止盈保护（tier2_dynamic）"
        ),
    },
    "tier3_cost_line": {
        "priority": "P1",
        "trigger_family": "take_profit",
        "trigger_type": "core_batch_cost_line_protection",
        "reason_template": (
            "{label}基金批次最高浮盈 {peak:.2f}% 回吐至 {current:.2f}%，"
            "触发核心仓成本线保护（tier3，兜底）"
        ),
    },
}


class BacktestEngine:
    """Runs a deterministic daily replay for one fund and one signal asset."""

    def __init__(self, fee_model: FundFeeModel | None = None):
        self.fee_model = fee_model or FundFeeModel()

    def run(
        self,
        config: BacktestConfig,
        fund_nav: list[FundNavPoint],
        signal_bars: list[SignalBar],
        test_mode: bool = False,
    ) -> BacktestResult:
        if not fund_nav:
            raise ValueError("fund_nav must not be empty")
        if len(fund_nav) != len(signal_bars):
            raise ValueError("fund_nav and signal_bars must have the same length")
        if not 0 <= config.initial_position_pct <= 1:
            raise ValueError("initial_position_pct must be between 0 and 1")

        initial_nav = fund_nav[0].nav
        initial_position_value = config.initial_cash * config.initial_position_pct
        cash = config.initial_cash - initial_position_value
        shares = initial_position_value / initial_nav if initial_nav > 0 else 0.0
        batches = self._seed_initial_batches(config, shares, fund_nav[0].date, initial_nav)

        detector = EventDetector(config)
        strategy = RuleBasedStrategyAgent(config)
        reporter = ReportAgent(config)
        batch_skill_router = BatchTradingSkillRouter(config)
        audit_trigger_engine = TriggerEngine(config)
        execution_logger = ExecutionLogger()
        scanner = TriggerScanner(config)
        judge = DeterministicJudge()
        buy_trigger_map = {t.index: t for t in scanner.scan(signal_bars) if t.kind == "buy"}
        sell_trigger_map = {t.index: t for t in scanner.scan(signal_bars) if t.kind == "sell"}
        pending: list[tuple[BacktestEvent, StrategyDecision]] = []
        equity_curve: list[PortfolioSnapshot] = []
        trades: list[TradeRecord] = []
        events: list[dict] = []
        peak_return_pct = 0.0
        peak_equity = config.initial_cash
        sell_cooldown_until_index = -1
        core_sell_cooldown_until_index = -1
        # 买入观察期状态
        buy_observation_start_index = -1
        buy_observation_until_index = -1
        buy_observation_candidate: TriggerPoint | None = None
        # 卖出观察期状态（L1 触发 -> 2 天观察 -> judge -> T+3 卖）
        sell_observation_start_index = -1
        sell_observation_until_index = -1
        sell_observation_candidate: TriggerPoint | None = None
        post_sell_observation_start_index = -1
        post_sell_observation_until_index = -1
        post_sell_source_event_type = ""

        for index, nav_point in enumerate(fund_nav):
            self._update_batch_peaks(batches, nav_point.nav)
            cash, batches, executed_sell_events = self._execute_pending(
                pending=pending,
                nav_point=nav_point,
                cash=cash,
                batches=batches,
                config=config,
                trades=trades,
            )
            if executed_sell_events:
                source_event = executed_sell_events[-1]
                post_sell_source_event_type = str(
                    source_event.details.get("continuation_source_event_type")
                    or source_event.event_type
                )
                post_sell_observation_start_index = index + 1
                post_sell_observation_until_index = index + 3
            shares = self._total_shares(batches)
            pending = []

            equity = cash + shares * nav_point.nav
            peak_equity = max(peak_equity, equity)
            cumulative_return_pct = (equity / config.initial_cash - 1) * 100
            peak_return_pct = max(peak_return_pct, cumulative_return_pct)
            snapshot = PortfolioSnapshot(
                date=nav_point.date,
                cash=cash,
                shares=shares,
                nav=nav_point.nav,
                equity=equity,
                position_pct=0.0 if equity <= 0 else (shares * nav_point.nav) / equity,
                cumulative_return_pct=cumulative_return_pct,
                peak_return_pct=peak_return_pct,
            )
            equity_curve.append(snapshot)

            if index >= len(fund_nav) - 1:
                continue

            # 在观察期内不再触发新的核心仓保护，避免重复折半
            batch_events = (
                []
                if post_sell_observation_start_index <= index <= post_sell_observation_until_index
                else self._detect_batch_profit_protection(nav_point, snapshot, batches, index, signal_bars, config)
            )
            post_sell_events = self._detect_post_sell_observation(
                index=index,
                nav_point=nav_point,
                snapshot=snapshot,
                batches=batches,
                bars=signal_bars,
                config=config,
                source_event_type=post_sell_source_event_type,
                start_index=post_sell_observation_start_index,
                until_index=post_sell_observation_until_index,
            )
            # ── 买入/卖出触发与观察期（L1 机械触发 + L2 观察判定）─────────
            # TriggerScanner 预扫 buy/sell 触发点；EventDetector 的
            # buy_candidate / technical_breakdown 被忽略（引擎用 TriggerScanner 取代）
            detector_events = [
                e for e in detector.detect(index=index, bars=signal_bars, snapshot=snapshot)
                if e.event_type not in {"buy_candidate", "technical_breakdown"}
            ]

            buy_confirmation_event = None
            buy_hold_event = None
            if buy_observation_start_index <= index <= buy_observation_until_index:
                if index == buy_observation_until_index and buy_observation_candidate is not None:
                    # 观察期最后一天：调 judge 判定
                    trigger = buy_observation_candidate
                    window_start = trigger.index + 1
                    window_bars = signal_bars[window_start : window_start + OBSERVATION_DAYS]
                    judgment = judge.judge(
                        trigger, window_bars, config, all_bars=signal_bars
                    )
                    if judgment.confirmed and judgment.decision == "buy":
                        buy_confirmation_event = BacktestEvent(
                            event_type="buy_confirmation",
                            date=signal_bars[index].date,
                            reason=judgment.reason,
                            details={
                                "original_buy_signal": {"signal_level": "strong_buy"},
                                "observation_days": OBSERVATION_DAYS,
                                "trigger": {
                                    "kind": "buy",
                                    "index": trigger.index,
                                    "date": trigger.date.isoformat(),
                                },
                                "market_regime": "neutral",
                                "judgment": {
                                    "confirmed": judgment.confirmed,
                                    "gate": judgment.gate,
                                },
                            },
                            snapshot=snapshot,
                        )
                        buy_observation_start_index = -1
                        buy_observation_until_index = -1
                        buy_observation_candidate = None
                    else:
                        # 未确认：记录 hold + gate，重置观察期
                        buy_hold_event = BacktestEvent(
                            event_type="buy_candidate",
                            date=signal_bars[index].date,
                            reason=judgment.reason,
                            details={
                                "gate": judgment.gate or "observation_not_confirmed",
                                "trigger": {
                                    "kind": "buy",
                                    "index": trigger.index,
                                    "date": trigger.date.isoformat(),
                                },
                                "judgment": {
                                    "confirmed": judgment.confirmed,
                                    "gate": judgment.gate,
                                },
                            },
                            snapshot=snapshot,
                        )
                        buy_observation_start_index = -1
                        buy_observation_until_index = -1
                        buy_observation_candidate = None
            elif (
                index in buy_trigger_map
                and snapshot.position_pct
                < min(config.target_position_pct, config.max_single_position_pct)
            ):
                # 新的买入触发：进入观察期
                trigger = buy_trigger_map[index]
                buy_observation_start_index = index
                buy_observation_until_index = index + OBSERVATION_DAYS
                buy_observation_candidate = trigger
                if test_mode:
                    observe_event = BacktestEvent(
                        event_type="buy_candidate",
                        date=signal_bars[index].date,
                        reason="放量突破站上EXPMA，进入2天观察期",
                        details={
                            "trigger": {
                                "kind": "buy",
                                "index": trigger.index,
                                "date": trigger.date.isoformat(),
                            },
                        },
                        snapshot=snapshot,
                    )
                    decision = StrategyDecision(
                        action="observe",
                        reason="买入信号进入2天观察期，确认条件是否持续满足",
                        observe_days=OBSERVATION_DAYS,
                    )
                    events.append(
                        self._event_record(observe_event, decision, reporter, batch_skill_router)
                    )

            # ── 卖出触发与观察期（L1 机械触发 + L2 观察判定）──────────────
            sell_confirmation_event = None
            sell_hold_event = None
            in_post_sell_window = (
                post_sell_observation_start_index <= index <= post_sell_observation_until_index
            )
            if sell_observation_start_index <= index <= sell_observation_until_index:
                if index == sell_observation_until_index and sell_observation_candidate is not None:
                    # 观察期最后一天：调 judge 判定
                    trigger = sell_observation_candidate
                    window_start = trigger.index + 1
                    window_bars = signal_bars[window_start : window_start + OBSERVATION_DAYS]
                    judgment = judge.judge(
                        trigger, window_bars, config, all_bars=signal_bars
                    )
                    if judgment.confirmed and judgment.decision == "sell":
                        sell_confirmation_event = BacktestEvent(
                            event_type="technical_breakdown",
                            date=signal_bars[index].date,
                            reason=judgment.reason,
                            details={
                                "close": signal_bars[index].close,
                                "expma": expma(
                                    [b.close for b in signal_bars[: index + 1]],
                                    config.expma_window,
                                )[index],
                                "volume_ratio": signal_bars[index].volume,
                                "trigger": {
                                    "kind": "sell",
                                    "index": trigger.index,
                                    "date": trigger.date.isoformat(),
                                },
                                "judgment": {
                                    "confirmed": judgment.confirmed,
                                    "gate": judgment.gate,
                                },
                            },
                            snapshot=snapshot,
                        )
                        sell_observation_start_index = -1
                        sell_observation_until_index = -1
                        sell_observation_candidate = None
                    else:
                        # 未确认：记录 hold + gate，重置观察期
                        sell_hold_event = BacktestEvent(
                            event_type="technical_breakdown",
                            date=signal_bars[index].date,
                            reason=judgment.reason,
                            details={
                                "gate": judgment.gate or "observation_not_confirmed",
                                "trigger": {
                                    "kind": "sell",
                                    "index": trigger.index,
                                    "date": trigger.date.isoformat(),
                                },
                                "judgment": {
                                    "confirmed": judgment.confirmed,
                                    "gate": judgment.gate,
                                },
                            },
                            snapshot=snapshot,
                        )
                        sell_observation_start_index = -1
                        sell_observation_until_index = -1
                        sell_observation_candidate = None
            elif (
                index in sell_trigger_map
                and snapshot.position_pct > 0
                and not in_post_sell_window
            ):
                # 新的卖出触发：进入观察期
                trigger = sell_trigger_map[index]
                sell_observation_start_index = index
                sell_observation_until_index = index + OBSERVATION_DAYS
                sell_observation_candidate = trigger
                if test_mode:
                    observe_event = BacktestEvent(
                        event_type="technical_breakdown",
                        date=signal_bars[index].date,
                        reason="放量跌破EXPMA，进入2天观察期",
                        details={
                            "trigger": {
                                "kind": "sell",
                                "index": trigger.index,
                                "date": trigger.date.isoformat(),
                            },
                        },
                        snapshot=snapshot,
                    )
                    decision = StrategyDecision(
                        action="observe",
                        reason="卖出信号进入2天观察期，确认是否稳定跌破",
                        observe_days=OBSERVATION_DAYS,
                    )
                    events.append(
                        self._event_record(observe_event, decision, reporter, batch_skill_router)
                    )

            day_events = self._merge_batch_events(
                detector_events,
                batch_events + post_sell_events,
            )

            # 如果有 buy_confirmation 事件，添加到事件列表
            if buy_confirmation_event:
                day_events.append(buy_confirmation_event)

            # 如果有 sell_confirmation 事件，添加到事件列表
            if sell_confirmation_event:
                day_events.append(sell_confirmation_event)

            # 记录未确认的 hold 事件
            if buy_hold_event:
                hold_decision = StrategyDecision(
                    action="hold",
                    reason=buy_hold_event.reason,
                )
                events.append(
                    self._event_record(buy_hold_event, hold_decision, reporter, batch_skill_router)
                )
            if sell_hold_event:
                hold_decision = StrategyDecision(
                    action="hold",
                    reason=sell_hold_event.reason,
                )
                events.append(
                    self._event_record(sell_hold_event, hold_decision, reporter, batch_skill_router)
                )

            emitted_event = bool(buy_hold_event or sell_hold_event)
            for event in day_events:
                is_core_protection = event.details.get("batch_protection") == "core_cost_line"
                # 核心仓保护走独立冷却期，避免每日重复触发；但不受非核心仓卖出冷却期约束。
                if is_core_protection and index <= core_sell_cooldown_until_index:
                    if test_mode:
                        decision = StrategyDecision(
                            action="observe",
                            reason="核心仓保护冷静期内，本次触发只记录判断，不重复卖出",
                            observe_days=max(0, core_sell_cooldown_until_index - index),
                        )
                        events.append(self._event_record(event, decision, reporter, batch_skill_router))
                        emitted_event = True
                    continue
                if (
                    event.event_type in {"profit_drawdown", "technical_breakdown"}
                    and index <= sell_cooldown_until_index
                    and not is_core_protection
                ):
                    if test_mode:
                        decision = StrategyDecision(
                            action="observe",
                            reason="卖出冷静期内，本次触发只记录判断，不重复卖出",
                            observe_days=max(0, sell_cooldown_until_index - index),
                        )
                        events.append(self._event_record(event, decision, reporter, batch_skill_router))
                        emitted_event = True
                    continue
                decision = strategy.decide(event)
                events.append(self._event_record(event, decision, reporter, batch_skill_router))
                emitted_event = True

                # 记录执行日志
                snapshot_before = {
                    "position_pct": snapshot.position_pct,
                    "equity": snapshot.equity,
                }
                trade_executed = decision.action in {"buy", "sell"}
                execution_logger.record(
                    date=signal_bars[index].date,
                    event=event,
                    decision=decision,
                    snapshot_before=snapshot_before,
                    snapshot_after=snapshot_before,  # 待执行时和执行前相同
                    nav=nav_point.nav,
                    trade_executed=trade_executed,
                )

                if decision.action in {"buy", "sell"}:
                    pending.append((event, decision))
                if decision.action == "sell" and event.event_type in {"profit_drawdown", "technical_breakdown"}:
                    if is_core_protection:
                        # 核心仓保护的第一次卖出后设置冷却期 = 观察期长度（3天）
                        # 这样观察期结束后自动解除冷却，允许在观察期末/期后进行最后一次卖出
                        # 避免反复折半。同时不激活常规 sell_cooldown，让常规 profit_drawdown
                        # 在观察期结束后能正常触发最后一次卖出。
                        core_sell_cooldown_until_index = index + decision.observe_days
                    else:
                        # 修复卖出冷却期逻辑：
                        # 不再使用固定的 sell_cooldown_days（10天太长）
                        # 改为只使用 observe_days（通常 3 天）
                        # 在观察期内通过 post_sell_observation 检查是否修复
                        # 修复了就不再卖，没修复就继续卖（观察期结束后）
                        sell_cooldown_until_index = index + decision.observe_days
            if test_mode and not emitted_event:
                triggers = audit_trigger_engine.evaluate(index=index, bars=signal_bars, snapshot=snapshot)
                if triggers:
                    event = self._system_check_event(signal_bars[index].date, snapshot, triggers)
                    decision = StrategyDecision(
                        action="observe",
                        reason=self._audit_observe_reason(event),
                    )
                    events.append(self._event_record(event, decision, reporter, batch_skill_router))

        # ── 末段不完整窗口处理 ──────────────────────────────────────────
        # 观察期未在循环内结束（触发临近末段 bar）-> 记录 incomplete_window hold
        last_snapshot = equity_curve[-1] if equity_curve else None
        for obs_candidate, obs_type in [
            (buy_observation_candidate, "buy"),
            (sell_observation_candidate, "sell"),
        ]:
            if obs_candidate is None:
                continue
            trigger = obs_candidate
            window_start = trigger.index + 1
            window_bars = signal_bars[window_start : window_start + OBSERVATION_DAYS]
            judgment = judge.judge(trigger, window_bars, config, all_bars=signal_bars)
            # 观察期未在循环内结束 = 无法 T+3 成交 -> incomplete_window
            gate = "incomplete_window"
            hold_event = BacktestEvent(
                event_type="buy_candidate" if obs_type == "buy" else "technical_breakdown",
                date=signal_bars[-1].date,
                reason=f"{'买入' if obs_type == 'buy' else '卖出'}观察窗口未完成（临近末段bar），{judgment.reason}",
                details={
                    "gate": gate,
                    "trigger": {
                        "kind": obs_type,
                        "index": trigger.index,
                        "date": trigger.date.isoformat(),
                    },
                    "judgment": {
                        "confirmed": judgment.confirmed,
                        "gate": judgment.gate,
                    },
                },
                snapshot=last_snapshot,
            )
            hold_decision = StrategyDecision(
                action="hold",
                reason=hold_event.reason,
                gate=gate,
            )
            events.append(
                self._event_record(hold_event, hold_decision, reporter, batch_skill_router)
            )

        metrics = self._calculate_metrics(config, equity_curve, trades, peak_equity)

        # 生成执行日志文件
        execution_log_path = None
        try:
            import tempfile
            import os

            # 生成日志文件到临时目录
            log_content = execution_logger.to_markdown()
            log_filename = f"backtest_execution_log_{fund_nav[0].date.isoformat()}_to_{fund_nav[-1].date.isoformat()}.md"
            log_filepath = os.path.join(tempfile.gettempdir(), log_filename)

            with open(log_filepath, "w", encoding="utf-8") as f:
                f.write(log_content)

            execution_log_path = log_filepath
        except Exception as e:
            # 日志生成失败不影响回测结果
            print(f"警告：执行日志生成失败: {e}")

        return BacktestResult(
            config=config,
            metrics=metrics,
            equity_curve=equity_curve,
            trades=trades,
            events=events,
            execution_log_path=execution_log_path,
        )

    def _event_record(
        self,
        event: BacktestEvent,
        decision: StrategyDecision,
        reporter: ReportAgent,
        batch_skill_router: BatchTradingSkillRouter,
    ) -> dict:
        # Merge decision.gate into event details for visible gates
        details = dict(event.details)
        if decision.gate and "gate" not in details:
            details["gate"] = decision.gate
        record = {
            "date": event.date.isoformat(),
            "event_type": event.event_type,
            "reason": event.reason,
            "details": details,
            "decision": asdict(decision),
            "analysis_report": reporter.build(event, decision),
            "skill_route": batch_skill_router.route(event, decision),
        }
        if event.event_type == "system_check":
            route = record["skill_route"]
            record["audit"] = {
                "final_decider": self._final_decider(route),
                "final_result": decision.action,
                "why_no_trade": decision.reason,
                "used_skills": route["required_skill_order"],
            }
        return record

    def _system_check_event(
        self,
        event_date: date,
        snapshot: PortfolioSnapshot,
        triggers: list[TriggerSignal],
    ) -> BacktestEvent:
        return BacktestEvent(
            event_type="system_check",
            date=event_date,
            reason="测试模式：机械触发系统判断，但未形成实际交易事件",
            details={"trigger_signals": [trigger.to_dict() for trigger in triggers]},
            snapshot=snapshot,
        )

    def _audit_observe_reason(self, event: BacktestEvent) -> str:
        triggers = event.details.get("trigger_signals", [])
        families = {trigger.get("trigger_family") for trigger in triggers if isinstance(trigger, dict)}
        if "account_risk" in families:
            return "账户风控触发，测试模式记录风险判断；未执行交易是因为没有形成明确卖出执行事件"
        if "buy_observation" in families or "add_position" in families:
            return "出现买入/补仓观察触发，但五维买入闭环、账户风控或批次规划未同时满足，系统保持观察"
        if "take_profit" in families:
            return "出现止盈观察触发，但未命中任何基金批次自身止盈回撤条件，系统保持持有"
        if "stop_loss" in families:
            return "出现止损观察触发，但未命中具体批次止损执行条件，系统保持观察"
        return "触发机械观察条件，但未通过批次交易系统的执行条件，系统保持观察"

    def _final_decider(self, route: dict) -> str:
        skills = route.get("required_skill_order", [])
        if not skills:
            return "batch-trading-router"
        if route.get("immediate_vetoes"):
            return skills[1] if len(skills) > 1 else skills[0]
        return skills[-1]

    def _execute_pending(
        self,
        pending: list[tuple[BacktestEvent, StrategyDecision]],
        nav_point: FundNavPoint,
        cash: float,
        batches: list[HoldingBatch],
        config: BacktestConfig,
        trades: list[TradeRecord],
    ) -> tuple[float, list[HoldingBatch], list[BacktestEvent]]:
        executed_sell_events: list[BacktestEvent] = []
        for event, decision in pending:
            if decision.action == "buy":
                shares = self._total_shares(batches)
                equity = cash + shares * nav_point.nav
                spend = min(cash, equity * decision.target_position_delta_pct)
                if spend <= 0:
                    continue
                bought_shares, fee = self.fee_model.calculate_buy_shares(spend, nav_point.nav)
                cash -= spend
                batch_type = self._next_buy_batch_type(config, batches, nav_point.nav, equity)
                batches.append(HoldingBatch(
                    batch_type=batch_type,
                    shares=bought_shares,
                    buy_date=nav_point.date,
                    cost_nav=nav_point.nav,
                ))
                trades.append(TradeRecord(
                    date=nav_point.date,
                    action="buy",
                    nav=nav_point.nav,
                    shares=bought_shares,
                    cash_delta=-spend,
                    fee=fee,
                    reason=decision.reason,
                    event_type=event.event_type,
                    batch_type=batch_type,
                    batch_cost_nav=nav_point.nav,
                    batch_return_pct=0.0,
                    batch_peak_return_pct=0.0,
                ))
            elif decision.action == "sell":
                sell_batches = self._select_batches_to_sell(event, decision, batches, nav_point.nav)
                if not sell_batches:
                    continue
                sold_any = False
                for batch in sell_batches:
                    shares_to_sell = batch.shares
                    if shares_to_sell <= 0:
                        continue
                    sold_any = True
                    holding_days = (nav_point.date - batch.buy_date).days
                    cash_received, fee = self.fee_model.calculate_sell_cash(
                        shares_to_sell,
                        nav_point.nav,
                        holding_days,
                    )
                    cash += cash_received
                    if any(existing is batch for existing in batches):
                        batches.remove(batch)
                    batch_return_pct = self._batch_return_pct(batch, nav_point.nav)
                    trades.append(TradeRecord(
                        date=nav_point.date,
                        action="sell",
                        nav=nav_point.nav,
                        shares=shares_to_sell,
                        cash_delta=cash_received,
                        fee=fee,
                        reason=self._batch_sell_reason(event, decision, batch, batch_return_pct),
                        event_type=event.event_type,
                        batch_type=batch.batch_type,
                        batch_cost_nav=batch.cost_nav,
                        batch_return_pct=batch_return_pct,
                        batch_peak_return_pct=batch.peak_return_pct,
                    ))
                if sold_any:
                    executed_sell_events.append(event)
        return cash, batches, executed_sell_events

    def _seed_initial_batches(
        self,
        config: BacktestConfig,
        shares: float,
        buy_date: date,
        cost_nav: float,
    ) -> list[HoldingBatch]:
        if shares <= 0 or config.initial_position_pct <= 0:
            return []
        batch_plan = [
            ("core", config.target_position_pct * 0.5),
            ("confirmation", config.target_position_pct * 0.3),
            ("high_position", config.target_position_pct * 0.2),
        ]
        remaining_pct = config.initial_position_pct
        batches: list[HoldingBatch] = []
        for batch_type, planned_account_pct in batch_plan:
            if remaining_pct <= 1e-9:
                break
            batch_account_pct = min(remaining_pct, planned_account_pct)
            batch_shares = shares * (batch_account_pct / config.initial_position_pct)
            if batch_shares > 1e-9:
                batches.append(HoldingBatch(
                    batch_type=batch_type,
                    shares=batch_shares,
                    buy_date=buy_date,
                    cost_nav=cost_nav,
                ))
            remaining_pct -= batch_account_pct
        if remaining_pct > 1e-9:
            batches.append(HoldingBatch(
                batch_type="high_position",
                shares=shares * (remaining_pct / config.initial_position_pct),
                buy_date=buy_date,
                cost_nav=cost_nav,
            ))
        return batches

    def _next_buy_batch_type(
        self,
        config: BacktestConfig,
        batches: list[HoldingBatch],
        nav: float,
        equity: float,
    ) -> str:
        if equity <= 0:
            return "core"
        values_by_type = self._batch_values_by_type(batches, nav)
        target_value = equity * config.target_position_pct
        if values_by_type.get("core", 0.0) < target_value * 0.5 - 1e-6:
            return "core"
        if values_by_type.get("confirmation", 0.0) < target_value * 0.3 - 1e-6:
            return "confirmation"
        return "high_position"

    def _select_batches_to_sell(
        self,
        event: BacktestEvent,
        decision: StrategyDecision,
        batches: list[HoldingBatch],
        nav: float,
    ) -> list[HoldingBatch]:
        # 核心仓分级保护事件独立成链，绕过常规批次优先级过滤，直接卖出核心仓；
        # 该分支需放在其他分支之前，以确保 core_cost_line 命中时不被 profit_drawdown
        # 的常规选择逻辑（优先卖 trial/high_position/confirmation）覆盖。
        # 止损档位需要清仓，其余档位半仓保护。
        if event.details.get("batch_protection") == "core_cost_line":
            tier = event.details.get("core_protection_tier")
            if tier == "stop_loss":
                return [batch for batch in batches if batch.batch_type == "core"]
            return self._core_half_batches(batches)
        if event.event_type == "stop_loss":
            return list(batches)
        if event.event_type == "technical_breakdown":
            selected = [
                batch for batch in self._batches_by_priority(batches, ["trial", "high_position", "confirmation"])
                if self._batch_breakdown_sell_allowed(batch, nav)
            ]
            return selected
        if event.event_type == "profit_drawdown":
            target_batch_type = event.details.get("target_batch_type")
            if isinstance(target_batch_type, str):
                selected = [
                    batch for batch in self._batches_by_priority(batches, [target_batch_type])
                    if self._batch_take_profit_allowed(batch, nav)
                ]
                return selected[:1]
            selected = [
                batch for batch in self._batches_by_priority(batches, ["trial", "high_position"])
                if self._batch_take_profit_allowed(batch, nav)
            ]
            if selected:
                return selected[:1]
            selected = [
                batch for batch in self._batches_by_priority(batches, ["confirmation"])
                if self._batch_take_profit_allowed(batch, nav)
            ]
            return selected[:1] if selected else self._core_half_batches(batches)
        if event.event_type == "post_sell_observation":
            if event.details.get("recommended_action") != "sell":
                return []
            source_event_type = event.details.get("continuation_source_event_type")
            if source_event_type in {"technical_breakdown", "stop_loss"}:
                selected = [
                    batch for batch in self._batches_by_priority(batches, ["trial", "high_position", "confirmation"])
                    if self._batch_breakdown_sell_allowed(batch, nav)
                ]
                if selected:
                    return selected
                if event.details.get("core_sell_allowed"):
                    return self._core_half_batches(batches)
                return []
            if source_event_type == "profit_drawdown":
                selected = [
                    batch for batch in self._batches_by_priority(batches, ["trial", "high_position", "confirmation"])
                    if self._batch_take_profit_allowed(batch, nav)
                ]
                if selected:
                    return selected[:1]
                # 核心仓在卖后观察窗口内的处理：
                # 如果是最后一天（观察期结束）且趋势仍未修复，卖出全部剩余核心仓
                # 否则不卖（由上一步 _post_sell_recheck_result 判断决定）
                if event.details.get("core_sell_allowed"):
                    observation_day = event.details.get("observation_day", 1)
                    observation_days_total = event.details.get("observation_days_total", 3)
                    if observation_day >= observation_days_total:
                        # 最后一天：卖出全部剩余核心仓，彻底清仓
                        return [batch for batch in batches if batch.batch_type == "core"]
                    else:
                        # 非最后一天：不卖（只观察）
                        return []
                return []
            return []
        shares_to_sell = self._total_shares(batches) * decision.ratio_of_position
        return self._batches_covering_shares(batches, shares_to_sell)

    def _batches_by_priority(self, batches: list[HoldingBatch], priority: list[str]) -> list[HoldingBatch]:
        result: list[HoldingBatch] = []
        for batch_type in priority:
            result.extend(batch for batch in batches if batch.batch_type == batch_type)
        return result

    def _core_half_batches(self, batches: list[HoldingBatch]) -> list[HoldingBatch]:
        core_batches = [batch for batch in batches if batch.batch_type == "core"]
        if not core_batches:
            return []
        core = core_batches[0]
        half = core.shares * 0.5
        if half <= 1e-9:
            return []
        core.shares -= half
        return [HoldingBatch(
            batch_type="core",
            shares=half,
            buy_date=core.buy_date,
            cost_nav=core.cost_nav,
            peak_return_pct=core.peak_return_pct,
        )]

    def _batches_covering_shares(
        self,
        batches: list[HoldingBatch],
        shares_to_sell: float,
    ) -> list[HoldingBatch]:
        selected: list[HoldingBatch] = []
        remaining = shares_to_sell
        for batch in self._batches_by_priority(batches, ["trial", "high_position", "confirmation", "core"]):
            if remaining <= 1e-9:
                break
            if batch.shares <= remaining + 1e-9:
                selected.append(batch)
                remaining -= batch.shares
            else:
                batch.shares -= remaining
                selected.append(HoldingBatch(
                    batch_type=batch.batch_type,
                    shares=remaining,
                    buy_date=batch.buy_date,
                    cost_nav=batch.cost_nav,
                    peak_return_pct=batch.peak_return_pct,
                ))
                remaining = 0
        return selected

    def _update_batch_peaks(self, batches: list[HoldingBatch], nav: float) -> None:
        for batch in batches:
            batch.peak_return_pct = max(batch.peak_return_pct, self._batch_return_pct(batch, nav))

    def _batch_return_pct(self, batch: HoldingBatch, nav: float) -> float:
        if batch.cost_nav <= 0:
            return 0.0
        return (nav / batch.cost_nav - 1) * 100

    def _batch_take_profit_allowed(self, batch: HoldingBatch, nav: float) -> bool:
        current = self._batch_return_pct(batch, nav)
        drawdown = batch.peak_return_pct - current
        if batch.batch_type == "trial":
            return (batch.peak_return_pct >= 3 and drawdown >= 3) or self._batch_cost_line_protection_triggered(batch, current)
        if batch.batch_type == "high_position":
            return (batch.peak_return_pct >= 5 and drawdown >= 4) or self._batch_cost_line_protection_triggered(batch, current)
        if batch.batch_type == "confirmation":
            return (batch.peak_return_pct >= 8 and drawdown >= 5) or self._batch_cost_line_protection_triggered(batch, current)
        if batch.batch_type == "core":
            return batch.peak_return_pct >= 15 and drawdown >= 6
        return False

    def _batch_breakdown_sell_allowed(self, batch: HoldingBatch, nav: float) -> bool:
        current = self._batch_return_pct(batch, nav)
        drawdown = batch.peak_return_pct - current
        if batch.batch_type == "trial":
            return True
        if batch.batch_type == "high_position":
            return current <= -8 or (batch.peak_return_pct >= 5 and drawdown >= 4)
        if batch.batch_type == "confirmation":
            return current <= -10 or (batch.peak_return_pct >= 8 and drawdown >= 5) or self._batch_cost_line_protection_triggered(batch, current)
        return False

    def _batch_sell_reason(
        self,
        event: BacktestEvent,
        decision: StrategyDecision,
        batch: HoldingBatch,
        batch_return_pct: float,
    ) -> str:
        if event.details.get("batch_protection") == "core_cost_line" and batch.batch_type == "core":
            tier = event.details.get("core_protection_tier", "tier3_cost_line")
            tier_label = {
                "stop_loss": "核心仓止损清仓",
                "tier1_high_peak_takeprofit": "核心仓高位止盈半仓保护（tier1）",
                "tier2_mid_peak_takeprofit": "核心仓中位止盈半仓保护（tier2）",
                "tier2_dynamic": "核心仓动态止盈半仓保护",
                "tier3_cost_line": "核心仓成本线半仓兜底保护（tier3）",
            }.get(tier, "核心仓保护")
            return (
                f"{decision.reason}；{self._batch_label(batch.batch_type)}基金批次最高浮盈"
                f"{batch.peak_return_pct:.2f}%，当前收益{batch_return_pct:.2f}%，"
                f"执行{tier_label}"
            )
        if event.details.get("batch_protection") == "cost_line" and event.details.get("target_batch_type") == batch.batch_type:
            return (
                f"{decision.reason}；{self._batch_label(batch.batch_type)}基金批次最高浮盈"
                f"{batch.peak_return_pct:.2f}%，当前收益{batch_return_pct:.2f}%回到成本线附近，"
                "执行确认仓批次保护卖出"
            )
        if event.event_type == "post_sell_observation":
            return (
                f"{decision.reason}；卖后观察窗口第{event.details.get('observation_day', '-')}"
                f"天复核，{self._batch_label(batch.batch_type)}基金批次收益{batch_return_pct:.2f}%，"
                f"最大浮盈{batch.peak_return_pct:.2f}%"
            )
        if batch_return_pct < 0:
            return (
                f"{decision.reason}；{self._batch_label(batch.batch_type)}基金批次收益"
                f"{batch_return_pct:.2f}%，本次按批次止损/破位处理"
            )
        return (
            f"{decision.reason}；{self._batch_label(batch.batch_type)}基金批次收益"
            f"{batch_return_pct:.2f}%，最大浮盈{batch.peak_return_pct:.2f}%"
        )

    def _batch_label(self, batch_type: str) -> str:
        labels = {
            "core": "核心仓",
            "confirmation": "确认仓",
            "high_position": "高位/灵活仓",
            "trial": "试错仓",
        }
        return labels.get(batch_type, batch_type)

    def _detect_batch_profit_protection(
        self,
        nav_point: FundNavPoint,
        snapshot: PortfolioSnapshot,
        batches: list[HoldingBatch],
        index: int,
        bars: list[SignalBar],
        config: BacktestConfig,
    ) -> list[BacktestEvent]:
        for batch in self._batches_by_priority(batches, ["trial", "high_position", "confirmation"]):
            current = self._batch_return_pct(batch, nav_point.nav)
            if not self._batch_cost_line_protection_triggered(batch, current):
                continue
            drawdown = batch.peak_return_pct - current
            label = self._batch_label(batch.batch_type)
            return [
                BacktestEvent(
                    event_type="profit_drawdown",
                    date=nav_point.date,
                    reason=f"{label}基金批次盈利后回到成本线附近，触发批次保护判断",
                    details={
                        "batch_protection": "cost_line",
                        "target_batch_type": batch.batch_type,
                        "batch_cost_nav": batch.cost_nav,
                        "batch_current_nav": nav_point.nav,
                        "batch_current_return_pct": current,
                        "batch_peak_return_pct": batch.peak_return_pct,
                        "batch_drawdown_from_peak_pct": drawdown,
                        "trigger_signals": [
                            {
                                "priority": "P2",
                                "trigger_family": "take_profit",
                                "trigger_type": "batch_cost_line_protection",
                                "reason": f"{label}最高浮盈回撤至成本线附近，必须优先保护该批次",
                                "should_call_ai": True,
                                "metrics": {
                                    "batch_type": batch.batch_type,
                                    "cost_nav": batch.cost_nav,
                                    "current_nav": nav_point.nav,
                                    "current_return_pct": current,
                                    "peak_return_pct": batch.peak_return_pct,
                                    "drawdown_from_peak_pct": drawdown,
                                },
                            }
                        ],
                    },
                    snapshot=snapshot,
                )
            ]

        # 核心仓的独立分级保护：仅当**没有其他可卖的脆弱批次**时才启动。
        # 若脆弱批次仍可通过常规 profit_drawdown/technical_breakdown 处理（比如
        # 高位仓自身仍处止盈档位），则让组合级事件优先卖脆弱批次，避免核心仓
        # 保护抢占本该由脆弱批次承担的止盈动作。
        #
        # 例外：硬顶保护（_CORE_HARD_CAP_*）——当核心仓从高位回撤过深时，
        # 无论脆弱批次是否还可卖，都必须立即触发核心仓保护，防止高位浮盈被全吃。
        _CORE_HARD_CAP_PEAK = 40.0       # 峰值浮盈达到此值才启用硬顶
        _CORE_HARD_CAP_DRAWDOWN = 20.0   # 从峰值回撤超过此值触发硬顶绕过

        current_nav = nav_point.nav

        # 预先检查核心仓是否已触达硬顶（优先于脆弱批次屏蔽逻辑）
        core_hard_cap_triggered = any(
            batch.batch_type == "core"
            and batch.peak_return_pct >= _CORE_HARD_CAP_PEAK
            and (batch.peak_return_pct - self._batch_return_pct(batch, current_nav)) >= _CORE_HARD_CAP_DRAWDOWN
            for batch in batches
        )

        fragile_takeprofit_available = any(
            self._batch_take_profit_allowed(batch, current_nav)
            or self._batch_breakdown_sell_allowed(batch, current_nav)
            for batch in batches
            if batch.batch_type in {"trial", "high_position", "confirmation"}
        )
        # 脆弱批次屏蔽只在没有硬顶触发时生效
        if fragile_takeprofit_available and not core_hard_cap_triggered:
            return []
        for batch in self._batches_by_priority(batches, ["core"]):
            current = self._batch_return_pct(batch, nav_point.nav)
            # 获取市场制度判断（宏观面 + 技术面）
            market_regime = self._get_market_regime(index, bars, config)
            tier = self._core_protection_tier(batch, current, market_regime)
            if tier is None:
                continue
            drawdown = batch.peak_return_pct - current
            label = self._batch_label(batch.batch_type)
            tier_config = _CORE_TIER_CONFIG[tier]
            tier_reason = tier_config["reason_template"].format(
                label=label,
                peak=batch.peak_return_pct,
                current=current,
                drawdown=drawdown,
            )
            return [
                BacktestEvent(
                    event_type="profit_drawdown",
                    date=nav_point.date,
                    reason=tier_reason,
                    details={
                        "batch_protection": "core_cost_line",
                        "core_protection_tier": tier,
                        "target_batch_type": batch.batch_type,
                        "batch_cost_nav": batch.cost_nav,
                        "batch_current_nav": nav_point.nav,
                        "batch_current_return_pct": current,
                        "batch_peak_return_pct": batch.peak_return_pct,
                        "batch_drawdown_from_peak_pct": drawdown,
                        "trigger_signals": [
                            {
                                "priority": tier_config["priority"],
                                "trigger_family": tier_config["trigger_family"],
                                "trigger_type": tier_config["trigger_type"],
                                "reason": tier_reason,
                                "should_call_ai": True,
                                "metrics": {
                                    "batch_type": batch.batch_type,
                                    "protection_tier": tier,
                                    "cost_nav": batch.cost_nav,
                                    "current_nav": nav_point.nav,
                                    "current_return_pct": current,
                                    "peak_return_pct": batch.peak_return_pct,
                                    "drawdown_from_peak_pct": drawdown,
                                },
                            }
                        ],
                    },
                    snapshot=snapshot,
                )
            ]
        return []

    def _detect_post_sell_observation(
        self,
        index: int,
        nav_point: FundNavPoint,
        snapshot: PortfolioSnapshot,
        batches: list[HoldingBatch],
        bars: list[SignalBar],
        config: BacktestConfig,
        source_event_type: str,
        start_index: int,
        until_index: int,
    ) -> list[BacktestEvent]:
        if not source_event_type or index < start_index or index > until_index or not batches:
            return []
        observation_day = index - start_index + 1
        observation_days_total = until_index - start_index + 1
        should_sell, sell_reason, core_sell_allowed = self._post_sell_recheck_result(
            source_event_type=source_event_type,
            index=index,
            bars=bars,
            config=config,
            batches=batches,
            nav=nav_point.nav,
            observation_day=observation_day,
            observation_days_total=observation_days_total,
        )
        priority = "P1" if source_event_type in {"technical_breakdown", "stop_loss"} else "P2"
        family = "stop_loss" if source_event_type in {"technical_breakdown", "stop_loss"} else "take_profit"
        action_text = "继续卖出" if should_sell else "继续观察"
        return [
            BacktestEvent(
                event_type="post_sell_observation",
                date=nav_point.date,
                reason=f"卖后观察期第{observation_day}天复核：{sell_reason}",
                details={
                    "recommended_action": "sell" if should_sell else "observe",
                    "continuation_source_event_type": source_event_type,
                    "observation_day": observation_day,
                    "observation_days_total": 3,
                    "observation_days_remaining": max(until_index - index, 0),
                    "core_sell_allowed": core_sell_allowed,
                    "trigger_signals": [
                        {
                            "priority": priority,
                            "trigger_family": family,
                            "trigger_type": "post_sell_observation",
                            "reason": f"卖后观察窗口复核结果：{action_text}",
                            "should_call_ai": True,
                            "metrics": {
                                "source_event_type": source_event_type,
                                "nav": nav_point.nav,
                                "position_pct": snapshot.position_pct,
                                "core_sell_allowed": core_sell_allowed,
                            },
                        }
                    ],
                },
                snapshot=snapshot,
            )
        ]

    def _post_sell_recheck_result(
        self,
        source_event_type: str,
        index: int,
        bars: list[SignalBar],
        config: BacktestConfig,
        batches: list[HoldingBatch],
        nav: float,
        observation_day: int = 1,
        observation_days_total: int = 3,
    ) -> tuple[bool, str, bool]:
        if source_event_type in {"technical_breakdown", "stop_loss"}:
            fragile_batches = [
                batch for batch in self._batches_by_priority(batches, ["trial", "high_position", "confirmation"])
                if self._batch_breakdown_sell_allowed(batch, nav)
            ]
            if fragile_batches:
                labels = "、".join(self._batch_label(batch.batch_type) for batch in fragile_batches)
                return True, f"{labels}仍命中批次止损/破位条件，继续交给卖出执行", False
            if self._signal_still_broken(index, bars, config) and any(batch.batch_type == "core" for batch in batches):
                return True, "参考标的仍在关键EXPMA下方，脆弱批次已处理，继续处理半个核心仓", True
            return False, "参考标的未继续恶化，剩余仓位暂不继续卖出", False
        if source_event_type == "profit_drawdown":
            profit_batches = [
                batch for batch in self._batches_by_priority(batches, ["trial", "high_position", "confirmation"])
                if self._batch_take_profit_allowed(batch, nav)
            ]
            if profit_batches:
                labels = "、".join(self._batch_label(batch.batch_type) for batch in profit_batches)
                return True, f"{labels}仍命中批次止盈保护条件，继续交给卖出执行", False
            # 核心仓复核：观察期内只观察，不卖；直到最后一天才做最终决策
            is_last_observation_day = observation_day >= observation_days_total
            market_regime = self._get_market_regime(index, bars, config)
            core_batches = [
                batch for batch in self._batches_by_priority(batches, ["core"])
                if self._core_protection_tier(batch, self._batch_return_pct(batch, nav), market_regime) is not None
            ]
            if core_batches and is_last_observation_day and self._signal_still_broken(index, bars, config):
                return (
                    True,
                    f"观察期第{observation_day}天：核心仓仍处保护档位且参考标的仍破位，"
                    "观察期结束判定需要卖出剩余全部",
                    True,
                )
            if core_batches and not is_last_observation_day:
                return (
                    False,
                    f"观察期第{observation_day}天：核心仓在保护档位内，"
                    "继续观察趋势修复（观察期未结束）",
                    False,
                )
            return False, "脆弱批次已处理，核心仓趋势已修复或无保护档位，停止卖出", False
        return False, "上一轮卖出来源不明确，卖后观察只记录不继续执行", False

    def _signal_still_broken(self, index: int, bars: list[SignalBar], config: BacktestConfig) -> bool:
        if index < 0 or index >= len(bars):
            return False
        closes = [bar.close for bar in bars[: index + 1]]
        expma_values = expma(closes, config.expma_window)
        return closes[index] < expma_values[index]

    def _batch_cost_line_protection_triggered(self, batch: HoldingBatch, current_return_pct: float) -> bool:
        near_cost_line_pct = 1.5
        if batch.batch_type == "trial":
            return batch.peak_return_pct >= 3 and current_return_pct <= near_cost_line_pct
        if batch.batch_type == "high_position":
            return batch.peak_return_pct >= 5 and current_return_pct <= near_cost_line_pct
        if batch.batch_type == "confirmation":
            return batch.peak_return_pct >= 5 and current_return_pct <= near_cost_line_pct
        return False

    def _batch_core_cost_line_protection_triggered(
        self,
        batch: HoldingBatch,
        current_return_pct: float,
    ) -> bool:
        """Backward-compatible wrapper: core batch cost-line protection triggered."""
        return self._core_protection_tier(batch, current_return_pct, "neutral") is not None

    def _get_market_regime(self, index: int, bars: list[SignalBar], config: BacktestConfig) -> str:
        """基于 Prosperity score（宏观面）+ 技术指标（技术面）判断市场制度。

        返回值：
        - "bull": 牛市 (retention_rate=85%)
        - "neutral": 中立 (retention_rate=75%)
        - "bear": 熊市 (retention_rate=50%)

        组合逻辑：
        1. Prosperity score >= 7.5 → 宏观看好
        2. signal ETF 技术面 (MACD/均线) → 近期趋势
        """
        if index < 0 or index >= len(bars):
            return "neutral"

        # 宏观面：Prosperity score
        prosperity_score = config.prosperity.score
        is_macro_bullish = prosperity_score >= 7.5

        # 技术面：信号 ETF 的 MACD 和均线
        closes = [bar.close for bar in bars[: index + 1]]
        if len(closes) < 60:
            # 数据不足时用 Prosperity 判断
            return "bull" if is_macro_bullish else ("neutral" if prosperity_score >= 5.0 else "bear")

        # 计算 MACD（简化版：快线用 12 周期，慢线用 26 周期）
        try:
            macd_values = expma(closes, 12) if len(closes) >= 12 else [closes[-1]] * len(closes)
            signal_line = expma(closes, 26) if len(closes) >= 26 else [closes[-1]] * len(closes)
            macd = macd_values[-1] - signal_line[-1] if len(macd_values) > 0 and len(signal_line) > 0 else 0
            is_macd_bullish = macd > 0
        except Exception:
            is_macd_bullish = True

        # 计算均线
        ma_20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else closes[-1]
        ma_60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else closes[-1]
        current_price = closes[-1]
        is_price_above_ma = current_price > ma_20 > ma_60

        # 综合判断
        if is_macro_bullish and is_macd_bullish and is_price_above_ma:
            return "bull"      # 宏观+技术都看好
        elif is_macro_bullish or (is_macd_bullish and is_price_above_ma):
            return "neutral"   # 至少有一个看好
        else:
            return "bear"      # 宏观+技术都看空

    def _core_protection_tier(
        self,
        batch: HoldingBatch,
        current_return_pct: float,
        market_regime: str = "neutral",
    ) -> str | None:
        """核心仓分级保护档位判定（硬编码阈值 + 动态相对比例）。

        优先级：stop_loss > 硬编码阈值(tier1/tier2/tier3) > 动态阈值(tier2_dynamic)
        （选择触发时最保守的档位）

        返回触发的保护档位字符串：
        - "stop_loss": 亏损 >= -8%，清仓止损（最高优先级）
        - "tier1_high_peak_takeprofit": peak≥40% && drawdown≥10%
        - "tier2_mid_peak_takeprofit": peak≥15% && drawdown≥8%
        - "tier3_cost_line": peak≥10% && current≤1.5%
        - "tier2_dynamic": 相对回撤超过市场制度调整的阈值（最低优先级）
        - None: 未触发任何保护档位
        """
        if batch.batch_type != "core":
            return None

        # 止损保护（绝对止损，最高优先级）
        if batch.peak_return_pct >= 5.0 and current_return_pct <= -8.0:
            return "stop_loss"

        drawdown_from_peak = batch.peak_return_pct - current_return_pct

        # 档位 1：硬编码的高位止盈
        if batch.peak_return_pct >= 40.0 and drawdown_from_peak >= 10.0:
            return "tier1_high_peak_takeprofit"

        # 档位 2：硬编码的中位止盈
        if batch.peak_return_pct >= 15.0 and drawdown_from_peak >= 8.0:
            return "tier2_mid_peak_takeprofit"

        # 档位 3：硬编码的成本线保护
        if batch.peak_return_pct >= 10.0 and current_return_pct <= 1.5:
            return "tier3_cost_line"

        # 档位 4：动态止盈保护（基于市场制度调整，最低优先级）
        peak = batch.peak_return_pct
        retention_rates = {"bull": 0.85, "neutral": 0.75, "bear": 0.50}
        retention_rate = retention_rates.get(market_regime, 0.75)
        profit_threshold = peak * retention_rate

        # 当硬编码阈值都未触发时，使用相对比例判断
        # 只对 peak >= 3% 的仓位启用（小涨幅也要保护）
        if peak >= 3.0 and current_return_pct <= profit_threshold:
            return "tier2_dynamic"

        return None

    def _detect_buy_confirmation(
        self,
        original_candidate: BacktestEvent | None,
        index: int,
        bars: list[SignalBar],
        snapshot: PortfolioSnapshot,
        config: BacktestConfig,
    ) -> BacktestEvent | None:
        """观察期末检查买入条件是否仍满足，生成 buy_confirmation 事件。

        技能调用链（对应 batch-trading 系统）：
          1. batch-trading-market-regime  → 评估当前市场环境（bull/neutral/bear）
          2. batch-trading-buy-signal     → 结合市场环境判断信号是否有效
          3. batch-trading-batch-planner  → 确定建仓比例（在 _decide_buy 中执行）

        门槛规则：
          - bear 市场 + 弱买点(3/5)  → 阻断，等更明确信号
          - bear 市场 + 中等买点(4/5) → 允许但降级为弱买，50%→30%（在_decide_buy中处理）
          - neutral/bull + 任何信号    → 正常执行
        """
        if not original_candidate:
            return None

        original_details = original_candidate.details or {}
        buy_signal = original_details.get("buy_signal", {})
        original_passed = buy_signal.get("passed_count", 0)
        signal_level = buy_signal.get("signal_level", "")

        if original_passed < 3:
            return None

        # ── 调用 batch-trading-market-regime ──────────────────────────────
        # 在 backtest 中由 _get_market_regime() 实现：
        #   宏观面：Prosperity score（景气度）
        #   技术面：signal ETF 的 MACD + MA20/MA60
        market_regime = self._get_market_regime(index, bars, config)
        skill_trace = [
            {
                "skill": "batch-trading-market-regime",
                "result": market_regime,
                "inputs": {
                    "prosperity_score": config.prosperity.score,
                    "signal_etf": config.signal_code,
                },
            }
        ]

        # ── 调用 batch-trading-buy-signal：market-regime 门槛 ────────────
        # bear 市场下弱买点直接阻断——市场环境不支持轻仓试错
        if market_regime == "bear" and signal_level == "weak_buy":
            skill_trace.append({
                "skill": "batch-trading-buy-signal",
                "result": "blocked",
                "reason": f"market_regime={market_regime}，弱买点在熊市环境下不确认建仓，等待market_regime回到neutral/bull",
            })
            return None     # 不生成 buy_confirmation，观察期自然结束

        skill_trace.append({
            "skill": "batch-trading-buy-signal",
            "result": "confirmed",
            "reason": f"market_regime={market_regime}，{original_passed}/5维度通过，确认建仓",
        })

        event_date = bars[index].date if index < len(bars) else original_candidate.date
        return BacktestEvent(
            event_type="buy_confirmation",
            date=event_date,
            reason=(
                f"买入观察期结束，{original_passed}/5维度通过，"
                f"market_regime={market_regime}，确认执行建仓"
            ),
            details={
                "original_buy_signal": buy_signal,
                "observation_days": 2,
                "trigger_signals": original_details.get("trigger_signals", []),
                # 市场环境透传给 _decide_buy（batch-trading-batch-planner）
                "market_regime": market_regime,
                "skill_trace": skill_trace,
            },
            snapshot=snapshot,
        )

    def _merge_batch_events(
        self,
        detected_events: list[BacktestEvent],
        batch_events: list[BacktestEvent],
    ) -> list[BacktestEvent]:
        if not batch_events:
            return detected_events
        first_sell_index = next(
            (
                index for index, event in enumerate(detected_events)
                if event.event_type in {"profit_drawdown", "technical_breakdown"}
            ),
            len(detected_events),
        )
        # 若 batch_events 中有核心仓保护，应移除 detected_events 中的通常 profit_drawdown，
        # 避免同一天对核心仓重复卖出（已由 batch_events 中的核心仓保护处理）
        has_core_protection = any(
            event.details.get("batch_protection") == "core_cost_line"
            for event in batch_events
        )
        if has_core_protection:
            detected_events = [
                event for event in detected_events
                if not (
                    event.event_type == "profit_drawdown"
                    and event.details.get("batch_protection") is None
                )
            ]
            # 重新计算 first_sell_index
            first_sell_index = next(
                (
                    index for index, event in enumerate(detected_events)
                    if event.event_type in {"profit_drawdown", "technical_breakdown"}
                ),
                len(detected_events),
            )
        return detected_events[:first_sell_index] + batch_events + detected_events[first_sell_index:]

    def _batch_values_by_type(self, batches: list[HoldingBatch], nav: float) -> dict[str, float]:
        values: dict[str, float] = {}
        for batch in batches:
            values[batch.batch_type] = values.get(batch.batch_type, 0.0) + batch.shares * nav
        return values

    def _total_shares(self, batches: list[HoldingBatch]) -> float:
        return sum(batch.shares for batch in batches)

    def _calculate_metrics(
        self,
        config: BacktestConfig,
        equity_curve: list[PortfolioSnapshot],
        trades: list[TradeRecord],
        peak_equity: float,
    ) -> BacktestMetrics:
        final_equity = equity_curve[-1].equity
        total_return_pct = (final_equity / config.initial_cash - 1) * 100
        days = max((equity_curve[-1].date - equity_curve[0].date).days, 1)
        annual_return_pct = (pow(final_equity / config.initial_cash, 365 / days) - 1) * 100
        max_drawdown_pct = 0.0
        running_peak = equity_curve[0].equity
        for snapshot in equity_curve:
            running_peak = max(running_peak, snapshot.equity)
            if running_peak > 0:
                drawdown = (snapshot.equity / running_peak - 1) * 100
                max_drawdown_pct = min(max_drawdown_pct, drawdown)
        return BacktestMetrics(
            total_return_pct=total_return_pct,
            annual_return_pct=annual_return_pct,
            max_drawdown_pct=max_drawdown_pct,
            trade_count=len(trades),
            final_equity=final_equity,
        )
