import { Card, Collapse, Space, Tag, Typography } from 'antd'
import type { ConversationMessage } from '@/types/conversation'

const { Text, Paragraph } = Typography

const ROLE_LABEL: Record<string, string> = {
  market_regime: '市场环境',
  theme_fund: '主题基金',
  portfolio_risk: '组合风险',
  buy: '买入评估',
  sell_protection: '卖出保护',
  skeptic: '证据审查',
  chair: '主席',
}

export default function MessageBubble({ msg }: { msg: ConversationMessage }) {
  const kind = msg.payload?.kind ?? 'text'
  const p = (msg.payload?.payload ?? {}) as any

  if (kind === 'text') {
    const isUser = msg.sender_role === 'user'
    return (
      <div data-testid="bubble-text" style={{ display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start', margin: '6px 0' }}>
        <Card size="small" style={{ maxWidth: '80%',
          background: isUser ? '#e6f4ff' : '#fafafa' }}>
          <Paragraph style={{ margin: 0 }}>{msg.content}</Paragraph>
        </Card>
      </div>
    )
  }

  if (kind === 'routing') {
    const parts = (p.participants ?? []) as string[]
    const funds = (p.resolved_funds ?? []) as Array<{ code: string, name: string }>
    return (
      <Card size="small" data-testid="bubble-routing"
            style={{ margin: '6px 0', background: '#fff7e6' }}>
        <Space size={6} wrap>
          <Text type="secondary">本次参与:</Text>
          {parts.map(r => <Tag key={r} color="orange">{ROLE_LABEL[r] ?? r}</Tag>)}
        </Space>
        {funds.length > 0 && (
          <div style={{ marginTop: 6 }}>
            <Text type="secondary">已解析: </Text>
            {funds.map(f => <Tag key={f.code}>{f.name}({f.code})</Tag>)}
          </div>
        )}
      </Card>
    )
  }

  if (kind === 'specialist_memo') {
    const role = msg.sender_role
    const memo = (p.memo ?? {}) as any
    const label = ROLE_LABEL[role] ?? role
    const oneliner = memo.summary ?? (p.error ? `不可用: ${p.error}` : '(无 summary)')
    return (
      <Card size="small" data-testid="bubble-specialist_memo"
            style={{ margin: '6px 0' }}>
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          <Space>
            <Tag color="blue">{label}</Tag>
            <Text>{oneliner}</Text>
          </Space>
          <Collapse ghost items={[{
            key: 'detail',
            label: '▸ 详情',
            children: <pre style={{ margin: 0, fontSize: 12 }}>
              {JSON.stringify(memo, null, 2)}
            </pre>,
          }]} />
        </Space>
      </Card>
    )
  }

  if (kind === 'amount_suggestion') {
    return (
      <Card size="small" data-testid="bubble-amount_suggestion"
            style={{ margin: '6px 0', background: '#f6ffed' }}>
        <Text>
          {p.action === 'buy' ? '建议买入' : '建议卖出'} {p.fund_code}:
          {' '}{p.minimum} - {p.maximum} {p.currency}
        </Text>
        <Paragraph type="secondary" style={{ margin: 0, fontSize: 12 }}>
          {p.basis}
        </Paragraph>
        {(p.caveats ?? []).map((c: string, i: number) => (
          <div key={i} style={{ fontSize: 11, color: '#faad14' }}>⚠️ {c}</div>
        ))}
      </Card>
    )
  }

  if (kind === 'chair_summary') {
    return (
      <Card size="small" data-testid="bubble-chair_summary"
            style={{ margin: '6px 0', borderColor: '#1677ff' }}>
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          <Space><Tag color="geekblue">主席</Tag></Space>
          <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{p.text}</Paragraph>
          {(p.data_caveats ?? []).map((c: string, i: number) => (
            <div key={i} style={{ fontSize: 12, color: '#faad14' }}>⚠️ {c}</div>
          ))}
        </Space>
      </Card>
    )
  }

  if (kind === 'clarification') {
    const ambigs = (p.ambiguities ?? []) as Array<{ hint: string,
      candidates: Array<{ code: string, name: string }> }>
    return (
      <Card size="small" data-testid="bubble-clarification"
            style={{ margin: '6px 0', background: '#fffbe6' }}>
        {ambigs.map((a, i) => (
          <div key={i}>
            <Text strong>{a.hint}</Text>
            <div>
              {a.candidates.map(c => (
                <Tag key={c.code} style={{ marginTop: 4 }}>
                  {c.name}({c.code})
                </Tag>
              ))}
            </div>
          </div>
        ))}
      </Card>
    )
  }

  // error
  return (
    <Card size="small" data-testid="bubble-error"
          style={{ margin: '6px 0', background: '#fff1f0' }}>
      <Text type="danger">{p.detail ?? '出现错误'}</Text>
    </Card>
  )
}
