import { Alert, Button, Card, Space, Spin, Typography } from 'antd'
import { CheckCircleOutlined, SyncOutlined } from '@ant-design/icons'

const { Text } = Typography

interface Props {
  connected: boolean
  positionCount: number
  totalValue: number
  syncedAt: string | null
  loading: boolean
  onSync?: () => void
}

export default function SyncedAccountSummary({
  connected, positionCount, totalValue, syncedAt, loading, onSync,
}: Props) {
  if (loading) return <Spin size="small" />

  if (!connected || positionCount === 0) {
    return (
      <Alert
        type="warning"
        showIcon
        message="暂无已同步持仓"
        description="请先在养基宝中同步持仓后开始正式讨论。"
        action={onSync ? (
          <Button size="small" icon={<SyncOutlined />} onClick={onSync}>立即同步</Button>
        ) : undefined}
        style={{ marginBottom: 12 }}
      />
    )
  }

  const timeText = syncedAt
    ? new Date(syncedAt).toLocaleString('zh-CN')
    : '同步时间未知'

  return (
    <Card size="small" style={{ marginBottom: 12 }}>
      <Space>
        <CheckCircleOutlined style={{ color: 'var(--ant-color-success, #52c41a)' }} />
        <Text>
          已同步 {positionCount} 个持仓 · 总市值 ¥{totalValue.toLocaleString()} · {timeText}
        </Text>
        {!syncedAt && <Text type="warning">同步时间未知</Text>}
        {onSync && <Button size="small" icon={<SyncOutlined />} onClick={onSync}>同步</Button>}
      </Space>
    </Card>
  )
}
