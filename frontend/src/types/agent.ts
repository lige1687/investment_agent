/* Agent chat + decision card types — mirrors backend Pydantic schema. */

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  toolCalls?: ToolCall[]
  decisionCard?: DecisionCard | null
  evidenceRefs?: string[]
  storedCardId?: number | null
  timestamp: string
  meta?: {
    turns?: number
    stop_reason?: string
    provider?: string
    model?: string
    input_tokens?: number
    output_tokens?: number
    fallback?: boolean
  }
}

export interface ToolCall {
  name: string
  arguments?: Record<string, any>
  evidence_id?: string
  result_preview?: string
  turn?: number
  // Legacy field the older UI expected:
  tool?: string
  result?: any
}

export interface ChatRequest {
  message: string
  history?: { role: string; content: string }[]
  session_id?: string | null
}

export interface ChatResponse {
  answer: string
  decision_card: DecisionCard | null
  stored_card_id: number | null
  evidence_refs: string[]
  tool_calls: ToolCall[]
  session_id: string
  fallback: boolean
  turns?: number | null
  stop_reason?: string | null
  usage?: {
    input_tokens: number
    output_tokens: number
    model: string
    provider: string
  } | null
  error?: string | null
}

// ── Decision card ──

export type DimensionKey =
  | 'technical'
  | 'capital'
  | 'macro'
  | 'news'
  | 'financial'
  | 'consensus'

export interface Dimension {
  key: DimensionKey
  score: number
  signal: string
  evidence_ref?: string | null
}

export interface Conflict {
  between: DimensionKey[]
  note: string
}

export type PortfolioRole = 'COMPLEMENT' | 'STRENGTHEN' | 'DUPLICATE' | 'NEW'

export interface PortfolioContext {
  overlap_with_holdings?: string[]
  role?: PortfolioRole
  warning?: string | null
}

export interface EntryPlan {
  style?: string
  batches?: number | null
  trigger?: string | null
}

export interface StopLoss {
  type: string
  value: string
}

export interface TakeProfitLevel {
  at: string
  action: string
}

export interface ExecutionPlan {
  position_size_pct?: string | null
  entry?: EntryPlan | null
  stop_loss?: StopLoss | null
  take_profit?: { levels: TakeProfitLevel[] } | null
}

export type DecisionType =
  | 'BUY_CANDIDATE'
  | 'SELL_ALERT'
  | 'REBALANCE'
  | 'WATCH'
  | 'NONE'

export type ActionVerb =
  | 'BUY'
  | 'ADD'
  | 'HOLD'
  | 'REDUCE'
  | 'SELL'
  | 'WATCH'
  | 'AVOID'

export type Urgency = 'LOW' | 'MEDIUM' | 'HIGH'

export type TargetKind = 'fund' | 'stock' | 'etf' | 'sector' | 'index' | 'portfolio'

export interface DecisionCard {
  decision_id: string
  created_at: string
  agent: string
  session_id?: string | null
  type: DecisionType
  target: {
    kind: TargetKind
    code?: string | null
    name: string
  }
  action: {
    verb: ActionVerb
    confidence: number
    urgency: Urgency
  }
  headline?: string | null
  summary?: string | null
  dimensions: Dimension[]
  conflicts: Conflict[]
  portfolio_context?: PortfolioContext | null
  execution_plan?: ExecutionPlan | null
  monitoring: string[]
  evidence_refs: string[]
  disclaimer: string
}

// ── Evidence ──

export interface Evidence {
  ev_id: string
  session_id: string
  agent: string
  source: string
  query: Record<string, any>
  data: string
  summary?: string | null
  fetched_at: string
  ttl_seconds: number
  is_fresh: boolean
}

// ── Monitoring alerts (synthesized from decision.monitoring[]) ──

export interface MonitoringAlert {
  id: number
  symbol: string
  alert_type: string
  threshold: number
  direction?: string | null
  enabled: boolean
  cooldown_min: number
  note?: string | null
  source: string
  source_ref?: string | null
  created_at?: string | null
}

// ── Guardian ──

export type GuardianSlot = 'midday' | 'close' | 'manual'
export type AlertSeverity = 'LOW' | 'MEDIUM' | 'HIGH'
export type AlertTrigger =
  | 'LOSS_DEEP'
  | 'LOSS_EXPANDING'
  | 'CONCENTRATION_HIGH'
  | 'TOP3_CONCENTRATION'
  | 'OVERLAP_DUPLICATE'
  | 'PROFIT_TAKE'

export interface HoldingAlert {
  code: string
  name: string
  trigger: AlertTrigger
  severity: AlertSeverity
  note: string
  metric_value?: number | null
  threshold?: number | null
}

export interface GuardianRun {
  session_id: string
  slot: GuardianSlot
  started_at: string
  finished_at?: string | null
  alert_count: number
  decision_count: number
  llm_used: boolean
  pushed_to_feishu: boolean
  error?: string | null
  briefing_text?: string | null
  portfolio_snapshot: Record<string, any>
  market_snapshot: Record<string, any>
  alerts: HoldingAlert[]
  decision_ids: string[]
}
