import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import MessageBubble from './MessageBubble'
import type { ConversationMessage } from '@/types/conversation'


const base = (overrides: Partial<ConversationMessage>): ConversationMessage => ({
  id: 1,
  sender_role: 'system',
  content: '',
  payload: { turn_id: 't1', kind: 'text', payload: {} },
  created_at: new Date().toISOString(),
  ...overrides,
})

describe('MessageBubble', () => {
  it('renders text kind', () => {
    render(<MessageBubble msg={base({
      sender_role: 'user',
      content: '要不要减仓',
      payload: { turn_id: 't1', kind: 'text', payload: { text: '要不要减仓' } },
    })} />)
    expect(screen.getByTestId('bubble-text')).toHaveTextContent('要不要减仓')
  })

  it('renders routing kind with participants', () => {
    render(<MessageBubble msg={base({
      content: 'x',
      payload: {
        turn_id: 't1', kind: 'routing',
        payload: {
          participants: ['sell_protection', 'portfolio_risk'],
          resolved_funds: [{ code: '001513', name: '易方达信息产业混合A', matched_from: '信息产业' }],
        },
      },
    })} />)
    const el = screen.getByTestId('bubble-routing')
    expect(el).toHaveTextContent('卖出保护')
    expect(el).toHaveTextContent('易方达信息产业混合A')
  })

  it('renders chair_summary with data caveats', () => {
    render(<MessageBubble msg={base({
      sender_role: 'chair',
      content: '综合意见',
      payload: {
        turn_id: 't1', kind: 'chair_summary',
        payload: { text: '综合意见：可小幅加仓 1000-3000 元。',
                   data_caveats: ['持仓数据同步于今早 9:31'] },
      },
    })} />)
    const el = screen.getByTestId('bubble-chair_summary')
    expect(el).toHaveTextContent('可小幅加仓')
    expect(el).toHaveTextContent('9:31')
  })

  it('renders clarification with candidates', () => {
    render(<MessageBubble msg={base({
      payload: {
        turn_id: 't1', kind: 'clarification',
        payload: {
          ambiguities: [{
            hint: 'A/C 需澄清',
            candidates: [
              { code: '001513', name: '易方达信息产业混合A', matched_from: '信息产业' },
              { code: '001514', name: '易方达信息产业混合C', matched_from: '信息产业' },
            ],
          }],
        },
      },
    })} />)
    const el = screen.getByTestId('bubble-clarification')
    expect(el).toHaveTextContent('A/C 需澄清')
    expect(el).toHaveTextContent('001513')
    expect(el).toHaveTextContent('001514')
  })

  it('renders error kind', () => {
    render(<MessageBubble msg={base({
      payload: { turn_id: 't1', kind: 'error', payload: { detail: 'router failed' } },
    })} />)
    expect(screen.getByTestId('bubble-error')).toHaveTextContent('router failed')
  })
})
