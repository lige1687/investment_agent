import apiClient from './client'
import type {
  AskResponse,
  ConversationCreateResponse,
  MessageListResponse,
  TurnRequest,
} from '@/types/conversation'

const BASE = '/agent/trading-room'

export const conversationApi = {
  create: async () =>
    (await apiClient.post<ConversationCreateResponse>(`${BASE}/conversations`)).data,

  ask: async (id: string, req: TurnRequest) =>
    (await apiClient.post<AskResponse>(`${BASE}/conversations/${id}/ask`, req)).data,

  listMessages: async (id: string, after = 0) =>
    (await apiClient.get<MessageListResponse>(
      `${BASE}/conversations/${id}/messages`,
      { params: { after } },
    )).data,
}
