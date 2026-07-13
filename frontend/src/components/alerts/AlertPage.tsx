import { Typography, Card } from 'antd'

const { Title } = Typography

export default function AlertPage() {
  return (
    <div>
      <Title level={4}>预警管理</Title>
      <Card>
        <div style={{ textAlign: 'center', padding: 60, color: '#999' }}>
          预警规则配置 + 触发历史
        </div>
      </Card>
    </div>
  )
}
