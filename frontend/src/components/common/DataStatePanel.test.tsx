import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import DataStatePanel from './DataStatePanel'
import DemoDataBanner from './DemoDataBanner'
import type { MarketDataMeta } from '@/types/dataTrust'

const meta: MarketDataMeta = {
  source: 'westock',
  fetchedAt: '2026-07-13T14:30:00+08:00',
  mode: 'live',
  status: 'ok',
  stale: false,
  isMock: false,
  message: null,
}

describe('DataStatePanel', () => {
  it('distinguishes loading, empty, and invalid data', () => {
    const { rerender } = render(<DataStatePanel state="loading" meta={meta}>content</DataStatePanel>)
    expect(screen.getByText('正在获取数据')).toBeInTheDocument()

    rerender(<DataStatePanel state="empty" meta={{ ...meta, status: 'empty' }}>content</DataStatePanel>)
    expect(screen.getByText('数据源正常，当前无数据')).toBeInTheDocument()

    rerender(<DataStatePanel state="invalid" meta={{ ...meta, status: 'invalid' }}>content</DataStatePanel>)
    expect(screen.getByText('数据格式异常，本次不用于决策')).toBeInTheDocument()
  })

  it('offers retry when the source is unavailable', () => {
    const retry = vi.fn()
    render(
      <DataStatePanel state="unavailable" meta={{ ...meta, status: 'unavailable' }} onRetry={retry}>
        content
      </DataStatePanel>,
    )

    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(retry).toHaveBeenCalledOnce()
  })

  it('shows stale and demo warnings while retaining visible content', () => {
    const { rerender } = render(
      <DataStatePanel state="stale" meta={{ ...meta, stale: true }}>
        <span>行情内容</span>
      </DataStatePanel>,
    )
    expect(screen.getByText(/数据已过期/)).toBeInTheDocument()
    expect(screen.getByText('行情内容')).toBeInTheDocument()

    rerender(
      <DataStatePanel state="demo" meta={{ ...meta, mode: 'demo', isMock: true }}>
        <span>行情内容</span>
      </DataStatePanel>,
    )
    expect(screen.getByText('演示数据，不可用于真实交易')).toBeInTheDocument()
    expect(screen.getByText('行情内容')).toBeInTheDocument()
  })
})

it('renders a persistent demo banner', () => {
  render(<DemoDataBanner />)
  expect(screen.getByRole('alert')).toHaveTextContent('演示数据，不可用于真实交易')
})

