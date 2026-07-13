import { useState, useMemo } from 'react'
import {
  Card, Table, Tag, Row, Col, Space, Button, Drawer, Empty,
  Typography, Progress, Tooltip, Segmented, Badge, Statistic,
  Divider,
} from 'antd'
import {
  ArrowUpOutlined, ArrowDownOutlined, ReloadOutlined, BgColorsOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { marketApi } from '@/api/market'
import { deriveDataState } from '@/api/adapters/market'
import DataStatePanel from '@/components/common/DataStatePanel'
import DemoDataBanner from '@/components/common/DemoDataBanner'
import type { SectorRankingItem } from '@/types/market'

const { Title, Text } = Typography

type SortBy = 'score' | 'change' | 'flow'
type FilterSignal = 'all' | 'strong' | 'watch' | 'weak'

interface SectorDetailDrawerProps {
  sector: SectorRankingItem | null
  visible: boolean
  onClose: () => void
}

/**右侧详情抽屉*/
function SectorDetailDrawer({ sector, visible, onClose }: SectorDetailDrawerProps) {
  if (!sector) return null

  const signalColors: Record<string, string> = {
    STRONG: '#cf1322',
    WATCH: '#fa8c16',
    WEAK: '#1f77b9',
    AVOID: '#999',
  }

  return (
    <Drawer
      title={`${sector.name} 详细分析`}
      placement="right"
      onClose={onClose}
      open={visible}
      width={420}
      bodyStyle={{ padding: 16 }}
    >
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        {/* 头部快速概览 */}
        <Card size="small" style={{ background: '#fafafa' }}>
          <Row gutter={16} align="middle">
            <Col span={12}>
              <Statistic
                title="综合评分"
                value={sector.baseScore}
                precision={2}
                suffix="/10"
                valueStyle={{ fontSize: 28, fontWeight: 700 }}
              />
            </Col>
            <Col span={12}>
              <div style={{ textAlign: 'center' }}>
                <Tag
                  color={signalColors[sector.signal]}
                  style={{ fontSize: 14, padding: '4px 12px' }}
                >
                  {sector.signal}
                </Tag>
                <div style={{ fontSize: 12, marginTop: 4, color: '#666' }}>
                  置信度 {(sector.confidence * 100).toFixed(0)}%
                </div>
              </div>
            </Col>
          </Row>
          <Divider style={{ margin: '12px 0' }} />
          <Row gutter={16}>
            <Col span={12}>
              <Statistic
                title="涨跌幅"
                value={sector.changePct}
                precision={2}
                suffix="%"
                valueStyle={{
                  color: sector.changePct > 0 ? '#cf1322' : sector.changePct < 0 ? '#3f8600' : '#666',
                  fontSize: 20,
                }}
              />
            </Col>
            <Col span={12}>
              <Statistic
                title="主力净流入"
                value={sector.flowValue}
                precision={1}
                suffix="亿"
                valueStyle={{
                  color: sector.flowValue > 0 ? '#cf1322' : sector.flowValue < 0 ? '#3f8600' : '#666',
                  fontSize: 20,
                }}
              />
            </Col>
          </Row>
        </Card>

        {/* 维度评分 */}
        <div>
          <Title level={5}>📊 维度评分</Title>
          <Space direction="vertical" style={{ width: '100%' }} size="small">
            <div>
              <Row justify="space-between" style={{ marginBottom: 4 }}>
                <Text>💹 技术面</Text>
                <Text strong>{sector.breakdown.price.toFixed(2)}/10</Text>
              </Row>
              <Progress
                percent={(sector.breakdown.price / 10) * 100}
                strokeColor="#1f77b9"
                showInfo={false}
                size="small"
              />
            </div>
            <div>
              <Row justify="space-between" style={{ marginBottom: 4 }}>
                <Text>💰 资金面</Text>
                <Text strong>{sector.breakdown.flow.toFixed(2)}/10</Text>
              </Row>
              <Progress
                percent={(sector.breakdown.flow / 10) * 100}
                strokeColor="#cf1322"
                showInfo={false}
                size="small"
              />
            </div>
            <div>
              <Row justify="space-between" style={{ marginBottom: 4 }}>
                <Text>🔥 热度面</Text>
                <Text strong>{sector.breakdown.heat.toFixed(2)}/10</Text>
              </Row>
              <Progress
                percent={(sector.breakdown.heat / 10) * 100}
                strokeColor="#fa8c16"
                showInfo={false}
                size="small"
              />
            </div>
            <div>
              <Row justify="space-between" style={{ marginBottom: 4 }}>
                <Text>⬆️ 动量面</Text>
                <Text strong>{sector.breakdown.momentum.toFixed(2)}/10</Text>
              </Row>
              <Progress
                percent={(sector.breakdown.momentum / 10) * 100}
                strokeColor="#52c41a"
                showInfo={false}
                size="small"
              />
            </div>
          </Space>
        </div>

        {/* 技术分析 */}
        <div>
          <Title level={5}>📈 技术分析</Title>
          <Space direction="vertical" size="small" style={{ width: '100%' }}>
            <Card size="small" style={{ background: '#fffbe6' }}>
              <div style={{ fontSize: 13 }}>
                <Text strong>K线形态：</Text>
                <Text>{sector.technical || '暂无'}</Text>
              </div>
            </Card>
            <Card size="small" style={{ background: '#f0f5ff' }}>
              <div style={{ fontSize: 13 }}>
                <Text strong>量能评价：</Text>
                <Text>{sector.volume || '暂无'}</Text>
              </div>
            </Card>
          </Space>
        </div>

        {/* 机会评价 */}
        <Card size="small" style={{ background: '#f6ffed', borderColor: '#52c41a' }}>
          <Title level={5} style={{ margin: '0 0 8px 0' }}>💡 机会评价</Title>
          <Text style={{ fontSize: 13, lineHeight: 1.6 }}>
            {sector.opportunity}
          </Text>
        </Card>

        {/* 行动建议 */}
        <Card size="small" style={{ background: '#e6f7ff', borderColor: '#1890ff' }}>
          <Title level={5} style={{ margin: '0 0 8px 0' }}>✓ 建议</Title>
          <ul style={{ margin: 0, paddingLeft: 16, fontSize: 13 }}>
            {sector.signal === 'STRONG' && (
              <>
                <li>信号强势，但需等待回踩确认</li>
                <li>不追分时急拉，风险/收益比不对</li>
              </>
            )}
            {sector.signal === 'WATCH' && (
              <>
                <li>信号一般，等价格和资金方向更清楚</li>
                <li>关注能否稳定在重要支撑位</li>
              </>
            )}
            {sector.signal === 'WEAK' && (
              <>
                <li>机会不足，先等止跌信号</li>
                <li>重点等资金回流和趋势修复</li>
              </>
            )}
          </ul>
        </Card>
      </Space>
    </Drawer>
  )
}

/**主看板*/
export default function SectorRankingBoard() {
  const [sortBy, setSortBy] = useState<SortBy>('score')
  const [filterSignal, setFilterSignal] = useState<FilterSignal>('all')
  const [selectedSector, setSelectedSector] = useState<SectorRankingItem | null>(null)
  const [drawerVisible, setDrawerVisible] = useState(false)

  // 获取排行数据
  const { data: rankingData, isLoading, refetch } = useQuery({
    queryKey: ['sector-rankings'],
    queryFn: async () => {
      return marketApi.getSectorRankings()
    },
    refetchInterval: 60_000, // 1分钟刷新
  })
  const rankingState = isLoading
    ? 'loading'
    : rankingData ? deriveDataState(rankingData.meta) : 'unavailable'

  // 过滤和排序
  const displayData = useMemo(() => {
    if (!rankingData?.data.allRankings) return []
    let filtered = rankingData.data.allRankings

    // 按信号过滤
    if (filterSignal !== 'all') {
      filtered = filtered.filter(s => s.signal.toLowerCase() === filterSignal.toUpperCase())
    }

    // 排序
    const sorted = [...filtered].sort((a, b) => {
      if (sortBy === 'score') {
        return b.baseScore - a.baseScore
      } else if (sortBy === 'change') {
        return b.changePct - a.changePct
      } else { // flow
        return b.flowValue - a.flowValue
      }
    })

    return sorted
  }, [rankingData, sortBy, filterSignal])

  const signalColors: Record<string, string> = {
    STRONG: '#cf1322',
    WATCH: '#fa8c16',
    WEAK: '#1f77b9',
    AVOID: '#999',
  }

  const signalLabels: Record<string, string> = {
    STRONG: '强势',
    WATCH: '观察',
    WEAK: '弱势',
    AVOID: '回避',
  }

  // 统计数据
  const statsData = useMemo(() => ({
    strong: rankingData?.data.strongSignals?.length ?? 0,
    watch: rankingData?.data.watchSignals?.length ?? 0,
    weak: rankingData?.data.weakSignals?.length ?? 0,
  }), [rankingData])

  const columns = [
    {
      title: '排名',
      dataIndex: 'rank',
      width: 60,
      render: (rank: number) => (
        <Text strong style={{ fontSize: 14 }}>{rank}</Text>
      ),
    },
    {
      title: '板块',
      dataIndex: 'name',
      width: 150,
      render: (_: any, record: SectorRankingItem) => (
        <div>
          <div style={{ fontWeight: 600, fontSize: 13 }}>{record.name}</div>
          <div style={{ fontSize: 11, color: '#999' }}>{record.matchedSector}</div>
        </div>
      ),
    },
    {
      title: '评分',
      dataIndex: 'baseScore',
      width: 100,
      sorter: (a: SectorRankingItem, b: SectorRankingItem) => a.baseScore - b.baseScore,
      render: (score: number) => (
        <div style={{ textAlign: 'center' }}>
          <div style={{
            fontSize: 14,
            fontWeight: 700,
            color: score > 7 ? '#cf1322' : score > 5 ? '#fa8c16' : '#666',
          }}>
            {score.toFixed(2)}
          </div>
          <Progress
            percent={(score / 10) * 100}
            size="small"
            showInfo={false}
            strokeColor={score > 7 ? '#cf1322' : score > 5 ? '#fa8c16' : '#1f77b9'}
          />
        </div>
      ),
    },
    {
      title: '涨跌',
      dataIndex: 'changePct',
      width: 80,
      sorter: (a: SectorRankingItem, b: SectorRankingItem) => a.changePct - b.changePct,
      render: (pct: number) => (
        <Text style={{
          color: pct > 0 ? '#cf1322' : pct < 0 ? '#3f8600' : '#666',
          fontWeight: 500,
          fontSize: 13,
        }}>
          {pct > 0 ? <ArrowUpOutlined /> : pct < 0 ? <ArrowDownOutlined /> : null}
          {' '}
          {pct > 0 ? '+' : ''}{pct.toFixed(2)}%
        </Text>
      ),
    },
    {
      title: '资金',
      dataIndex: 'flowValue',
      width: 100,
      sorter: (a: SectorRankingItem, b: SectorRankingItem) => a.flowValue - b.flowValue,
      render: (flow: number) => (
        <Text style={{
          color: flow > 0 ? '#cf1322' : flow < 0 ? '#3f8600' : '#666',
          fontWeight: 500,
          fontSize: 13,
        }}>
          {flow > 0 ? '+' : ''}{flow.toFixed(1)}亿
        </Text>
      ),
    },
    {
      title: '信号',
      dataIndex: 'signal',
      width: 80,
      render: (signal: string, record: SectorRankingItem) => (
        <Tooltip title={`置信度: ${(record.confidence * 100).toFixed(0)}%`}>
          <Badge
            count={signalLabels[signal]}
            style={{
              backgroundColor: signalColors[signal],
              fontSize: 11,
              padding: '2px 8px',
              borderRadius: 4,
              color: 'white',
            }}
          />
        </Tooltip>
      ),
    },
    {
      title: '操作',
      width: 80,
      render: (_: any, record: SectorRankingItem) => (
        <Button
          type="text"
          size="small"
          onClick={() => {
            setSelectedSector(record)
            setDrawerVisible(true)
          }}
        >
          详情
        </Button>
      ),
    },
  ]

  return (
    <div>
      {rankingData?.meta.isMock && <DemoDataBanner />}
      {/* 页面标题 */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 20 }}>
        <Col>
          <Title level={3} style={{ margin: 0 }}>📊 版块监控看板</Title>
        </Col>
        <Col>
          <Space>
            <Button icon={<ReloadOutlined />} size="small" onClick={() => { refetch() }}>
              刷新
            </Button>
          </Space>
        </Col>
      </Row>

      <DataStatePanel
        state={rankingState}
        meta={rankingData?.meta}
        onRetry={() => { refetch() }}
      >
      <div>
      {/* 统计卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} sm={8}>
          <Card size="small">
            <Statistic
              title="🔥 强势信号"
              value={statsData.strong}
              prefix={<span style={{ color: '#cf1322' }}>🔴</span>}
            />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card size="small">
            <Statistic
              title="📈 观察信号"
              value={statsData.watch}
              prefix={<span style={{ color: '#fa8c16' }}>🟠</span>}
            />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card size="small">
            <Statistic
              title="📉 弱势信号"
              value={statsData.weak}
              prefix={<span style={{ color: '#1f77b9' }}>🔵</span>}
            />
          </Card>
        </Col>
      </Row>

      {/* 控制栏 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Row gutter={[16, 16]} align="middle">
          <Col xs={24} sm={12}>
            <Space>
              <Text strong>排序:</Text>
              <Segmented
                value={sortBy}
                onChange={(val) => setSortBy(val as SortBy)}
                options={[
                  { label: '📊 评分', value: 'score' },
                  { label: '📈 涨跌', value: 'change' },
                  { label: '💰 资金', value: 'flow' },
                ]}
              />
            </Space>
          </Col>
          <Col xs={24} sm={12}>
            <Space>
              <Text strong>筛选:</Text>
              <Segmented
                value={filterSignal}
                onChange={(val) => setFilterSignal(val as FilterSignal)}
                options={[
                  { label: '全部', value: 'all' },
                  { label: '强势', value: 'strong' },
                  { label: '观察', value: 'watch' },
                  { label: '弱势', value: 'weak' },
                ]}
              />
            </Space>
          </Col>
        </Row>
      </Card>

      {/* 数据表 */}
      <Card
        size="small"
        extra={
          rankingData && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              共 {rankingData.data.totalSectors} 个板块 • 更新于 {new Date(rankingData.data.timestamp).toLocaleTimeString()}
            </Text>
          )
        }
      >
        {displayData.length === 0 ? (
          <Empty description="当前筛选条件下无数据" style={{ padding: 40 }} />
        ) : (
          <Table
            dataSource={displayData}
            columns={columns}
            pagination={{ pageSize: 20, showSizeChanger: true }}
            rowKey="rank"
            size="small"
            scroll={{ x: 1000 }}
            onRow={(record) => ({
              onClick: () => {
                setSelectedSector(record)
                setDrawerVisible(true)
              },
              style: { cursor: 'pointer' },
            })}
          />
        )}
      </Card>
      </div>
      </DataStatePanel>

      {/* 右侧详情抽屉 */}
      <SectorDetailDrawer
        sector={selectedSector}
        visible={drawerVisible}
        onClose={() => setDrawerVisible(false)}
      />
    </div>
  )
}
