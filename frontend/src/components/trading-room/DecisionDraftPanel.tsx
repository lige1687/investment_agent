import { useEffect, useState } from 'react'
import { Alert, Button, Card, InputNumber, Space, Tag, Typography } from 'antd'
import type { FinalDecision } from '@/types/tradingRoom'

const { Text } = Typography

const ACTION_LABEL = {
  IMMEDIATE: { label: '立即操作', color: 'green' },
  CONDITIONAL: { label: '条件操作', color: 'blue' },
  WATCH: { label: '继续观察', color: 'orange' },
  NO_ACTION: { label: '今天不操作', color: 'default' },
} as const

const money = (value: number) => `¥${value.toLocaleString('zh-CN')}`

interface Props {
  decision: FinalDecision | null
  contextActionable: boolean
  onConfirm?: (amount: number) => void
  submitting?: boolean
}

export default function DecisionDraftPanel({
  decision, contextActionable, onConfirm, submitting,
}: Props) {
  const [amount, setAmount] = useState<number | null>(decision?.guarded_range?.minimum ?? null)
  useEffect(() => setAmount(decision?.guarded_range?.minimum ?? null), [decision])

  if (!decision) {
    return <Card size="small" title="交易结论"><Alert type="info" message="允许结论：今天不操作。当前尚未形成最终草案。" /></Card>
  }
  const action = ACTION_LABEL[decision.action_class]
  const validAmount = Boolean(
    amount !== null
      && decision.guarded_range
      && amount >= decision.guarded_range.minimum
      && amount <= decision.guarded_range.maximum,
  )
  const confirmable = contextActionable
    && validAmount
    && ['IMMEDIATE', 'CONDITIONAL'].includes(decision.action_class)

  return (
    <Card size="small" title="交易结论与金额确认">
      <Space direction="vertical" style={{ width: '100%' }} size={10}>
        <Space wrap>
          <Tag color={action.color}>{action.label}</Tag>
          <Text>机会分 {decision.score}</Text>
          <Text type="secondary">只在机会明显时操作</Text>
        </Space>
        <Text>
          建议区间：{money(decision.suggested_range.minimum)} - {money(decision.suggested_range.maximum)}
        </Text>
        <Text strong>
          {decision.guarded_range
            ? `护栏后：${money(decision.guarded_range.minimum)} - ${money(decision.guarded_range.maximum)}`
            : '护栏后：暂无可执行金额'}
        </Text>
        {!!decision.reasons.length && (
          <Alert type="warning" showIcon message="暂不可直接执行" description={decision.reasons.join(' · ')} />
        )}
        <Space wrap>
          <Text>¥</Text>
          <InputNumber
            aria-label="最终金额"
            min={decision.guarded_range?.minimum}
            max={decision.guarded_range?.maximum}
            value={amount}
            onChange={value => setAmount(value === null ? null : Number(value))}
            disabled={!decision.guarded_range}
          />
          <Button
            type="primary"
            disabled={!confirmable}
            loading={submitting}
            onClick={() => amount !== null && onConfirm?.(amount)}
          >
            确认采用
          </Button>
          <Text type="secondary">系统不下单，金额由你最终确认后手动执行</Text>
        </Space>
      </Space>
    </Card>
  )
}
