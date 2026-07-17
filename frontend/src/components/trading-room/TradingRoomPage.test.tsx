import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import TradingRoomPage from './TradingRoomPage'
import { portfolioApi } from '@/api/portfolio'
import { conversationApi } from '@/api/conversation'


vi.mock('@/api/portfolio')
vi.mock('@/api/conversation')


describe('TradingRoomPage', () => {
  it('mounts SyncedAccountSummary and ConversationView', async () => {
    vi.mocked(portfolioApi.getPortfolio).mockResolvedValue({
      data: { connected: true, positions: [], total_value: 0, synced_at: null },
    } as any)
    vi.mocked(conversationApi.create).mockResolvedValue({ conversation_id: 'c1' })
    vi.mocked(conversationApi.listMessages).mockResolvedValue({
      messages: [], next_cursor: 0,
    })
    render(<TradingRoomPage />)
    await waitFor(() => expect(portfolioApi.getPortfolio).toHaveBeenCalled())
    await waitFor(() => expect(conversationApi.create).toHaveBeenCalled())
    expect(await screen.findByRole('button', { name: /今日操作/ })).toBeInTheDocument()
  })
})
