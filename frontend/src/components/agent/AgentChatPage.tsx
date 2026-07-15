import { useState, useRef, useEffect } from 'react'
import {
  Typography, Input, Button, Card, Space, Tag, Spin,
  Row, Col,
} from 'antd'
import {
  SendOutlined, RobotOutlined, UserOutlined,
  ThunderboltOutlined, SearchOutlined, WalletOutlined,
  AlertOutlined, LineChartOutlined, ClearOutlined,
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import { agentApi } from '@/api/agent'
import PageContainer from '@/components/layout/PageContainer'
import type { ChatMessage, ToolCall } from '@/types/agent'
import DecisionCardView from './DecisionCardView'

const { Text } = Typography
const { TextArea } = Input

const SESSION_KEY = 'fund_agent_session_id'

// Quick suggestions
const SUGGESTIONS = [
  { icon: <WalletOutlined />, label: '我的持仓分析', question: '帮我分析一下我的持仓情况，哪些表现好？哪些需要关注？' },
  { icon: <LineChartOutlined />, label: '市场热点板块', question: '最近市场热点板块有哪些？资金流向如何？' },
  { icon: <SearchOutlined />, label: '推荐新能源基金', question: '筛选几只新能源主题的优质基金' },
  { icon: <ThunderboltOutlined />, label: '持仓风险诊断', question: '我的持仓风险大吗？行业集中度如何？' },
  { icon: <AlertOutlined />, label: '下周一是否减仓', question: '下周一我要不要减仓? 关注 001513 和 022184 的持仓。给我明确建议 + 监控条件。' },
]

export default function AgentChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: 'assistant',
      content: '你好！我是基金投资 AI 助手 🤖\n\n涉及买卖决策的问题，我会给出**结构化决策卡**：6 维评估 + 分歧提示 + 组合上下文 + 执行方案 + 监控条件。每一维都可以点开看原始数据。\n\n试试下面的问题，或直接输入。',
      timestamp: new Date().toISOString(),
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(
    () => localStorage.getItem(SESSION_KEY),
  )
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    if (sessionId) localStorage.setItem(SESSION_KEY, sessionId)
  }, [sessionId])

  const sendMessage = async (text: string) => {
    if (!text.trim() || loading) return

    const userMsg: ChatMessage = { role: 'user', content: text, timestamp: new Date().toISOString() }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setLoading(true)

    try {
      // History = last N user/assistant text pairs (drop cards to keep prompt small)
      const history = messages
        .filter(m => m.content)
        .slice(-10)
        .map(m => ({ role: m.role, content: m.content }))

      const resp = await agentApi.chat(text, { history, session_id: sessionId })
      const data = resp.data

      if (!sessionId && data.session_id) setSessionId(data.session_id)

      const assistantMsg: ChatMessage = {
        role: 'assistant',
        content: data.answer || '抱歉，我暂时无法回答这个问题。',
        toolCalls: data.tool_calls,
        decisionCard: data.decision_card,
        evidenceRefs: data.evidence_refs,
        storedCardId: data.stored_card_id,
        timestamp: new Date().toISOString(),
        meta: {
          turns: data.turns ?? undefined,
          stop_reason: data.stop_reason ?? undefined,
          fallback: data.fallback,
          input_tokens: data.usage?.input_tokens,
          output_tokens: data.usage?.output_tokens,
          model: data.usage?.model,
          provider: data.usage?.provider,
        },
      }
      setMessages(prev => [...prev, assistantMsg])
    } catch (e: any) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '⚠️ 请求失败:' + (e?.response?.data?.detail || e.message),
        timestamp: new Date().toISOString(),
      }])
    } finally {
      setLoading(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage(input)
    }
  }

  const resetSession = () => {
    localStorage.removeItem(SESSION_KEY)
    setSessionId(null)
    setMessages([messages[0]])
  }

  return (
    <PageContainer
      title={
        <Space>
          <RobotOutlined /> AI 投资助手
          {loading && <Spin size="small" />}
        </Space>
      }
      subtitle="基于市场数据和持仓的智能分析"
      extra={
        <Space size={4}>
          {sessionId && (
            <Text type="secondary" style={{ fontSize: 11, fontFamily: 'monospace' }}>
              session: {sessionId.slice(0, 20)}
            </Text>
          )}
          <Button icon={<ClearOutlined />} onClick={resetSession}>新会话</Button>
        </Space>
      }
    >
      {/* Chat area */}
      <div style={{
        height: 'calc(100vh - 280px)',
        overflowY: 'auto',
        padding: '0 4px',
      }}>
        {messages.map((msg, idx) => (
          <div key={idx} style={{ marginBottom: 16 }}>
            {/* Role label */}
            <div style={{
              display: 'flex', alignItems: 'center', marginBottom: 4,
              justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
            }}>
              <Space>
                {msg.role === 'assistant' ? (
                  <><RobotOutlined style={{ color: '#1677ff' }} /><Text type="secondary" style={{ fontSize: 12 }}>AI 助手</Text></>
                ) : (
                  <><Text type="secondary" style={{ fontSize: 12 }}>你</Text><UserOutlined /></>
                )}
              </Space>
            </div>

            {/* Text bubble */}
            <div style={{
              background: msg.role === 'user' ? '#e6f4ff' : '#fafafa',
              borderRadius: 12,
              padding: '12px 16px',
              marginLeft: msg.role === 'user' ? 60 : 0,
              marginRight: msg.role === 'user' ? 0 : 60,
              border: '1px solid #f0f0f0',
            }}>
              <ReactMarkdown
                components={{
                  h2: ({ children }) => <div style={{ fontSize: 16, fontWeight: 600, margin: '8px 0 4px' }}>{children}</div>,
                  h3: ({ children }) => <div style={{ fontSize: 14, fontWeight: 600, margin: '6px 0 2px' }}>{children}</div>,
                  p: ({ children }) => <div style={{ margin: '4px 0', lineHeight: 1.6 }}>{children}</div>,
                  li: ({ children }) => <li style={{ margin: '2px 0' }}>{children}</li>,
                  code: ({ children }) => <Tag style={{ fontSize: 11 }}>{children}</Tag>,
                }}
              >
                {msg.content}
              </ReactMarkdown>

              {/* Tool call indicator */}
              {msg.toolCalls && msg.toolCalls.length > 0 && (
                <div style={{ marginTop: 8, borderTop: '1px dashed #d9d9d9', paddingTop: 8 }}>
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    🔧 调用了 {msg.toolCalls.length} 个工具：
                    {' '}
                    <Space size={2} wrap>
                      {uniqueToolNames(msg.toolCalls).map((name, i) => (
                        <Tag key={i} color="blue" style={{ fontSize: 10 }}>{name}</Tag>
                      ))}
                    </Space>
                  </Text>
                </div>
              )}

              {/* Meta strip (turns / tokens / model) */}
              {msg.meta && (
                <div style={{ marginTop: 4 }}>
                  <Text type="secondary" style={{ fontSize: 10, fontFamily: 'monospace' }}>
                    {msg.meta.turns != null && `${msg.meta.turns} 轮`}
                    {msg.meta.model && ` · ${msg.meta.model}`}
                    {msg.meta.input_tokens != null && ` · in ${msg.meta.input_tokens}`}
                    {msg.meta.output_tokens != null && ` · out ${msg.meta.output_tokens}`}
                    {msg.meta.fallback && ' · fallback'}
                  </Text>
                </div>
              )}
            </div>

            {/* Decision card (rendered under the message when present) */}
            {msg.decisionCard && (
              <div style={{ marginRight: msg.role === 'user' ? 0 : 60, marginLeft: msg.role === 'user' ? 60 : 0 }}>
                <DecisionCardView card={msg.decisionCard} />
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div style={{ textAlign: 'center', padding: 12 }}>
            <Spin size="small" />
            <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>AI 思考中(可能拉数据、调板块、生成决策卡)...</Text>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Suggestions before any user turn */}
      {messages.length <= 1 && (
        <Card size="small" style={{ marginBottom: 12, background: '#fafafa' }}>
          <Text type="secondary" style={{ fontSize: 12, marginBottom: 8, display: 'block' }}>💡 快捷提问</Text>
          <Row gutter={[8, 8]}>
            {SUGGESTIONS.map((s, i) => (
              <Col xs={24} sm={12} key={i}>
                <Button
                  size="small"
                  icon={s.icon}
                  onClick={() => sendMessage(s.question)}
                  style={{ width: '100%', textAlign: 'left', fontSize: 12 }}
                >
                  {s.label}
                </Button>
              </Col>
            ))}
          </Row>
        </Card>
      )}

      {/* Input */}
      <div style={{ display: 'flex', gap: 8 }}>
        <TextArea
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入你的问题,如:001513 该继续持有还是减仓?"
          rows={2}
          disabled={loading}
          style={{ flex: 1 }}
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={() => sendMessage(input)}
          loading={loading}
          disabled={!input.trim()}
          size="large"
        >
          发送
        </Button>
      </div>
    </PageContainer>
  )
}

function uniqueToolNames(calls: ToolCall[]): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const c of calls) {
    const n = c.name || c.tool || 'tool'
    if (!seen.has(n)) {
      seen.add(n)
      out.push(n)
    }
  }
  return out
}
