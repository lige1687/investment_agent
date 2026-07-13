import { useState, useMemo, useCallback } from 'react'
import {
  Row, Col, Card, Statistic, Tag, Button, Modal, Checkbox,
  Space, Typography, Spin, Empty, Tooltip, List, Progress,
} from 'antd'
import {
  PlusOutlined, SettingOutlined, ArrowUpOutlined,
  ArrowDownOutlined, QuestionCircleOutlined, ReloadOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { marketApi } from '@/api/market'
import {
  DEFAULT_INDICES, AVAILABLE_INDICES,
  type IndexConfig, type IndexData, type DiagnosisData,
} from '@/types/market'

const { Title, Text } = Typography

export default function DashboardPage() {
  // ── Index Config State ──
  const [myIndices, setMyIndices] = useState<IndexConfig[]>(() => {
    const saved = localStorage.getItem('dashboard-indices')
    return saved ? JSON.parse(saved) : DEFAULT_INDICES
  })
  const [showConfig, setShowConfig] = useState(false)
  const enabledCodes = useMemo(
    () => myIndices.filter((i) => i.enabled).map((i) => i.code),
    [myIndices]
  )

  // ── Fetch Data ──
  const { data: indicesData, isLoading: indicesLoading, refetch: refetchIndices } = useQuery({
    queryKey: ['global-indices', enabledCodes],
    queryFn: async () => {
      const resp = await marketApi.getIndices(enabledCodes)
      return resp.data.indices
    },
    refetchInterval: 60_000, // 1min refresh
  })

  const { data: diagnosis, isLoading: diagLoading } = useQuery({
    queryKey: ['market-diagnosis'],
    queryFn: async () => {
      const resp = await marketApi.getDiagnosis()
      return resp.data
    },
    refetchInterval: 300_000, // 5min refresh
  })

  // ── Handlers ──
  const saveIndices = useCallback((indices: IndexConfig[]) => {
    setMyIndices(indices)
    localStorage.setItem('dashboard-indices', JSON.stringify(indices))
  }, [])

  const toggleIndex = useCallback((code: string) => {
    const updated = myIndices.map((i) =>
      i.code === code ? { ...i, enabled: !i.enabled } : i
    )
    saveIndices(updated)
  }, [myIndices, saveIndices])

  // ── Render Helpers ──
  const indexColor = (pct: number) => ({
    color: pct > 0 ? '#cf1322' : pct < 0 ? '#3f8600' : '#666',
  })

  const sentimentColor = (val: number | undefined) => {
    if (!val) return '#666'
    if (val <= 25) return '#3f8600' // extreme fear = green (opportunity)
    if (val >= 75) return '#cf1322' // extreme greed = red (risk)
    return '#fa8c16'
  }

  const trendTag = (trend: string) => {
    const map: Record<string, { color: string; text: string }> = {
      leading: { color: 'red', text: '🔥 领涨' },
      improving: { color: 'orange', text: '📈 改善' },
      weakening: { color: 'blue', text: '📉 走弱' },
      lagging: { color: 'default', text: '❄️ 滞后' },
    }
    const item = map[trend] || { color: 'default', text: trend }
    return <Tag color={item.color}>{item.text}</Tag>
  }

  return (
    <div>
      {/* ── Header ── */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>市场概览</Title>
        </Col>
        <Col>
          <Space>
            <Button icon={<ReloadOutlined />} size="small" onClick={() => { refetchIndices() }}>
              刷新行情
            </Button>
            <Button icon={<SettingOutlined />} size="small" onClick={() => setShowConfig(true)}>
              配置指数
            </Button>
          </Space>
        </Col>
      </Row>

      {/* ── 🌍 Global Index Cards ── */}
      <Card size="small" style={{ marginBottom: 16 }}>
        {indicesLoading ? (
          <div style={{ textAlign: 'center', padding: 20 }}><Spin /></div>
        ) : (
          <Row gutter={[12, 12]}>
            {(indicesData || []).map((idx: IndexData) => (
              <Col xs={12} sm={8} md={6} lg={4} key={idx.code}>
                <div className="stat-card" style={{ background: '#fafafa', borderRadius: 8, padding: 10 }}>
                  <Text type="secondary" style={{ fontSize: 11 }}>{idx.name}</Text>
                  <div className="value" style={{ fontSize: 18, ...indexColor(idx.changePct) }}>
                    {idx.price?.toFixed(idx.price > 100 ? 0 : 2)}
                  </div>
                  <div style={{ fontSize: 12, ...indexColor(idx.changePct) }}>
                    {idx.changePct > 0 ? <ArrowUpOutlined /> : idx.changePct < 0 ? <ArrowDownOutlined /> : null}
                    {' '}{idx.changePct > 0 ? '+' : ''}{idx.changePct?.toFixed(2)}%
                    {' '}
                    <Text type="secondary" style={{ fontSize: 10 }}>
                      {idx.change > 0 ? '+' : ''}{idx.change?.toFixed(2)}
                    </Text>
                  </div>
                </div>
              </Col>
            ))}
            {(!indicesData || indicesData.length === 0) && (
              <Col span={24}><Empty description="暂无指数数据" /></Col>
            )}
          </Row>
        )}
      </Card>

      {/* ── 📊 大盘诊断 ── */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        {/* 市场情绪 */}
        <Col xs={24} md={8}>
          <Card
            title={<><QuestionCircleOutlined /> 市场情绪</>}
            size="small"
            loading={diagLoading}
            extra={<Text type="secondary" style={{ fontSize: 11 }}>市场情绪分析 #120</Text>}
          >
            {diagnosis?.sentiment ? (
              <div>
                <div style={{ textAlign: 'center', marginBottom: 12 }}>
                  <Tooltip title="0=极度恐惧, 100=极度贪婪. 巴菲特: 别人恐惧我贪婪">
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      恐慌贪婪指数 <QuestionCircleOutlined />
                    </Text>
                  </Tooltip>
                  <div style={{ fontSize: 36, fontWeight: 700, color: sentimentColor(diagnosis.sentiment.fearGreedIndex) }}>
                    {diagnosis.sentiment.fearGreedIndex ?? '--'}
                  </div>
                  <Tag color={sentimentColor(diagnosis.sentiment.fearGreedIndex)}>
                    {diagnosis.sentiment.fearGreedLabel || '--'}
                  </Tag>
                </div>
                <Space direction="vertical" size={4} style={{ width: '100%', fontSize: 12 }}>
                  <Row justify="space-between">
                    <Text type="secondary">融资余额</Text>
                    <Text>{diagnosis.sentiment.marginBalance?.toFixed(0) ?? '--'} 亿</Text>
                  </Row>
                  <Row justify="space-between">
                    <Text type="secondary">融券余额</Text>
                    <Text>{diagnosis.sentiment.shortBalance?.toFixed(0) ?? '--'} 亿</Text>
                  </Row>
                  <Row justify="space-between">
                    <Text type="secondary">Put/Call比率</Text>
                    <Text>{diagnosis.sentiment.putCallRatio?.toFixed(2) ?? '--'}</Text>
                  </Row>
                  <Row justify="space-between">
                    <Text type="secondary">北向资金</Text>
                    <Text style={{ color: (diagnosis.sentiment.northBoundFlow ?? 0) > 0 ? '#cf1322' : '#3f8600' }}>
                      {diagnosis.sentiment.northBoundFlow != null
                        ? `${diagnosis.sentiment.northBoundFlow > 0 ? '+' : ''}${diagnosis.sentiment.northBoundFlow.toFixed(1)}亿`
                        : '--'}
                    </Text>
                  </Row>
                </Space>
              </div>
            ) : (
              <Empty description="情绪数据获取中..." image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>
        </Col>

        {/* 资金流向板块 TOP5 */}
        <Col xs={24} md={8}>
          <Card
            title="💰 资金流入 TOP5"
            size="small"
            loading={diagLoading}
            extra={<Text type="secondary" style={{ fontSize: 11 }}>行业轮动 #119</Text>}
          >
            {diagnosis?.topCapitalInflow?.length ? (
              <List
                size="small"
                dataSource={diagnosis.topCapitalInflow}
                renderItem={(item) => (
                  <List.Item style={{ padding: '4px 0' }}>
                    <Row justify="space-between" style={{ width: '100%' }} align="middle">
                      <Col>
                        <Tag color="red" style={{ fontSize: 10 }}>{item.rank}</Tag>
                        <Text style={{ fontSize: 13 }}>{item.sectorName}</Text>
                      </Col>
                      <Col>
                        <Text strong style={{ color: '#cf1322', fontSize: 13 }}>
                          +{item.netFlow.toFixed(1)}亿
                        </Text>
                        {item.consecutiveDays ? (
                          <Text type="secondary" style={{ fontSize: 10, marginLeft: 4 }}>
                            {item.consecutiveDays}日
                          </Text>
                        ) : null}
                      </Col>
                    </Row>
                  </List.Item>
                )}
              />
            ) : (
              <Empty description="资金数据获取中..." image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>
        </Col>

        {/* 板块轮动 */}
        <Col xs={24} md={8}>
          <Card
            title="🔄 板块轮动"
            size="small"
            loading={diagLoading}
            extra={<Text type="secondary" style={{ fontSize: 11 }}>行业轮动监控 #187</Text>}
          >
            {diagnosis?.sectorRotation?.length ? (
              <List
                size="small"
                dataSource={diagnosis.sectorRotation.slice(0, 8)}
                renderItem={(item) => (
                  <List.Item style={{ padding: '3px 0' }}>
                    <Row justify="space-between" style={{ width: '100%' }} align="middle">
                      <Col>
                        <Text style={{ fontSize: 13 }}>{item.sectorName}</Text>
                      </Col>
                      <Col>
                        <Space size={4}>
                          {trendTag(item.trend)}
                          <Progress
                            percent={item.momentumScore * 100}
                            size="small"
                            style={{ width: 60, margin: 0 }}
                            strokeColor={item.momentumScore > 0.6 ? '#cf1322' : item.momentumScore > 0.3 ? '#fa8c16' : '#3f8600'}
                            format={() => `${item.heatLevel}🔥`}
                          />
                        </Space>
                      </Col>
                    </Row>
                  </List.Item>
                )}
              />
            ) : (
              <Empty description="轮动数据获取中..." image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>
        </Col>
      </Row>

      {/* ── Summary + North-bound ── */}
      {diagnosis?.summary && (
        <Card size="small" style={{ marginBottom: 16, background: '#f6f8fa' }}>
          <Row gutter={16}>
            <Col xs={24} md={16}>
              <Text strong>📋 AI 诊断总结：</Text>
              <Text>{diagnosis.summary}</Text>
            </Col>
            <Col xs={24} md={8}>
              {(diagnosis.northBoundSectors || []).length > 0 && (
                <>
                  <Text strong style={{ fontSize: 12 }}>北向加仓板块：</Text>
                  <Space size={4} wrap>
                    {diagnosis.northBoundSectors.map((s) => (
                      <Tag key={s.sectorCode} color="blue" style={{ fontSize: 11 }}>
                        {s.sectorName} +{s.netFlow.toFixed(1)}亿
                      </Tag>
                    ))}
                  </Space>
                </>
              )}
            </Col>
          </Row>
        </Card>
      )}

      {/* ── 预警 + 信号 (Placeholder) ── */}
      <Row gutter={[16, 16]}>
        <Col xs={24} md={12}>
          <Card title="🚨 最近预警" size="small">
            <Empty description="暂无触发预警" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card title="⚡ 活跃信号" size="small">
            <Empty description="暂无交易信号" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          </Card>
        </Col>
      </Row>

      {/* ── Index Config Modal ── */}
      <Modal
        title="配置全球指数"
        open={showConfig}
        onCancel={() => setShowConfig(false)}
        onOk={() => setShowConfig(false)}
        width={500}
      >
        <Text type="secondary" style={{ marginBottom: 12, display: 'block' }}>
          勾选你要关注的全球指数，取消勾选则隐藏。支持A股、港股、美股、日股、韩股、欧股等。
        </Text>
        <Checkbox.Group
          value={enabledCodes}
          onChange={(values) => {
            const updated = myIndices.map((i) => ({
              ...i,
              enabled: (values as string[]).includes(i.code),
            }))
            // Add any newly selected indices from AVAILABLE_INDICES
            for (const v of values as string[]) {
              if (!updated.find((i) => i.code === v)) {
                const found = AVAILABLE_INDICES.find((a) => a.code === v)
                if (found) updated.push({ ...found, enabled: true })
              }
            }
            saveIndices(updated)
          }}
        >
          <Row gutter={[8, 8]}>
            {AVAILABLE_INDICES.map((idx) => (
              <Col span={12} key={idx.code}>
                <Checkbox value={idx.code}>
                  {idx.name}
                  <Tag style={{ marginLeft: 4, fontSize: 10 }}>{idx.market}</Tag>
                </Checkbox>
              </Col>
            ))}
          </Row>
        </Checkbox.Group>
      </Modal>
    </div>
  )
}
