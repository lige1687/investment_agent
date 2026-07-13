import { useState } from 'react'
import { Alert, Button, Card, Input, InputNumber, Space, Typography } from 'antd'
import type { TargetAllocation, TradingPolicy } from '@/types/tradingRoom'

const { Text } = Typography

interface Props {
  policy: TradingPolicy
  loading?: boolean
  onImport?: (targets: TargetAllocation[]) => void
}

export default function PolicyImportPanel({ policy, loading, onImport }: Props) {
  const [targets, setTargets] = useState<TargetAllocation[]>([
    { scope: 'theme', key: '通信', target_pct: 0.25 },
    { scope: 'theme', key: '纳斯达克', target_pct: 0.25 },
    { scope: 'theme', key: '全球基金', target_pct: 0.2 },
  ])

  if (policy.ready) {
    return (
      <Card size="small" title="当前交易政策">
        <Space wrap>
          <Text>{policy.display_name}</Text>
          <Text type="secondary">明显机会 ≥ {policy.buy_obvious_threshold} 分</Text>
          {policy.target_allocations.map(item => (
            <Text code key={`${item.scope}-${item.key}`}>
              {item.key} {(item.target_pct * 100).toFixed(0)}%
            </Text>
          ))}
        </Space>
      </Card>
    )
  }

  return (
    <Card title="还需确认目标仓位" size="small">
      <Alert
        type="warning"
        showIcon
        message="默认中线题材模板已载入"
        description="止损优先级、账户回撤阈值和机会分数都已有初始值；现在只确认题材目标仓位，不会像查户口一样逐项追问。"
        style={{ marginBottom: 12 }}
      />
      <Space direction="vertical" style={{ width: '100%' }}>
        {targets.map((target, index) => (
          <Space key={index} wrap>
            <Input
              aria-label={`题材 ${index + 1}`}
              value={target.key}
              onChange={event => setTargets(current => current.map((item, itemIndex) => (
                itemIndex === index ? { ...item, key: event.target.value } : item
              )))}
              style={{ width: 150 }}
            />
            <InputNumber
              aria-label={`目标仓位 ${index + 1}`}
              min={1}
              max={100}
              value={target.target_pct * 100}
              onChange={value => setTargets(current => current.map((item, itemIndex) => (
                itemIndex === index ? { ...item, target_pct: Number(value || 0) / 100 } : item
              )))}
            />
            <Text>%</Text>
          </Space>
        ))}
        <Button
          type="primary"
          loading={loading}
          disabled={targets.some(item => !item.key || item.target_pct <= 0)}
          onClick={() => onImport?.(targets)}
        >
          确认目标仓位
        </Button>
      </Space>
    </Card>
  )
}
