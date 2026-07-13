import apiClient from './client'
import type {
  ChatRequest,
  ChatResponse,
  DecisionCard,
  Evidence,
  GuardianRun,
  GuardianSlot,
  MonitoringAlert,
} from '@/types/agent'

/** Chat with the advisor agent. */
async function chat(
  message: string,
  opts?: {
    history?: { role: string; content: string }[]
    session_id?: string | null
  },
) {
  const body: ChatRequest = {
    message,
    history: opts?.history ?? [],
    session_id: opts?.session_id ?? undefined,
  }
  return apiClient.post<ChatResponse>('/agent/chat', body)
}

/** Fetch one evidence snapshot by id (click-through). */
async function getEvidence(evId: string) {
  return apiClient.get<Evidence>(`/agent/evidence/${evId}`)
}

/** All evidence collected in a session. */
async function listSessionEvidence(sessionId: string, onlyFresh = false) {
  return apiClient.get<{ session_id: string; count: number; items: Evidence[] }>(
    `/agent/sessions/${sessionId}/evidence`,
    { params: { only_fresh: onlyFresh, limit: 100 } },
  )
}

/** All decision cards emitted in a session. */
async function listSessionDecisions(sessionId: string, limit = 20) {
  return apiClient.get<{ session_id: string; count: number; items: DecisionCard[] }>(
    `/agent/sessions/${sessionId}/decisions`,
    { params: { limit } },
  )
}

/** Fetch one card by id. */
async function getDecision(decisionId: string) {
  return apiClient.get<{ decision_id: string; card: DecisionCard }>(
    `/agent/decisions/${decisionId}`,
  )
}

/** Mark accepted / ignored / partial. */
async function markDecisionAction(decisionId: string, action: 'accepted' | 'ignored' | 'partial') {
  return apiClient.post<{
    decision_id: string
    user_action: string
    user_action_at: string | null
  }>(`/agent/decisions/${decisionId}/action`, { action })
}

/** Synthesized alerts for a decision card. */
async function listMonitoringAlerts(decisionId: string) {
  return apiClient.get<{ decision_id: string; count: number; items: MonitoringAlert[] }>(
    `/agent/decisions/${decisionId}/monitoring-alerts`,
  )
}

/** Disable all synthesized alerts for a decision card in one click. */
async function disableMonitoringAlerts(decisionId: string) {
  return apiClient.post<{ decision_id: string; disabled_count: number }>(
    `/agent/decisions/${decisionId}/monitoring-alerts/disable`,
  )
}

/** Run a Guardian scan on demand (usually slot="manual"). */
async function runGuardian(slot: GuardianSlot = 'manual') {
  return apiClient.post<GuardianRun>(`/agent/guardian/run`, null, { params: { slot } })
}

/** List recent Guardian scans, newest first. */
async function listGuardianRuns(limit = 10) {
  return apiClient.get<{ count: number; items: GuardianRun[] }>(
    `/agent/guardian/runs`,
    { params: { limit } },
  )
}

/** Fetch one Guardian scan by session id. */
async function getGuardianRun(sessionId: string) {
  return apiClient.get<GuardianRun>(`/agent/guardian/${sessionId}`)
}

/** Manually trigger the 7d/30d outcome tracker (cron runs at 21:00). */
async function updateOutcomes() {
  return apiClient.post<{
    seven_day_updated: number
    thirty_day_updated: number
    skipped_no_snapshot: number
    skipped_no_price: number
    updated_ids: string[]
  }>(`/agent/guardian/outcome/update`)
}

/** Hit-rate summary. */
async function getOutcomeSummary(days = 90) {
  return apiClient.get(`/agent/guardian/outcome/summary`, { params: { days } })
}

export const agentApi = {
  chat,
  getEvidence,
  listSessionEvidence,
  listSessionDecisions,
  getDecision,
  markDecisionAction,
  listMonitoringAlerts,
  disableMonitoringAlerts,
  runGuardian,
  listGuardianRuns,
  getGuardianRun,
  updateOutcomes,
  getOutcomeSummary,
}
