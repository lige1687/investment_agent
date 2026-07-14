import { Alert, Card, Descriptions, Space, Tag, Typography } from 'antd'
import type { TradingContextSnapshot } from '@/types/tradingRoom'

const { Text } = Typography

function money(value: number | null): string {
  if (value === null) return '—'
  return `¥${value.toLocaleString()}`
}

export default function ContextSnapshotCard({ context }: { context: TradingContextSnapshot }) {
  const analysisBlockers = context.blockers.filter(b => !b.startsWith('available_cash_') && !b.startsWith('account_drawdown_'))
  const executionBlockers = context.execution_blockers || []

  return (
    <Card size="small" title="同一时点上下文">
      {!context.formally_actionable && analysisBlockers.length > 0 && (
        <Alert
          type="warning"
          showIcon
          message="当前上下文不可用于实盘执行"
          description={analysisBlockers.join(' · ')}
          style={{ marginBottom: 12 }}
        />
      )}
      {!context.execution_ready && executionBlockers.length > 0 && (
        <Alert
          type="info"
          showIcon
          message="已确认分析，但金额信息不完整"
          description={executionBlockers.join(' · ')}
          style={{ marginBottom: 12 }}
        />
      )}
      <Descriptions size="small" column={{ xs: 1, md: 3 }}>
        <Descriptions.Item label="快照时间">{new Date(context.as_of).toLocaleString('zh-CN')}</Descriptions.Item>
        <Descriptions.Item label="可用现金">
          {context.cash === null ? '买入时确认' : money(context.cash)}
        </Descriptions.Item>
        <Descriptions.Item label="持仓市值">{money(context.holdings_value)}</Descriptions.Item>
        <Descriptions.Item label="账户净值">
          {context.equity === null ? '现金确认后计算' : money(context.equity)}
        </Descriptions.Item>
        <Descriptions.Item label="账户近期峰值">
          {context.peak_equity === null ? '历史不足' : money(context.peak_equity)}
        </Descriptions.Item>
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
