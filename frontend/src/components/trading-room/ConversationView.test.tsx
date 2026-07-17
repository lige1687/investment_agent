import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import ConversationView from './ConversationView'
import { conversationApi } from '@/api/conversation'


vi.mock('@/api/conversation')


describe('ConversationView', () => {
  beforeEach(() => {
    vi.mocked(conversationApi.create).mockResolvedValue({ conversation_id: 'c1' })
    vi.mocked(conversationApi.ask).mockResolvedValue({ turn_id: 't1' })
    vi.mocked(conversationApi.listMessages).mockResolvedValue({
      messages: [], next_cursor: 0,
    })
  })

  it('shows preset bar on initial empty state and can trigger a preset ask', async () => {
    render(<ConversationView />)
    await waitFor(() => expect(conversationApi.create).toHaveBeenCalled())

    const btn = await screen.findByRole('button', { name: /风险扫描/ })
    fireEvent.click(btn)
    expect(conversationApi.ask).toHaveBeenCalledWith('c1', { preset_id: 'risk_scan' })
  })

  it('renders messages as they arrive from poll', async () => {
    vi.mocked(conversationApi.listMessages).mockResolvedValueOnce({
      messages: [{
        id: 1, sender_role: 'user', content: '要不要减',
        payload: { turn_id: 't1', kind: 'text', payload: { text: '要不要减' } },
        created_at: new Date().toISOString(),
      }],
      next_cursor: 1,
    }).mockResolvedValueOnce({
      messages: [{
        id: 2, sender_role: 'chair', content: 'x',
        payload: { turn_id: 't1', kind: 'chair_summary',
                   payload: { text: '综合结论：可减仓 1500-2500 元', data_caveats: [] } },
        created_at: new Date().toISOString(),
      }],
      next_cursor: 2,
    }).mockResolvedValue({ messages: [], next_cursor: 2 })

    render(<ConversationView />)
    await waitFor(() => expect(conversationApi.create).toHaveBeenCalled())
    // 触发一次 ask 才会开始 poll
    fireEvent.click(await screen.findByRole('button', { name: /今日操作/ }))
    await waitFor(() => expect(screen.getByTestId('bubble-text')).toBeInTheDocument(), { timeout: 3000 })
    await waitFor(() => expect(screen.getByTestId('bubble-chair_summary'))
      .toHaveTextContent('可减仓 1500-2500'), { timeout: 3000 })
  })
})
