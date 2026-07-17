import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import QuickActionBar from './QuickActionBar'

describe('QuickActionBar', () => {
  it('renders 4 preset buttons', () => {
    render(<QuickActionBar onPreset={vi.fn()} />)
    expect(screen.getByRole('button', { name: /今日操作/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /机会发现/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /风险扫描/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /市场解读/ })).toBeInTheDocument()
  })

  it('calls onPreset with correct id', () => {
    const onPreset = vi.fn()
    render(<QuickActionBar onPreset={onPreset} />)
    fireEvent.click(screen.getByRole('button', { name: /风险扫描/ }))
    expect(onPreset).toHaveBeenCalledWith('risk_scan')
  })

  it('disables all buttons when disabled prop is true', () => {
    render(<QuickActionBar onPreset={vi.fn()} disabled />)
    screen.getAllByRole('button').forEach(btn => {
      expect(btn).toBeDisabled()
    })
  })
})
