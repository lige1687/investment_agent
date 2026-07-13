import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Col, InputNumber, Row, Space, Spin, Typography } from 'antd'
import { CommentOutlined, PlayCircleOutlined, ReloadOutlined } from '@ant-design/icons'

import { tradingRoomApi } from '@/api/tradingRoom'
import { portfolioApi } from '@/api/portfolio'
import { marketApi } from '@/api/market'
import type { TargetAllocation, TradingPolicy, TradingRoomSession } from '@/types/tradingRoom'
import DemoDataBanner from '@/components/common/DemoDataBanner'
import PolicyImportPanel from './PolicyImportPanel'
import ContextSnapshotCard from './ContextSnapshotCard'
import ExposureCard from './ExposureCard'
import ExecutionStatusCard from './ExecutionStatusCard'
import SpecialistRoundtable from './SpecialistRoundtable'
import ConflictPanel from './ConflictPanel'
import DecisionDraftPanel from './DecisionDraftPanel'

const { Paragraph, Text, Title } = Typography

interface ViewProps {
  policy: TradingPolicy
  session: TradingRoomSession | null
  policyLoading?: boolean
  actionLoading?: boolean
  onImportTargets?: (targets: TargetAllocation[]) => void
  onConfirm?: (amount: number) => void
}

export function TradingRoomView({
  policy,
  session,
  policyLoading,
  actionLoading,
  onImportTargets,
  onConfirm,
}: ViewProps) {
  return (
    <Space direction="vertical" size={14} style={{ width: '100%' }}>
      <PolicyImportPanel policy={policy} loading={policyLoading} onImport={onImportTargets} />
      {session?.context.data_mode === 'demo' && <DemoDataBanner />}
      {session && (
        <>
          {session.messages.filter(item => item.sender_role === 'system').map(item => (
            <Alert key={item.id} type="warning" showIcon message={item.content} />
          ))}
          <ContextSnapshotCard context={session.context} />
          <Row gutter={[12, 12]}>
            <Col xs={24} lg={12}><ExposureCard snapshots={session.exposure_snapshots} /></Col>
            <Col xs={24} lg={12}><ExecutionStatusCard snapshots={session.trade_status_snapshots} /></Col>
          </Row>
          <SpecialistRoundtable memos={session.specialist_memos} />
          <ConflictPanel memos={session.specialist_memos} />
          <DecisionDraftPanel
            decision={session.final_decision}
            contextActionable={session.context.formally_actionable}
            onConfirm={onConfirm}
            submitting={actionLoading}
          />
        </>
      )}
    </Space>
  )
}

export default function TradingRoomPage() {
  const [policy, setPolicy] = useState<TradingPolicy | null>(null)
  const [session, setSession] = useState<TradingRoomSession | null>(null)
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [cash, setCash] = useState(0)
  const [peakEquity, setPeakEquity] = useState(0)
  const [pendingBuy, setPendingBuy] = useState(0)
  const [consumedPurchaseToday, setConsumedPurchaseToday] = useState(0)

  const loadPolicy = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setPolicy(await tradingRoomApi.getCurrentPolicy())
    } catch (reason: any) {
      if (reason?.response?.status === 404) {
        try {
          setPolicy(await tradingRoomApi.importPolicy({
            template_id: 'mid-term-theme-v1', target_allocations: [],
          }))
        } catch {
          setError('默认策略模板载入失败')
        }
      } else {
        setError('交易政策读取失败')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void loadPolicy() }, [loadPolicy])

  const importTargets = async (targets: TargetAllocation[]) => {
    setWorking(true)
    setError(null)
    try {
      setPolicy(await tradingRoomApi.importPolicy({
        template_id: 'mid-term-theme-v1', target_allocations: targets,
      }))
    } catch {
      setError('目标仓位保存失败')
    } finally {
      setWorking(false)
    }
  }

  const startDiscussion = async () => {
    if (!policy?.ready) return
    setWorking(true)
    setError(null)
    try {
      const [portfolioResponse, indices] = await Promise.all([
        portfolioApi.getPortfolio(),
        marketApi.getIndices(['000001', 'IXIC']),
      ])
      const portfolio = portfolioResponse.data
      const now = new Date().toISOString()
      const equity = Math.max(1, Number(portfolio.total_value || 0) + cash)
      const confirmedPeakEquity = peakEquity > 0 ? Math.max(peakEquity, equity) : equity
      const fundPositions = portfolio.positions.filter(item => item.type === 'fund').slice(0, 8)
      const created = await tradingRoomApi.createSession({
        policy_version_id: policy.version_id,
        as_of: now,
        data_mode: indices.meta.mode,
        market_dates: { CN: now.slice(0, 10), US: now.slice(0, 10) },
        positions: portfolio.positions.map(item => ({ ...item })),
        cash,
        equity,
        peak_equity: confirmedPeakEquity,
        pending_orders: pendingBuy > 0 ? [{ side: 'buy', amount: pendingBuy }] : [],
        themes: Object.fromEntries(policy.target_allocations.map(item => [item.key, {}])),
        funds: Object.fromEntries(portfolio.positions.map(item => [item.symbol, { name: item.name }])),
        skill_versions: {},
        critical_inputs: [{
          key: 'market_indices',
          source: indices.meta.source,
          as_of: indices.meta.fetchedAt || null,
          confidence: indices.meta.status === 'ok' ? 'HIGH' : 'LOW',
          is_mock: indices.meta.isMock,
          stale: indices.meta.stale,
        }, {
          key: 'portfolio',
          source: 'yangjibao',
          as_of: now,
          confidence: portfolio.connected ? 'HIGH' : 'UNKNOWN',
          is_mock: false,
          stale: false,
        }, {
          key: 'account_peak_equity',
          source: 'user_confirmation',
          as_of: peakEquity > 0 ? now : null,
          confidence: peakEquity > 0 ? 'HIGH' : 'UNKNOWN',
          is_mock: false,
          stale: false,
        }],
        execution_channel: '支付宝',
        start_discussion: true,
      })
      const tradeStatuses = created.trade_status_snapshots
      const buyMemo = created.specialist_memos.find(item => item.role === 'buy' && item.state === 'completed')
      const themeMemo = created.specialist_memos.find(item => item.role === 'theme_fund' && item.state === 'completed')
      const riskMemo = created.specialist_memos.find(item => item.role === 'portfolio_risk' && item.state === 'completed')
      const score = Number(buyMemo?.memo.score)
      const suggested = buyMemo?.memo.suggested_range as { minimum?: unknown; maximum?: unknown } | undefined
      const targetFund = String(themeMemo?.memo.fund_code || fundPositions[0]?.symbol || '')
      const preflight = tradeStatuses.find(item => item.fund_code === targetFund) || tradeStatuses[0]
      const target = policy.target_allocations.find(item => item.scope === 'fund' && item.key === targetFund)
        || policy.target_allocations.find(item => item.scope === 'theme' && item.key === String(themeMemo?.memo.theme || ''))
      const positionValue = Number(portfolio.positions.find(item => item.symbol === targetFund)?.market_value || 0)
      if (
        Number.isFinite(score)
        && suggested
        && Number.isFinite(Number(suggested.minimum))
        && Number.isFinite(Number(suggested.maximum))
        && preflight
        && target
        && target.scope === 'fund'
      ) {
        const finalized = await tradingRoomApi.finalizeSession(created.session_id, {
          score,
          has_veto: riskMemo?.memo.new_buy_allowed === false,
          suggested_range: {
            minimum: Number(suggested.minimum), maximum: Number(suggested.maximum), currency: 'CNY',
          },
          preflight,
          guard_inputs: {
            consumed_purchase_today: consumedPurchaseToday,
            account_equity: equity,
            current_allocation_pct: positionValue / equity,
            target_allocation_pct: target.target_pct,
            available_cash: cash,
            pending_buy_amount: pendingBuy,
          },
        })
        setSession({ ...created, status: 'finalized', final_decision: finalized.decision })
      } else {
        setSession(created)
      }
    } catch (reason: any) {
      setError(reason?.response?.data?.detail || '今日讨论启动失败，请检查持仓、行情和 DeepSeek 配置')
    } finally {
      setWorking(false)
    }
  }

  const confirmAction = async (amount: number) => {
    if (!session) return
    setWorking(true)
    try {
      await tradingRoomApi.recordAction(session.session_id, {
        state: 'accepted', selected_amount: amount, note: '用户在今日讨论室确认',
      })
      setSession({ ...session, feedback_state: 'accepted', selected_amount: amount })
    } catch (reason: any) {
      setError(reason?.response?.data?.detail || '操作记录保存失败')
    } finally {
      setWorking(false)
    }
  }

  return (
    <div style={{ maxWidth: 1240, margin: '0 auto' }}>
      <Space align="start" style={{ width: '100%', justifyContent: 'space-between' }}>
        <div>
          <Title level={3} style={{ marginBottom: 2 }}><CommentOutlined /> 今日交易讨论室</Title>
          <Paragraph type="secondary">
            回答两个核心问题：今天哪些持仓要操作、操作多少；通信、纳斯达克等题材处于什么阶段。
          </Paragraph>
        </div>
        <Button icon={<ReloadOutlined />} onClick={loadPolicy}>刷新</Button>
      </Space>

      {error && <Alert type="error" showIcon message={error} closable onClose={() => setError(null)} style={{ marginBottom: 12 }} />}
      {loading || !policy ? <Spin /> : (
        <>
          <TradingRoomView
            policy={policy}
            session={session}
            policyLoading={working}
            actionLoading={working}
            onImportTargets={importTargets}
            onConfirm={confirmAction}
          />
          {policy.ready && !session && (
            <Card size="small" style={{ marginTop: 14 }}>
              <Space wrap>
                <Text>可用现金</Text>
                <Text>¥</Text>
                <InputNumber min={0} value={cash} onChange={value => setCash(Number(value || 0))} />
                <Text>账户近期峰值</Text>
                <Text>¥</Text>
                <InputNumber min={0} value={peakEquity} onChange={value => setPeakEquity(Number(value || 0))} />
                <Text>在途买入</Text>
                <Text>¥</Text>
                <InputNumber min={0} value={pendingBuy} onChange={value => setPendingBuy(Number(value || 0))} />
                <Text>今日已申购</Text>
                <Text>¥</Text>
                <InputNumber min={0} value={consumedPurchaseToday} onChange={value => setConsumedPurchaseToday(Number(value || 0))} />
                <Button type="primary" icon={<PlayCircleOutlined />} loading={working} onClick={startDiscussion}>
                  开始今日讨论
                </Button>
                <Text type="secondary">只读分析，不会自动下单</Text>
              </Space>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
