import apiClient from './client'
import type {
  ExecutionFundingInput,
  FinalDecision,
  SessionCreatePayload,
  TargetAllocation,
  TradingPolicy,
  TradingRoomSession,
} from '@/types/tradingRoom'

export const tradingRoomApi = {
  getTemplates: async () =>
    (await apiClient.get<TradingPolicy[]>('/agent/trading-policy/templates')).data,

  getCurrentPolicy: async () =>
    (await apiClient.get<TradingPolicy>('/agent/trading-policy')).data,

  importPolicy: async (payload: {
    template_id: string
    target_allocations: TargetAllocation[]
  }) => (await apiClient.post<TradingPolicy>('/agent/trading-policy/import', payload)).data,

  createSession: async (payload: SessionCreatePayload) =>
    (await apiClient.post<TradingRoomSession>(
      '/agent/trading-room/sessions', payload, { timeout: 300_000 },
    )).data,

  preflight: async (payload: {
    fund_code: string
    fund_name: string
    share_class: string
    customer_scope: 'retail' | 'institutional'
    channel: string
    channel_confirmed: boolean
  }) => (await apiClient.post<Record<string, unknown>>('/agent/trading-room/preflight', payload)).data,

  finalizeSession: async (sessionId: string, payload: {
    score: number
    has_veto: boolean
    suggested_range: { minimum: number; maximum: number; currency?: string }
    preflight: Record<string, unknown>
    execution_funding: ExecutionFundingInput | null
    selected_amount?: number
  }) =>
    (await apiClient.post<{ session_id: string; decision: FinalDecision }>(
      `/agent/trading-room/sessions/${sessionId}/finalize`, payload,
    )).data,

  getLatestFunding: async () =>
    (await apiClient.get<{ available_cash: number | null; confirmed_at: string | null }>(
      '/agent/trading-room/funding/latest',
    )).data,

  getSession: async (sessionId: string) =>
    (await apiClient.get<TradingRoomSession>(`/agent/trading-room/sessions/${sessionId}`)).data,

  addMessage: async (sessionId: string, content: string, payload: Record<string, unknown> = {}) =>
    (await apiClient.post(`/agent/trading-room/sessions/${sessionId}/messages`, { content, payload })).data,

  recordAction: async (
    sessionId: string,
    payload: { state: string; selected_amount?: number; note?: string },
  ) => (await apiClient.post(`/agent/trading-room/sessions/${sessionId}/actions`, payload)).data,
}
