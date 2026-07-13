import { Card, Empty, Space, Tag, Typography } from 'antd'

const { Text } = Typography

export default function ExposureCard({ snapshots }: { snapshots: Array<Record<string, unknown>> }) {
  return (
    <Card size="small" title="基金主题暴露">
      {!snapshots.length ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无主题暴露快照" /> : (
        <Space direction="vertical" style={{ width: '100%' }}>
          {snapshots.map((item, index) => (
            <div key={index}>
              <Text strong>{String(item.fund_code || '未知基金')}</Text>{' '}
              <Tag>{String(item.theme || '未识别题材')}</Tag>
              <Tag color={item.confidence === 'LOW' ? 'orange' : 'blue'}>{String(item.confidence || 'UNKNOWN')}</Tag>
              <Text type="secondary">公开持仓截止 {String(item.report_period_end || '未知')}</Text>
            </div>
          ))}
        </Space>
      )}
    </Card>
  )
}
