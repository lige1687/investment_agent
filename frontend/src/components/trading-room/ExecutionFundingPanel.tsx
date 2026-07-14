import { useState } from 'react'
import { Button, Card, Collapse, InputNumber, Space, Typography } from 'antd'
import type { ExecutionFundingInput } from '@/types/tradingRoom'

const { Text } = Typography

interface Props {
  lastConfirmedCash?: number
  lastConfirmedAt?: string | null
  onConfirm: (input: ExecutionFundingInput) => void
  loading?: boolean
}

export default function ExecutionFundingPanel({
  lastConfirmedCash, lastConfirmedAt, onConfirm, loading,
}: Props) {
  const [cash, setCash] = useState<number>(lastConfirmedCash ?? 0)
  const [pendingBuy, setPendingBuy] = useState(0)
  const [consumedToday, setConsumedToday] = useState(0)
  const [showLowFrequency, setShowLowFrequency] = useState(false)

  const hasDifferentDefaults = pendingBuy > 0 || consumedToday > 0
  const assumptionText = hasDifferentDefaults
    ? `按在途买入 ¥${pendingBuy.toLocaleString()}、今日已申购 ¥${consumedToday.toLocaleString()}计算`
    : '按无在途买入、今日未申购计算'

  return (
    <Card size="small" title="确认可买金额">
      {lastConfirmedAt && (
        <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
          上次确认于 {new Date(lastConfirmedAt).toLocaleString('zh-CN')}，本次仍需确认
        </Text>
      )}
      <Space direction="vertical" style={{ width: '100%' }} size={8}>
        <Space>
          <Text>可用现金</Text>
          <InputNumber
            aria-label="可用现金"
            min={0}
            value={cash}
            onChange={v => setCash(Number(v ?? 0))}
          />
        </Space>

        <Text type="secondary" style={{ fontSize: 12 }}>
          {assumptionText}
        </Text>

        <Button
          type="link"
          onClick={() => setShowLowFrequency(!showLowFrequency)}
          style={{ padding: 0 }}
        >
          有未确认订单或今天已买过这只基金
        </Button>

        {showLowFrequency && (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Space>
              <InputNumber
                aria-label="账户在途买入"
                min={0}
                value={pendingBuy}
                onChange={v => setPendingBuy(Number(v ?? 0))}
              />
              <Text>账户在途买入</Text>
            </Space>
            <Space>
              <InputNumber
                aria-label="本基金今日已申购"
                min={0}
                value={consumedToday}
                onChange={v => setConsumedToday(Number(v ?? 0))}
              />
              <Text>本基金今日已申购</Text>
            </Space>
          </Space>
        )}

        <Button type="primary" loading={loading} onClick={() => onConfirm({ available_cash: cash, pending_buy_amount: pendingBuy, consumed_purchase_today: consumedToday })}>
          确认资金并计算最终金额
        </Button>
      </Space>
    </Card>
  )
}
