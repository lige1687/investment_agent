import { useEffect, useState } from 'react'
import { Divider, Tag, Typography, Button, Space, Empty, message as antdMessage } from 'antd'
import { BellOutlined, StopOutlined } from '@ant-design/icons'
import { agentApi } from '@/api/agent'
import type { MonitoringAlert } from '@/types/agent'

const { Text } = Typography

const TYPE_LABEL: Record<string, string> = {
  price_below: '跌破价',
  price_above: '涨破价',
  change_pct: '涨跌%',
  consecutive_down: '连续下跌',
  consecutive_up: '连续上涨',
  volume_spike: '成交异动',
  rank_change: '排名变化',
  technical: '综合(不自动触发)',
}

const TYPE_COLOR: Record<string, string> = {
  price_below: 'red',
  price_above: 'green',
  change_pct: 'orange',
  consecutive_down: 'red',
  consecutive_up: 'green',
  technical: 'default',
}

interface Props {
  decisionId: string
  monitoring: string[]  // original bullets — shown as fallback if no synthesized alerts
}

/** Shows the PriceAlert rows the backend auto-synthesized from the card's
 *  `monitoring[]` bullets. If synthesis produced nothing, we still show the
 *  raw bullets so the user isn't left thinking Guardian ignored them. */
export default function MonitoringAlertsPanel({ decisionId, monitoring }: Props) {
  const [alerts, setAlerts] = useState<MonitoringAlert[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [disabling, setDisabling] = useState(false)

  useEffect(() => {
    if (!decisionId) return
    setLoading(true)
    agentApi.listMonitoringAlerts(decisionId)
      .then(r => setAlerts(r.data.items))
      .catch(() => setAlerts([]))  // fail quietly — bullets still render below
      .finally(() => setLoading(false))
  }, [decisionId])

  const handleDisableAll = async () => {
    try {
      setDisabling(true)
      const r = await agentApi.disableMonitoringAlerts(decisionId)
      antdMessage.success(`已停止盯这 ${r.data.disabled_count} 条条件`)
      // Update local state so the buttons reflect enabled=false immediately
      setAlerts(prev => prev?.map(a => ({ ...a, enabled: false })) ?? null)
    } catch (e: any) {
      antdMessage.error('停止失败:' + (e?.response?.data?.detail || e.message))
    } finally {
      setDisabling(false)
    }
  }

  if (monitoring.length === 0 && (alerts ?? []).length === 0) return null

  const anyEnabled = (alerts ?? []).some(a => a.enabled)
  const enabledCount = (alerts ?? []).filter(a => a.enabled).length

  return (
    <>
      <Divider style={{ margin: '12px 0' }}>
        <Space size={4}>
          <BellOutlined />
          <span style={{ fontSize: 12 }}>
            监控条件 {enabledCount > 0 && `(${enabledCount} 条运行中)`}
          </span>
        </Space>
      </Divider>

      {loading && <Text type="secondary" style={{ fontSize: 12 }}>加载中...</Text>}

      {!loading && (alerts ?? []).length > 0 && (
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          {(alerts ?? []).map(a => (
            <div key={a.id} style={{
              padding: '6px 8px',
              background: a.enabled ? '#f6ffed' : '#fafafa',
              border: '1px solid #f0f0f0',
              borderRadius: 4,
              fontSize: 12,
              opacity: a.enabled ? 1 : 0.55,
            }}>
              <Space size={4} wrap>
                <Tag color={TYPE_COLOR[a.alert_type] || 'default'}>
                  {TYPE_LABEL[a.alert_type] || a.alert_type}
                </Tag>
                <Text code style={{ fontSize: 11 }}>{a.symbol}</Text>
                {a.alert_type !== 'technical' && (
                  <Text style={{ fontSize: 12 }}>
                    阈值 <b>{formatThreshold(a)}</b>
                  </Text>
                )}
                {!a.enabled && <Tag color="default">已禁用</Tag>}
              </Space>
              {a.note && (
                <div style={{ marginTop: 2, color: '#8c8c8c', fontSize: 11 }}>
                  {a.note}
                </div>
              )}
            </div>
          ))}

          {anyEnabled && (
            <Button
              size="small"
              icon={<StopOutlined />}
              onClick={handleDisableAll}
              loading={disabling}
              danger
            >
              全部停止监控
            </Button>
          )}
        </Space>
      )}

      {!loading && (alerts ?? []).length === 0 && monitoring.length > 0 && (
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            以下条件已保留(原文,尚未自动落表):
          </Text>
          {monitoring.map((m, i) => (
            <div key={i} style={{ fontSize: 12, color: '#595959' }}>• {m}</div>
          ))}
        </Space>
      )}
    </>
  )
}

function formatThreshold(a: MonitoringAlert): string {
  const t = a.alert_type
  if (t === 'change_pct') return `${a.threshold >= 0 ? '+' : ''}${a.threshold.toFixed(1)}%`
  if (t === 'price_below' || t === 'price_above') return a.threshold.toFixed(2)
  if (t === 'consecutive_down' || t === 'consecutive_up') return `${a.threshold.toFixed(0)} 日`
  return a.threshold.toString()
}
