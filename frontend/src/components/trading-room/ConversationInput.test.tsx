import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import ConversationInput from './ConversationInput'

describe('ConversationInput', () => {
  it('submits text on send click and clears input', () => {
    const onSubmit = vi.fn()
    render(<ConversationInput onSubmit={onSubmit} />)
    const textarea = screen.getByRole('textbox')
    fireEvent.change(textarea, { target: { value: '信息产业那只' } })
    fireEvent.click(screen.getByRole('button', { name: /发送/ }))
    expect(onSubmit).toHaveBeenCalledWith('信息产业那只')
    expect(textarea).toHaveValue('')
  })

  it('does nothing on empty submit', () => {
    const onSubmit = vi.fn()
    render(<ConversationInput onSubmit={onSubmit} />)
    fireEvent.click(screen.getByRole('button', { name: /发送/ }))
    expect(onSubmit).not.toHaveBeenCalled()
  })
})
