import { Card, Empty } from 'antd'
import PageContainer from '@/components/layout/PageContainer'

export default function SignalPage() {
  return (
    <PageContainer title="交易信号" subtitle="技术面与基本面信号汇总">
      <Card>
        <Empty description="接入技术分析引擎后展示" />
      </Card>
    </PageContainer>
  )
}
