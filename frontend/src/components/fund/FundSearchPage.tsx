import { Typography, Card } from 'antd'

const { Title } = Typography

export default function FundSearchPage() {
  return (
    <div>
      <Title level={4}>基金筛选</Title>
      <Card>
        <div style={{ textAlign: 'center', padding: 60, color: '#999' }}>
          基金/ETF 多维度筛选 - 接入 hithink-fund-selector 后展示
        </div>
      </Card>
    </div>
  )
}
