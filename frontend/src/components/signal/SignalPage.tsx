import { Typography, Card } from 'antd'

const { Title } = Typography

export default function SignalPage() {
  return (
    <div>
      <Title level={4}>交易信号</Title>
      <Card>
        <div style={{ textAlign: 'center', padding: 60, color: '#999' }}>
          买卖信号列表 - 接入技术分析引擎后展示
        </div>
      </Card>
    </div>
  )
}
