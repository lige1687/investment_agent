import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import AppErrorBoundary from './AppErrorBoundary'

function BrokenChild(): never {
  throw new Error('secret request body')
}

describe('AppErrorBoundary', () => {
  it('replaces a crashed subtree with a safe recovery view', () => {
    const reload = vi.fn()
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    render(
      <AppErrorBoundary onReload={reload}>
        <BrokenChild />
      </AppErrorBoundary>,
    )

    expect(screen.getByText('页面模块出现异常')).toBeInTheDocument()
    expect(screen.queryByText('secret request body')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重新加载' }))
    expect(reload).toHaveBeenCalledOnce()
    consoleError.mockRestore()
  })
})

