import { Alert, Card, Descriptions, Space, Tag, Typography } from 'antd'
import type { TradingContextSnapshot } from '@/types/tradingRoom'

const { Text } = Typography

export default function ContextSnapshotCard({ context }: { context: TradingContextSnapshot }) {
  return (
    <Card size="small" title="同一时点上下文">
      {!context.formally_actionable && (
        <Alert
          type="warning"
          showIcon
          message="当前上下文不可用于实盘执行"
          description={context.blockers.join(' · ')}
          style={{ marginBottom: 12 }}
        />
      )}
      <Descriptions size="small" column={{ xs: 1, md: 3 }}>
        <Descriptions.Item label="快照时间">{new Date(context.as_of).toLocaleString('zh-CN')}</Descriptions.Item>
        <Descriptions.Item label="账户净值">¥{context.equity.toLocaleString()}</Descriptions.Item>
        <Descriptions.Item label="可用现金">¥{context.cash.toLocaleString()}</Descriptions.Item>
        <Descriptions.Item label="策略版本"><Text code>{context.policy_version_id.slice(0, 12)}</Text></Descriptions.Item>
        <Descriptions.Item label="上下文哈希"><Text code>{context.context_hash.slice(0, 16)}</Text></Descriptions.Item>
        <Descriptions.Item label="状态">
          <Tag color={context.formally_actionable ? 'green' : 'orange'}>
            {context.formally_actionable ? '可进入决策' : '仅解释'}
          </Tag>
        </Descriptions.Item>
      </Descriptions>
      <Space wrap style={{ marginTop: 8 }}>
        {context.critical_inputs.map(item => (
          <Tag key={item.key} color={item.is_mock || item.stale ? 'red' : 'blue'}>
            {item.key} · {item.source} · {item.confidence} · {item.as_of || '时间缺失'}
          </Tag>
        ))}
      </Space>
    </Card>
  )
}
