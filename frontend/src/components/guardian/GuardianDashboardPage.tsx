import { useCallback, useEffect, useState } from 'react'
import {
  Card, Typography, Space, Tag, Button, Table, Empty,
  message as antdMessage, Statistic, Row, Col, Spin, Alert, Divider,
} from 'antd'
import {
  SafetyOutlined, PlayCircleOutlined, ReloadOutlined,
  AlertOutlined, CheckCircleOutlined, WarningOutlined,
} from '@ant-design/icons'
import { agentApi } from '@/api/agent'
import type {
  DecisionCard, GuardianRun, HoldingAlert,
} from '@/types/agent'
import DecisionCardView from '../agent/DecisionCardView'

const { Title, Text, Paragraph } = Typography

const SEV_COLOR: Record<string, string> = { HIGH: 'red', MEDIUM: 'orange', LOW: 'blue' }
const SLOT_LABEL: Record<string, string> = { midday: '午盘 11:30', close: '尾盘 14:30', manual: '临时' }

export default function GuardianDashboardPage() {
  const [runs, setRuns] = useState<GuardianRun[]>([])
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [selectedSid, setSelectedSid] = useState<string | null>(null)
  const [selectedCards, setSelectedCards] = useState<DecisionCard[]>([])
  const [cardsLoading, setCardsLoading] = useState(false)

  const loadRuns = useCallback(async () => {
    setLoading(true)
    try {
      const r = await agentApi.listGuardianRuns(15)
      setRuns(r.data.items)
      if (r.data.items.length > 0 && !selectedSid) {
        setSelectedSid(r.data.items[0].session_id)
      }
    } catch (e: any) {
      antdMessage.error('拉取历史扫描失败:' + (e?.response?.data?.detail || e.message))
    } finally {
      setLoading(false)
    }
  }, [selectedSid])

  useEffect(() => { loadRuns() }, [loadRuns])

  useEffect(() => {
    if (!selectedSid) {
      setSelectedCards([])
      return
    }
    setCardsLoading(true)
    agentApi.listSessionDecisions(selectedSid, 30)
      .then(r => setSelectedCards(r.data.items))
      .catch(() => setSelectedCards([]))
      .finally(() => setCardsLoading(false))
  }, [selectedSid])

  const handleRunNow = async () => {
    setRunning(true)
    try {
      const r = await agentApi.runGuardian('manual')
      antdMessage.success(
        `体检完成:${r.data.alert_count} 条预警 · ${r.data.decision_count} 张决策卡`,
      )
      setSelectedSid(r.data.session_id)
      await loadRuns()
    } catch (e: any) {
      antdMessage.error('体检失败:' + (e?.response?.data?.detail || e.message))
    } finally {
      setRunning(false)
    }
  }

  const selectedRun = runs.find(r => r.session_id === selectedSid) || null

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Title level={4} style={{ margin: 0 }}>
          <SafetyOutlined /> 持仓守护 Guardian
        </Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={loadRuns} loading={loading}>刷新</Button>
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            onClick={handleRunNow}
            loading={running}
          >
            立即体检
          </Button>
        </Space>
      </div>

      <Text type="secondary" style={{ fontSize: 12 }}>
        每工作日 11:30 午盘 / 14:30 尾盘自动体检,飞书推送。「立即体检」现在跑一次。
      </Text>

      <Divider style={{ margin: '16px 0' }} />

      <Row gutter={16}>
        {/* Left: run list */}
        <Col xs={24} md={10}>
          <Card size="small" title="历史扫描" bodyStyle={{ padding: 0 }}>
            <Table
              size="small"
              rowKey="session_id"
              dataSource={runs}
              pagination={false}
              loading={loading}
              rowClassName={r => r.session_id === selectedSid ? 'ant-table-row-selected' : ''}
              onRow={r => ({
                onClick: () => setSelectedSid(r.session_id),
                style: { cursor: 'pointer' },
              })}
              locale={{ emptyText: <Empty description="还没有扫描记录 · 点右上「立即体检」" /> }}
              columns={[
                {
                  title: '时段', dataIndex: 'slot', width: 100,
                  render: (s: string) => <Tag>{SLOT_LABEL[s] || s}</Tag>,
                },
                {
                  title: '时间', dataIndex: 'started_at', width: 150,
                  render: (t: string) => <Text style={{ fontSize: 11 }}>{new Date(t).toLocaleString('zh-CN')}</Text>,
                },
                {
                  title: '预警', dataIndex: 'alert_count', width: 60,
                  render: (n: number) => n > 0 ? <Tag color="orange">{n}</Tag> : <Tag color="green">0</Tag>,
                },
                {
                  title: '推送', dataIndex: 'pushed_to_feishu', width: 60,
                  render: (b: boolean) => b ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : <Text type="secondary">—</Text>,
                },
              ]}
            />
          </Card>
        </Col>

        {/* Right: details */}
        <Col xs={24} md={14}>
          {!selectedRun && <Empty description="选择左侧一次扫描查看详情" />}

          {selectedRun && (
            <>
              {/* Overview */}
              <Card size="small" title="扫描概览" style={{ marginBottom: 12 }}>
                {selectedRun.error && (
                  <Alert type="warning" showIcon message={`错误: ${selectedRun.error}`} style={{ marginBottom: 8 }} />
                )}
                <Row gutter={8}>
                  <Col span={8}>
                    <Statistic
                      title="预警数"
                      value={selectedRun.alert_count}
                      prefix={<AlertOutlined />}
                      valueStyle={{
                        fontSize: 20,
                        color: selectedRun.alert_count > 0 ? '#faad14' : '#52c41a',
                      }}
                    />
                  </Col>
                  <Col span={8}>
                    <Statistic
                      title="决策卡"
                      value={selectedRun.decision_count}
                      valueStyle={{ fontSize: 20 }}
                    />
                  </Col>
                  <Col span={8}>
                    <Statistic
                      title="LLM 参与"
                      value={selectedRun.llm_used ? '是' : '否(降级)'}
                      valueStyle={{
                        fontSize: 20,
                        color: selectedRun.llm_used ? '#52c41a' : '#8c8c8c',
                      }}
                    />
                  </Col>
                </Row>

                {selectedRun.portfolio_snapshot && (
                  <>
                    <Divider style={{ margin: '10px 0' }} />
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      总市值 ¥{Number(selectedRun.portfolio_snapshot.total_value || 0).toLocaleString()}
                      {' · '}
                      累计 {(selectedRun.portfolio_snapshot.total_pnl_pct ?? 0).toFixed(2)}%
                      {' · '}
                      持仓 {selectedRun.portfolio_snapshot.position_count} 只
                    </Text>
                  </>
                )}

                {selectedRun.briefing_text && (
                  <>
                    <Divider style={{ margin: '10px 0' }} />
                    <Paragraph style={{ fontSize: 12, whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                      {selectedRun.briefing_text}
                    </Paragraph>
                  </>
                )}
              </Card>

              {/* Rule alerts */}
              {selectedRun.alerts.length > 0 && (
                <Card
                  size="small"
                  title={<Space size={4}><WarningOutlined />规则触发的预警 ({selectedRun.alerts.length})</Space>}
                  style={{ marginBottom: 12 }}
                >
                  <Space direction="vertical" size={6} style={{ width: '100%' }}>
                    {selectedRun.alerts.map((a: HoldingAlert, i: number) => (
                      <div key={i} style={{
                        padding: '6px 8px',
                        background: a.severity === 'HIGH' ? '#fff2f0' : '#fffbe6',
                        borderRadius: 4,
                        fontSize: 12,
                      }}>
                        <Space size={4}>
                          <Tag color={SEV_COLOR[a.severity] || 'default'}>{a.severity}</Tag>
                          <Text strong style={{ fontSize: 12 }}>{a.name}</Text>
                          <Text code style={{ fontSize: 11 }}>{a.code}</Text>
                          <Tag>{a.trigger}</Tag>
                        </Space>
                        <div style={{ marginTop: 2, color: '#595959' }}>{a.note}</div>
                      </div>
                    ))}
                  </Space>
                </Card>
              )}

              {/* Decision cards */}
              <Card
                size="small"
                title={`本次生成的决策卡 (${selectedCards.length})`}
                loading={cardsLoading}
              >
                {selectedCards.length === 0 && !cardsLoading && (
                  <Empty description="无决策卡" />
                )}
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  {selectedCards.map(card => (
                    <DecisionCardView key={card.decision_id} card={card} />
                  ))}
                </Space>
              </Card>
            </>
          )}
        </Col>
      </Row>
    </div>
  )
}
