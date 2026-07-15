import { Card, Empty } from 'antd'
import PageContainer from '@/components/layout/PageContainer'

export default function FundSearchPage() {
  return (
    <PageContainer title="基金筛选" subtitle="接入 hithink-fund-selector 后展示">
      <Card>
        <Empty description="基金/ETF 多维度筛选" />
      </Card>
    </PageContainer>
  )
}
