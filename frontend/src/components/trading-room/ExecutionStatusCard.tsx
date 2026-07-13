import { Card, Empty, Space, Tag, Typography } from 'antd'

const { Text } = Typography

export default function ExecutionStatusCard({ snapshots }: { snapshots: Array<Record<string, unknown>> }) {
  return (
    <Card size="small" title="申赎与渠道预检">
      {!snapshots.length ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未完成申赎预检，不生成可执行金额" /> : (
        <Space direction="vertical" style={{ width: '100%' }}>
          {snapshots.map((item, index) => {
            const status = String(item.availability || item.manager_status || 'UNKNOWN')
            return (
              <div key={index}>
                <Text strong>{String(item.fund_code || '')}{String(item.share_class || '')}</Text>{' '}
                <Tag color={status === 'OPEN' ? 'green' : status === 'UNKNOWN' ? 'orange' : 'red'}>{status}</Tag>
                <Text>{String(item.channel || '渠道未确认')}</Text>{' '}
                <Text type="secondary">查询 {String(item.queried_at || '时间未知')}</Text>
              </div>
            )
          })}
        </Space>
      )}
    </Card>
  )
}
