export interface BacktestPreset {
  preset_id: string
  title: string
  fund_code: string
  fund_name: string
  signal_symbol: string
  signal_name: string
  signal_provider: string
  description: string
}

export interface PortfolioSnapshot {
  date: string
  cash: number
  shares: number
  nav: number
  equity: number
  position_pct: number
  cumulative_return_pct: number
  peak_return_pct: number
}

export interface SignalBar {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  amount?: number
}

export interface BacktestTrade {
  date: string
  action: 'buy' | 'sell'
  nav: number
  shares: number
  cash_delta: number
  fee: number
  reason: string
  event_type: string
  batch_type?: string
  batch_cost_nav?: number
  batch_return_pct?: number
  batch_peak_return_pct?: number
}

export interface DimensionCheck {
  name: string
  passed: boolean
  reason: string
  details: Record<string, unknown>
}

export interface BuySignalDetails {
  signal_level: string
  recommended_action: string
  passed_count: number
  account_allowed: boolean
  account_reasons: string[]
  dimensions: DimensionCheck[]
}

export interface TriggerSignal {
  priority: 'P0' | 'P1' | 'P2' | 'P3' | 'P4'
  trigger_family: string
  trigger_type: string
  reason: string
  metrics: Record<string, unknown>
  should_call_ai: boolean
}

export interface TradeAnalysisReport {
  current_conclusion: {
    signal_level: string
    suggested_action: string
    risk_control_passed: boolean
    decision_reason: string
  }
  account_check: {
    current_total_position_pct: number
    current_total_position_safe: boolean
    current_sector_exposure_too_high: boolean
    would_break_single_or_sector_limit: boolean
    risk_control_passed: boolean
    reasons: string[]
  }
  buy_signal_checks: Record<string, {
    passed: boolean
    reason: string
    details?: Record<string, unknown>
  }>
  trigger_conditions: {
    event: string
    decision: string
    missing_conditions: string[]
    upgrade_conditions: string[]
    raw_details: Record<string, unknown>
  }
  risk_warnings: string[]
  one_sentence: string
}

export interface BatchTradingSkillRoute {
  system: 'batch-trading'
  system_name: string
  classified_intent: string
  highest_priority: string
  immediate_vetoes: Array<{
    rule: string
    blocking: boolean
    reason: string
  }>
  required_skill_order: string[]
  direct_answer_allowed: boolean
  missing_information: string[]
  priority_note: string
  next_step: {
    invoke: string
    reason: string
  }
}

export interface BacktestEvent {
  date: string
  event_type: string
  reason: string
  details: {
    buy_signal?: BuySignalDetails
    trigger_signals?: TriggerSignal[]
    [key: string]: unknown
  }
  decision: {
    action: string
    reason: string
    target_position_delta_pct: number
    ratio_of_position: number
    observe_days: number
  }
  analysis_report?: TradeAnalysisReport
  skill_route?: BatchTradingSkillRoute
  audit?: {
    final_decider: string
    final_result: string
    why_no_trade: string
    used_skills: string[]
  }
}

export interface BacktestMetrics {
  total_return_pct: number
  annual_return_pct: number
  max_drawdown_pct: number
  trade_count: number
  final_equity: number
}

export interface BacktestResponse {
  config: Record<string, unknown>
  metrics: BacktestMetrics
  equity_curve: PortfolioSnapshot[]
  signal_bars: SignalBar[]
  trades: BacktestTrade[]
  events: BacktestEvent[]
  strategy_profile: {
    source: string
    recognized_rules: string[]
    notes: string[]
  }
  disclaimer: string
}

export interface RunPresetPayload {
  preset_id: string
  start_date: string
  end_date: string
  initial_cash: number
  initial_position_pct: number
  target_position_pct: number
  fund_nav_page_size: number
  signal_limit: number
  current_correlated_growth_exposure_pct?: number
  strategy_text?: string
  use_ai_strategy_compiler?: boolean
  test_mode?: boolean
}
