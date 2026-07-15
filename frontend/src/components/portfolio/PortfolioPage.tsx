import { Row, Col, Card, Statistic, Typography, Spin, Empty } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { portfolioApi } from '@/api/portfolio'
import PageContainer from '@/components/layout/PageContainer'
import AllocationChart from './AllocationChart'
import PnLChart from './PnLChart'
import PositionTable from './PositionTable'

const { Text } = Typography

export default function PortfolioPage() {
  const { data: portfolio, isLoading, isError } = useQuery({
    queryKey: ['yangjibao-portfolio'],
    queryFn: async () => {
      const resp = await portfolioApi.getPortfolio()
      return resp.data
    },
    refetchInterval: 60_000,
  })

  // ── Loading state ──
  if (isLoading) {
    return (
      <PageContainer title="我的持仓" subtitle="养基宝同步的持仓汇总">
        <Card>
          <div style={{ textAlign: 'center', padding: 80 }}>
            <Spin size="large" />
            <div style={{ marginTop: 16, color: '#999' }}>加载持仓数据...</div>
          </div>
        </Card>
      </PageContainer>
    )
  }

  // ── Error / not connected state ──
  if (isError || !portfolio?.connected) {
    return (
      <PageContainer title="我的持仓" subtitle="养基宝同步的持仓汇总">
        <Card>
          <Empty
            description={
              isError
                ? '获取持仓数据失败，请稍后重试'
                : '未连接养基宝，请先在设置页面同步持仓数据'
            }
          />
        </Card>
      </PageContainer>
    )
  }

  const { total_value, total_cost, total_pnl, total_pnl_pct, positions } = portfolio

  const stats = (
    <Row gutter={[16, 16]}>
      <Col xs={12} sm={6}>
        <Card size="small">
          <Statistic title="总市值" value={total_value} precision={2} prefix="¥" />
        </Card>
      </Col>
      <Col xs={12} sm={6}>
        <Card size="small">
          <Statistic title="总成本" value={total_cost} precision={2} prefix="¥" />
        </Card>
      </Col>
      <Col xs={12} sm={6}>
        <Card size="small">
          <Statistic
            title="总盈亏"
            value={total_pnl}
            precision={2}
            prefix="¥"
            valueStyle={{ color: total_pnl >= 0 ? '#cf1322' : '#3f8600' }}
          />
        </Card>
      </Col>
      <Col xs={12} sm={6}>
        <Card size="small">
          <Statistic
            title="总收益率"
            value={total_pnl_pct}
            precision={2}
            suffix="%"
            valueStyle={{ color: total_pnl_pct >= 0 ? '#cf1322' : '#3f8600' }}
          />
        </Card>
      </Col>
    </Row>
  )

  // ── Empty positions after connected ──
  if (positions.length === 0) {
    return (
      <PageContainer title="我的持仓" subtitle="养基宝同步的持仓汇总">
        {stats}
        <Card>
          <Empty description="暂无持仓数据" />
        </Card>
      </PageContainer>
    )
  }

  // ── Main portfolio view ──
  return (
    <PageContainer title="我的持仓" subtitle="养基宝同步的持仓汇总" size="wide">
      {stats}
      <Card size="small">
        <Text strong style={{ display: 'block', marginBottom: 12 }}>
          持仓明细
        </Text>
        <PositionTable
          positions={positions}
          totalValue={total_value}
        />
      </Card>
      <Row gutter={[16, 16]}>
        <Col xs={24} md={12}>
          <Card size="small" title="资产配置">
            <AllocationChart
              positions={positions}
              totalValue={total_value}
            />
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card size="small" title="盈亏分布">
            <PnLChart positions={positions} />
          </Card>
        </Col>
      </Row>
    </PageContainer>
  )
}
