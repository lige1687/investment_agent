import { useState } from 'react'
import { Button, Input, Space } from 'antd'
import { SendOutlined } from '@ant-design/icons'

interface Props {
  onSubmit: (text: string) => void
  disabled?: boolean
  placeholder?: string
}

export default function ConversationInput({ onSubmit, disabled, placeholder }: Props) {
  const [text, setText] = useState('')

  const submit = () => {
    const trimmed = text.trim()
    if (!trimmed) return
    onSubmit(trimmed)
    setText('')
  }

  return (
    <Space.Compact style={{ width: '100%' }}>
      <Input.TextArea
        rows={2}
        value={text}
        disabled={disabled}
        placeholder={placeholder ?? '直接说基金名就行，如"信息产业那只要不要减"'}
        onChange={e => setText(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            submit()
          }
        }}
      />
      <Button
        type="primary"
        icon={<SendOutlined />}
        disabled={disabled}
        onClick={submit}
      >
        发送
      </Button>
    </Space.Compact>
  )
}
