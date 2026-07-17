export type PresetId = 'daily_action' | 'discovery' | 'risk_scan' | 'market_read'

export type MessageKind =
  | 'text'
  | 'routing'
  | 'specialist_memo'
  | 'amount_suggestion'
  | 'chair_summary'
  | 'clarification'
  | 'error'

export interface TurnRequest {
  text?: string | null
  preset_id?: PresetId | null
}

export interface ResolvedFund {
  code: string
  name: string
  matched_from: string
}

export interface Ambiguity {
  hint: string
  candidates: ResolvedFund[]
}

export interface AmountSuggestion {
  action: 'buy' | 'sell'
  fund_code: string
  minimum: number
  maximum: number
  currency: string
  basis: string
  caveats: string[]
}

export interface MessagePayloadEnvelope {
  turn_id: string
  kind: MessageKind
  payload: Record<string, unknown>
}

export interface ConversationMessage {
  id: number
  sender_role: string
  content: string
  payload: MessagePayloadEnvelope
  created_at: string
}

export interface ConversationCreateResponse {
  conversation_id: string
}

export interface AskResponse {
  turn_id: string
}

export interface MessageListResponse {
  messages: ConversationMessage[]
  next_cursor: number
}
