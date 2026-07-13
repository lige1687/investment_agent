export type DataConfidence = 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN'
export type ActionClass = 'IMMEDIATE' | 'CONDITIONAL' | 'WATCH' | 'NO_ACTION'

export interface TargetAllocation {
  scope: 'theme' | 'fund'
  key: string
  target_pct: number
}

export interface TradingPolicy {
  template_id: string
  display_name: string
  buy_obvious_threshold: number
  conditional_buy_min: number
  account_drawdown_warning_pct: number
  account_drawdown_derisk_pct: number
  account_drawdown_protection_pct: number
  percentage_stop_enabled: boolean
  percentage_stop_pct: number | null
  stop_priority: string[]
  trend_break: Record<string, number | boolean>
  version_id: string
  created_at: string
  target_allocations: TargetAllocation[]
  ready: boolean
  missing_confirmations: string[]
}

export interface CriticalDataInput {
  key: string
  source: string
  as_of: string | null
  confidence: DataConfidence
  is_mock: boolean
  stale: boolean
}

export interface TradingContextSnapshot {
  as_of: string
  data_mode: 'live' | 'demo'
  market_dates: Record<string, string>
  positions: Record<string, unknown>[]
  cash: number
  equity: number
  peak_equity: number
  pending_orders: Record<string, unknown>[]
  themes: Record<string, unknown>
  funds: Record<string, unknown>
  policy_version_id: string
  skill_versions: Record<string, string>
  critical_inputs: CriticalDataInput[]
  status: 'complete' | 'incomplete'
  formally_actionable: boolean
  blockers: string[]
  context_hash: string
}

export interface DecisionRange {
  minimum: number
  maximum: number
  currency?: 'CNY'
}

export interface SpecialistMemo {
  role: string
  state: 'ready' | 'completed' | 'unavailable'
  memo: Record<string, unknown> & {
    summary?: string
    evidence_refs?: string[]
    confidence?: DataConfidence
    exposure_confidence?: DataConfidence
    findings?: Array<Record<string, unknown>>
  }
  skill_versions: Record<string, string>
  created_at: string
}

export interface FinalDecision {
  action_class: ActionClass
  suggested_range: DecisionRange
  guarded_range: DecisionRange | null
  immediately_executable: boolean
  reasons: string[]
  applied_caps: string[]
  score: number
  selected_amount: number | null
  policy_version_id: string
  context_hash: string
  manual_execution_only: boolean
}

export interface TradingRoomSession {
  session_id: string
  status: string
  policy_version_id: string
  context: TradingContextSnapshot
  specialist_memos: SpecialistMemo[]
  messages: Array<{
    id: number
    sender_role: string
    content: string
    payload: Record<string, unknown>
    created_at: string
  }>
  exposure_snapshots: Array<Record<string, unknown>>
  trade_status_snapshots: Array<Record<string, unknown>>
  policy_proposals: Array<Record<string, unknown>>
  final_decision: FinalDecision | null
  feedback_state: string | null
  selected_amount: number | null
  feedback_note: string | null
  created_at: string
  manual_execution_only: boolean
}

export interface SessionCreatePayload {
  policy_version_id: string
  as_of: string
  data_mode: 'live' | 'demo'
  market_dates: Record<string, string>
  positions: Record<string, unknown>[]
  cash: number
  equity: number
  peak_equity: number
  pending_orders: Record<string, unknown>[]
  themes: Record<string, unknown>
  funds: Record<string, unknown>
  skill_versions: Record<string, string>
  critical_inputs: CriticalDataInput[]
  exposure_snapshots?: Array<Record<string, unknown>>
  trade_status_snapshots?: Array<Record<string, unknown>>
  execution_channel?: string
  start_discussion: boolean
}
