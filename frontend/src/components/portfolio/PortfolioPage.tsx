import { Row, Col, Card, Statistic, Typography, Spin, Empty } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { portfolioApi } from '@/api/portfolio'
import AllocationChart from './AllocationChart'
import PnLChart from './PnLChart'
import PositionTable from './PositionTable'

const { Title, Text } = Typography

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
      <div>
        <Title level={4}>我的持仓</Title>
        <Card>
          <div style={{ textAlign: 'center', padding: 80 }}>
            <Spin size="large" />
            <div style={{ marginTop: 16, color: '#999' }}>加载持仓数据...</div>
          </div>
        </Card>
      </div>
    )
  }

  // ── Error / not connected state ──
  if (isError || !portfolio?.connected) {
    return (
      <div>
        <Title level={4}>我的持仓</Title>
        <Card>
          <Empty
            description={
              isError
                ? '获取持仓数据失败，请稍后重试'
                : '未连接养基宝，请先在设置页面同步持仓数据'
            }
          />
        </Card>
      </div>
    )
  }

  const { total_value, total_cost, total_pnl, total_pnl_pct, positions } = portfolio

  // ── Empty positions after connected ──
  if (positions.length === 0) {
    return (
      <div>
        <Title level={4}>我的持仓</Title>

        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
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

        <Card>
          <Empty description="暂无持仓数据" />
        </Card>
      </div>
    )
  }

  // ── Main portfolio view ──
  return (
    <div>
      <Title level={4}>我的持仓</Title>

      {/* ── Summary Cards ── */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="总市值"
              value={total_value}
              precision={2}
              prefix="¥"
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="总成本"
              value={total_cost}
              precision={2}
              prefix="¥"
            />
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

      {/* ── Position Table ── */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Text strong style={{ display: 'block', marginBottom: 12 }}>
          持仓明细
        </Text>
        <PositionTable
          positions={positions}
          totalValue={total_value}
        />
      </Card>

      {/* ── Charts Row ── */}
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
    </div>
  )
}
