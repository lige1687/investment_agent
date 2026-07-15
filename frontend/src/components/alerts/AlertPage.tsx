import { Card, Empty } from 'antd'
import PageContainer from '@/components/layout/PageContainer'

export default function AlertPage() {
  return (
    <PageContainer title="预警管理" subtitle="预警规则配置 + 触发历史">
      <Card>
        <Empty description="正在开发中" />
      </Card>
    </PageContainer>
  )
}
