import { useEffect, useMemo, useState } from 'react'
import {
  Card, Space, Tag, Row, Col, Typography, Descriptions, Divider, Button,
  Progress, Empty, Alert, message as antdMessage,
} from 'antd'
import {
  RadarChartOutlined, WarningOutlined, CheckCircleOutlined,
  ThunderboltOutlined, EyeOutlined, CloseCircleOutlined,
  ExperimentOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'
import type {
  DecisionCard,
  Dimension,
  DimensionKey,
} from '@/types/agent'
import { agentApi } from '@/api/agent'
import EvidenceDrawer from './EvidenceDrawer'
import MonitoringAlertsPanel from './MonitoringAlertsPanel'

const { Text, Title, Paragraph } = Typography

// 6 dimensions in canonical order — same axes every time so radars are comparable.
const DIM_ORDER: DimensionKey[] = [
  'technical', 'capital', 'macro', 'news', 'financial', 'consensus',
]

const DIM_LABEL: Record<DimensionKey, string> = {
  technical: '技术面',
  capital: '资金面',
  macro: '宏观面',
  news: '消息面',
  financial: '财务面',
  consensus: '机构面',
}

const URGENCY_COLOR: Record<string, string> = {
  HIGH: 'red',
  MEDIUM: 'orange',
  LOW: 'blue',
}

const VERB_COLOR: Record<string, string> = {
  BUY: 'green', ADD: 'green',
  HOLD: 'blue', WATCH: 'blue',
  REDUCE: 'orange', SELL: 'red', AVOID: 'red',
}

const TYPE_LABEL: Record<string, string> = {
  BUY_CANDIDATE: '买入建议',
  SELL_ALERT: '卖出预警',
  REBALANCE: '组合调整',
  WATCH: '关注',
  NONE: '无',
}

const ROLE_LABEL: Record<string, string> = {
  COMPLEMENT: '补齐(降波动)',
  STRENGTHEN: '加强(已有暴露)',
  DUPLICATE: '重叠',
  NEW: '全新方向',
}

interface Props {
  card: DecisionCard
  onActionMarked?: (action: 'accepted' | 'ignored' | 'partial') => void
}

export default function DecisionCardView({ card, onActionMarked }: Props) {
  const [evOpen, setEvOpen] = useState<string | null>(null)
  const [actionSubmitting, setActionSubmitting] = useState<string | null>(null)
  const [simulatedEvidence, setSimulatedEvidence] = useState(false)

  // Detect whether any of this card's evidence snapshots carry a
  // `data_source: simulated` flag. We check lazily against the API on mount
  // so the warning banner only appears when there's a real reliability
  // issue, without needing the backend to pre-compute it.
  useEffect(() => {
    let cancelled = false
    async function check() {
      const refs = card.evidence_refs.slice(0, 6) // cap to a few probes
      if (refs.length === 0) return
      const results = await Promise.allSettled(
        refs.map(id => agentApi.getEvidence(id)),
      )
      if (cancelled) return
      for (const r of results) {
        if (r.status !== 'fulfilled') continue
        try {
          const parsed = JSON.parse(r.value.data.data)
          if (parsed?.data_source === 'simulated') {
            setSimulatedEvidence(true)
            return
          }
        } catch { /* not JSON, skip */ }
      }
    }
    check()
    return () => { cancelled = true }
  }, [card.evidence_refs])

  // A missing dimension should read as "该维度暂无数据" — visually a light-grey
  // dashed outline at mid-scale rather than a solid 0-score. We build two
  // radar series: solid coloured for present dims, dashed grey for absent.
  const radarOption: EChartsOption = useMemo(() => {
    const byKey = new Map(card.dimensions.map(d => [d.key, d]))
    const presentValues = DIM_ORDER.map(k => byKey.get(k)?.score ?? null)
    const missingValues = DIM_ORDER.map(k => byKey.has(k) ? null : 5)

    return {
      radar: {
        indicator: DIM_ORDER.map(k => ({
          name: byKey.has(k) ? DIM_LABEL[k] : `${DIM_LABEL[k]}(暂无)`,
          max: 10,
        })),
        radius: '65%',
        splitNumber: 5,
        axisName: {
          color: '#666',
          fontSize: 12,
          formatter: (name?: string) => {
            const label = name ?? ''
            return label.includes('暂无') ? `{missing|${label}}` : label
          },
          rich: { missing: { color: '#bfbfbf' } },
        },
        splitLine: { lineStyle: { color: '#eee' } },
        splitArea: { areaStyle: { color: ['#fff', '#fafafa'] } },
      },
      series: [
        {
          type: 'radar',
          data: [{
            value: presentValues,
            name: '当前评估',
            areaStyle: { color: 'rgba(22,119,255,0.20)' },
            lineStyle: { color: '#1677ff', width: 2 },
            symbol: 'circle',
            symbolSize: 4,
            itemStyle: { color: '#1677ff' },
          }],
        },
        {
          type: 'radar',
          data: [{
            value: missingValues,
            name: '缺失维度',
            symbol: 'none',
            lineStyle: { color: '#d9d9d9', width: 1, type: 'dashed' },
            areaStyle: { color: 'rgba(0,0,0,0)' },
            itemStyle: { color: '#d9d9d9' },
            silent: true,
            tooltip: { show: false },
          }],
        },
      ],
    }
  }, [card.dimensions])

  const missingKeys = useMemo(
    () => DIM_ORDER.filter(k => !card.dimensions.some(d => d.key === k)),
    [card.dimensions],
  )

  const handleAction = async (action: 'accepted' | 'ignored' | 'partial') => {
    try {
      setActionSubmitting(action)
      await agentApi.markDecisionAction(card.decision_id, action)
      antdMessage.success(`已标记为「${action === 'accepted' ? '接受' : action === 'ignored' ? '忽略' : '部分接受'}」`)
      onActionMarked?.(action)
    } catch (e: any) {
      antdMessage.error('标记失败:' + (e?.response?.data?.detail || e.message))
    } finally {
      setActionSubmitting(null)
    }
  }

  const conf = card.action.confidence
  const urgencyColor = URGENCY_COLOR[card.action.urgency] || 'default'
  const verbColor = VERB_COLOR[card.action.verb] || 'default'

  return (
    <Card
      size="small"
      style={{ borderLeft: `4px solid var(--ant-color-${urgencyColor}, #1677ff)`, marginTop: 8 }}
      bodyStyle={{ padding: 12 }}
    >
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
        <div style={{ flex: 1 }}>
          <Space size={6} wrap>
            <Tag color={verbColor} style={{ fontWeight: 600 }}>{card.action.verb}</Tag>
            <Tag color={urgencyColor}>紧迫度 {card.action.urgency}</Tag>
            <Tag>{TYPE_LABEL[card.type] || card.type}</Tag>
            <Text type="secondary" style={{ fontSize: 12 }}>
              信心 {(conf * 100).toFixed(0)}%
            </Text>
          </Space>
          {card.headline && (
            <Title level={5} style={{ marginTop: 8, marginBottom: 4 }}>
              {card.headline}
            </Title>
          )}
          <Text type="secondary" style={{ fontSize: 12 }}>
            目标:{card.target.name}
            {card.target.code && ` (${card.target.code})`}
            {' · '}
            {card.agent} · {new Date(card.created_at).toLocaleString('zh-CN')}
          </Text>
        </div>
      </div>

      {/* Data source warning — if any evidence was simulated, tell the user
          the whole card is illustrative, not actionable. */}
      {simulatedEvidence && (
        <Alert
          type="warning"
          showIcon
          icon={<ExperimentOutlined />}
          message="当前市场数据为模拟数据(尚未接同花顺 skill)"
          description="以下决策仅供 UI 演示,请勿据此实际操作。真正接入行情源后,该提示会自动消失。"
          style={{ marginTop: 8, marginBottom: 8 }}
        />
      )}

      {/* Summary */}
      {card.summary && (
        <Paragraph style={{ marginTop: 12, marginBottom: 8, fontSize: 13 }}>
          {card.summary}
        </Paragraph>
      )}

      {/* 6 维雷达 + 每维详情 */}
      {card.dimensions.length > 0 && (
        <>
          <Divider style={{ margin: '12px 0' }}>
            <Space size={4}>
              <RadarChartOutlined />
              <span style={{ fontSize: 12 }}>
                维度评估 · {card.dimensions.length} / 6
              </span>
            </Space>
          </Divider>
          <Row gutter={16}>
            <Col xs={24} md={10}>
              <ReactECharts option={radarOption} style={{ height: 240 }} notMerge lazyUpdate />
            </Col>
            <Col xs={24} md={14}>
              <DimensionList dimensions={card.dimensions} onEvidenceClick={setEvOpen} />
              {missingKeys.length > 0 && (
                <div style={{
                  marginTop: 8,
                  padding: '6px 8px',
                  background: '#fafafa',
                  border: '1px dashed #d9d9d9',
                  borderRadius: 4,
                  fontSize: 11,
                  color: '#8c8c8c',
                }}>
                  暂无数据的维度:
                  {' '}
                  {missingKeys.map(k => (
                    <Tag key={k} style={{ fontSize: 10, color: '#8c8c8c', background: 'transparent' }}>
                      {DIM_LABEL[k]}
                    </Tag>
                  ))}
                  <div style={{ marginTop: 2 }}>
                    (该维度的数据源尚未接通,故未参与评估)
                  </div>
                </div>
              )}
            </Col>
          </Row>
        </>
      )}

      {/* Conflicts */}
      {card.conflicts.length > 0 && (
        <>
          <Divider style={{ margin: '12px 0' }}>
            <Space size={4}><WarningOutlined /><span style={{ fontSize: 12 }}>维度分歧</span></Space>
          </Divider>
          <Space direction="vertical" size={4} style={{ width: '100%' }}>
            {card.conflicts.map((c, i) => (
              <Card key={i} size="small" style={{ background: '#fff7e6' }} bodyStyle={{ padding: 8 }}>
                <Space size={4}>
                  {c.between.map(k => <Tag key={k} color="orange">{DIM_LABEL[k] || k}</Tag>)}
                </Space>
                <div style={{ fontSize: 12, marginTop: 4, color: '#8c4a00' }}>{c.note}</div>
              </Card>
            ))}
          </Space>
        </>
      )}

      {/* Portfolio context */}
      {card.portfolio_context && (
        <>
          <Divider style={{ margin: '12px 0' }}>
            <span style={{ fontSize: 12 }}>组合上下文</span>
          </Divider>
          <Descriptions size="small" column={1} bordered>
            <Descriptions.Item label="定位">
              <Tag color={card.portfolio_context.role === 'DUPLICATE' ? 'red' :
                          card.portfolio_context.role === 'STRENGTHEN' ? 'orange' :
                          card.portfolio_context.role === 'COMPLEMENT' ? 'green' : 'blue'}>
                {ROLE_LABEL[card.portfolio_context.role || 'NEW']}
              </Tag>
            </Descriptions.Item>
            {(card.portfolio_context.overlap_with_holdings || []).length > 0 && (
              <Descriptions.Item label="重叠">
                {(card.portfolio_context.overlap_with_holdings || []).map((o, i) => (
                  <div key={i} style={{ fontSize: 12 }}>{o}</div>
                ))}
              </Descriptions.Item>
            )}
            {card.portfolio_context.warning && (
              <Descriptions.Item label="风险">
                <Text type="warning" style={{ fontSize: 12 }}>{card.portfolio_context.warning}</Text>
              </Descriptions.Item>
            )}
          </Descriptions>
        </>
      )}

      {/* Execution plan */}
      {card.execution_plan && hasExecutionData(card.execution_plan) && (
        <>
          <Divider style={{ margin: '12px 0' }}>
            <Space size={4}><ThunderboltOutlined /><span style={{ fontSize: 12 }}>执行方案</span></Space>
          </Divider>
          <Descriptions size="small" column={{ xs: 1, sm: 2 }} bordered>
            {card.execution_plan.position_size_pct && (
              <Descriptions.Item label="仓位">
                {card.execution_plan.position_size_pct}
              </Descriptions.Item>
            )}
            {card.execution_plan.entry && (
              <Descriptions.Item label="入场">
                {[
                  card.execution_plan.entry.style,
                  card.execution_plan.entry.batches ? `分 ${card.execution_plan.entry.batches} 批` : null,
                  card.execution_plan.entry.trigger,
                ].filter(Boolean).join(' · ')}
              </Descriptions.Item>
            )}
            {card.execution_plan.stop_loss && (
              <Descriptions.Item label="止损">
                <Text type="danger">{card.execution_plan.stop_loss.type} @ {card.execution_plan.stop_loss.value}</Text>
              </Descriptions.Item>
            )}
            {(card.execution_plan.take_profit?.levels || []).length > 0 && (
              <Descriptions.Item label="止盈">
                {(card.execution_plan.take_profit?.levels || []).map((lvl, i) => (
                  <div key={i} style={{ fontSize: 12 }}>
                    <Tag color="green">{lvl.at}</Tag>
                    <span>{lvl.action}</span>
                  </div>
                ))}
              </Descriptions.Item>
            )}
          </Descriptions>
        </>
      )}

      {/* Monitoring alerts (rendered from PriceAlert rows the backend
          auto-synthesized from `monitoring[]`) */}
      <MonitoringAlertsPanel decisionId={card.decision_id} monitoring={card.monitoring} />

      {/* Evidence refs (top level) */}
      {card.evidence_refs.length > 0 && (
        <>
          <Divider style={{ margin: '12px 0' }}>
            <Space size={4}><EyeOutlined /><span style={{ fontSize: 12 }}>证据链</span></Space>
          </Divider>
          <Space size={4} wrap>
            {card.evidence_refs.map(ref => (
              <Tag
                key={ref}
                color="blue"
                style={{ cursor: 'pointer', fontFamily: 'monospace', fontSize: 11 }}
                onClick={() => setEvOpen(ref)}
              >
                {ref}
              </Tag>
            ))}
          </Space>
        </>
      )}

      {/* Action buttons */}
      <Divider style={{ margin: '12px 0' }} />
      <Space wrap>
        <Button
          type="primary"
          size="small"
          icon={<CheckCircleOutlined />}
          loading={actionSubmitting === 'accepted'}
          onClick={() => handleAction('accepted')}
        >
          接受
        </Button>
        <Button
          size="small"
          onClick={() => handleAction('partial')}
          loading={actionSubmitting === 'partial'}
        >
          部分接受
        </Button>
        <Button
          size="small"
          icon={<CloseCircleOutlined />}
          onClick={() => handleAction('ignored')}
          loading={actionSubmitting === 'ignored'}
        >
          忽略
        </Button>
        <Text type="secondary" style={{ fontSize: 11 }}>
          {card.disclaimer}
        </Text>
      </Space>

      {/* Evidence drawer */}
      <EvidenceDrawer
        evId={evOpen}
        open={evOpen !== null}
        onClose={() => setEvOpen(null)}
      />
    </Card>
  )
}

function hasExecutionData(ep: NonNullable<DecisionCard['execution_plan']>) {
  return Boolean(
    ep.position_size_pct
    || ep.entry
    || ep.stop_loss
    || (ep.take_profit?.levels || []).length > 0,
  )
}

function DimensionList({
  dimensions,
  onEvidenceClick,
}: {
  dimensions: Dimension[]
  onEvidenceClick: (id: string) => void
}) {
  if (dimensions.length === 0) return <Empty description="无维度数据" />

  return (
    <Space direction="vertical" size={6} style={{ width: '100%' }}>
      {dimensions.map(d => {
        const scorePct = (d.score / 10) * 100
        const scoreColor =
          d.score >= 7 ? '#52c41a' : d.score >= 4 ? '#faad14' : '#ff4d4f'
        return (
          <div key={d.key} style={{ fontSize: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
              <Text strong style={{ fontSize: 12 }}>{DIM_LABEL[d.key] || d.key}</Text>
              <Text style={{ color: scoreColor, fontWeight: 600 }}>
                {d.score.toFixed(1)} / 10
              </Text>
            </div>
            <Progress
              percent={scorePct}
              showInfo={false}
              size="small"
              strokeColor={scoreColor}
            />
            <div style={{ marginTop: 2, color: '#595959' }}>
              {d.signal}
              {d.evidence_ref && (
                <Tag
                  color="blue"
                  style={{
                    marginLeft: 6, cursor: 'pointer',
                    fontFamily: 'monospace', fontSize: 10,
                  }}
                  onClick={() => onEvidenceClick(d.evidence_ref!)}
                >
                  {d.evidence_ref}
                </Tag>
              )}
            </div>
          </div>
        )
      })}
    </Space>
  )
}
