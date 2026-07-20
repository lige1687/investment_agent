import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Card, Empty, Space, Spin, Typography } from 'antd'

import { conversationApi } from '@/api/conversation'
import type { ConversationMessage, PresetId, TurnRequest } from '@/types/conversation'
import ConversationInput from './ConversationInput'
import MessageBubble from './MessageBubble'
import QuickActionBar from './QuickActionBar'

const { Text } = Typography

const POLL_INTERVAL_MS = 1500
const TERMINAL_KINDS = new Set(['chair_summary', 'clarification', 'error'])

export default function ConversationView() {
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ConversationMessage[]>([])
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const cursorRef = useRef(0)
  const pollTimerRef = useRef<number | null>(null)

  // 初始化：拿或建 conversation
  useEffect(() => {
    conversationApi.create()
      .then(r => setConversationId(r.conversation_id))
      .catch(e => setError(e?.response?.data?.detail || '初始化失败'))
  }, [])

  const poll = useCallback(async (id: string) => {
    try {
      const r = await conversationApi.listMessages(id, cursorRef.current)
      if (r.messages.length > 0) {
        setMessages(prev => [...prev, ...r.messages])
        cursorRef.current = r.next_cursor
        const terminal = r.messages.some(m => TERMINAL_KINDS.has(m.payload?.kind))
        if (terminal) {
          setAsking(false)
          if (pollTimerRef.current !== null) {
            clearInterval(pollTimerRef.current)
            pollTimerRef.current = null
          }
        }
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || '拉消息失败')
    }
  }, [])

  const startPolling = useCallback(() => {
    if (!conversationId || pollTimerRef.current !== null) return
    pollTimerRef.current = window.setInterval(
      () => poll(conversationId), POLL_INTERVAL_MS,
    )
    // 立即拉一次
    void poll(conversationId)
  }, [conversationId, poll])

  useEffect(() => {
    return () => {
      if (pollTimerRef.current !== null) {
        clearInterval(pollTimerRef.current)
      }
    }
  }, [])

  const submit = useCallback(async (req: TurnRequest) => {
    if (!conversationId || asking) return
    setError(null)
    setAsking(true)
    try {
      await conversationApi.ask(conversationId, req)
      startPolling()
    } catch (e: any) {
      setAsking(false)
      setError(e?.response?.data?.detail || '发送失败')
    }
  }, [conversationId, asking, startPolling])

  const onPreset = (id: PresetId) => submit({ preset_id: id })
  const onText = (text: string) => submit({ text })

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {error && <Alert type="error" showIcon message={error}
        closable onClose={() => setError(null)} />}

      {!conversationId ? <Spin /> : (
        <>
          {messages.length === 0 ? (
            <Card size="small">
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                <Text type="secondary">🎉 直接选一个快捷功能，或问一个具体问题</Text>
                <QuickActionBar onPreset={onPreset} disabled={asking} />
              </Space>
            </Card>
          ) : (
            <Card size="small">
              <QuickActionBar onPreset={onPreset} disabled={asking} />
            </Card>
          )}

          <div style={{ maxHeight: '55vh', overflowY: 'auto', padding: '4px 2px' }}>
            {messages.map(m => <MessageBubble key={m.id} msg={m} />)}
            {messages.length === 0 && (
              <Empty description="还没有消息" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </div>

          <ConversationInput onSubmit={onText} disabled={asking} />
        </>
      )}
    </Space>
  )
}
