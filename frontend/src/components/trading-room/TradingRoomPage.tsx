import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Col, Row, Space, Spin, Typography } from 'antd'
import { CommentOutlined, PlayCircleOutlined, ReloadOutlined } from '@ant-design/icons'

import { portfolioApi } from '@/api/portfolio'
import { tradingRoomApi } from '@/api/tradingRoom'
import { marketApi } from '@/api/market'
import type {
  ExecutionFundingInput,
  TargetAllocation,
  TradingPolicy,
  TradingRoomSession,
} from '@/types/tradingRoom'
import DemoDataBanner from '@/components/common/DemoDataBanner'
import PolicyImportPanel from './PolicyImportPanel'
import SyncedAccountSummary from './SyncedAccountSummary'
import ContextSnapshotCard from './ContextSnapshotCard'
import ExposureCard from './ExposureCard'
import ExecutionStatusCard from './ExecutionStatusCard'
import SpecialistRoundtable from './SpecialistRoundtable'
import ConflictPanel from './ConflictPanel'
import DecisionDraftPanel from './DecisionDraftPanel'
import ExecutionFundingPanel from './ExecutionFundingPanel'

const { Paragraph, Title } = Typography

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
  const [portfolio, setPortfolio] = useState<{ connected: boolean; positions: Array<{ symbol: string; name: string; type: string; market_value: number; [key: string]: any }>; total_value: number } | null>(null)
  const [portfolioLoading, setPortfolioLoading] = useState(false)
  const [pendingBuyDecision, setPendingBuyDecision] = useState<{
    sessionId: string
    sessionData: TradingRoomSession
    buyMemo: any
    themeMemo: any
    riskMemo: any
    targetFund: string
    preflight: any
    score: number
    suggested: any
  } | null>(null)

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

  // Load portfolio for account summary only.
  const loadPortfolio = useCallback(async () => {
    setPortfolioLoading(true)
    try {
      const res = await portfolioApi.getPortfolio()
      setPortfolio(res.data)
    } catch {
      // Silent — portfolio failure is not fatal for discussion start.
    } finally {
      setPortfolioLoading(false)
    }
  }, [])

  useEffect(() => { void loadPortfolio() }, [loadPortfolio])

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
      const indices = await marketApi.getIndices(['000001', 'IXIC'])
      const now = new Date().toISOString()
      const created = await tradingRoomApi.createSession({
        policy_version_id: policy.version_id,
        as_of: now,
        data_mode: indices.meta.mode,
        market_dates: { CN: now.slice(0, 10), US: now.slice(0, 10) },
        themes: Object.fromEntries(
          policy.target_allocations.map(item => [item.key, {}]),
        ),
        skill_versions: {},
        critical_inputs: [{
          key: 'market_indices',
          source: indices.meta.source,
          as_of: indices.meta.fetchedAt || null,
          confidence: indices.meta.status === 'ok' ? 'HIGH' : 'LOW',
          is_mock: indices.meta.isMock,
          stale: indices.meta.stale,
        }],
        execution_channel: '支付宝',
        start_discussion: true,
      })

      // Check if there's a buy candidate needing funding.
      const buyMemo = created.specialist_memos.find(
        item => item.role === 'buy' && item.state === 'completed',
      )
      const themeMemo = created.specialist_memos.find(
        item => item.role === 'theme_fund' && item.state === 'completed',
      )
      const riskMemo = created.specialist_memos.find(
        item => item.role === 'portfolio_risk' && item.state === 'completed',
      )
      const score = Number(buyMemo?.memo.score)
      const suggested = buyMemo?.memo.suggested_range as
        | { minimum?: unknown; maximum?: unknown }
        | undefined
      const targetFund = String(themeMemo?.memo.fund_code || '')
      const preflight = created.trade_status_snapshots.find(
        item => item.fund_code === targetFund,
      ) || created.trade_status_snapshots[0]

      if (
        Number.isFinite(score)
        && score >= policy.conditional_buy_min
        && suggested
        && Number.isFinite(Number(suggested.minimum))
        && Number.isFinite(Number(suggested.maximum))
        && targetFund
        && preflight
        && policy.target_allocations.some(
          t => (t.scope === 'fund' && t.key === targetFund) || t.scope === 'theme',
        )
      ) {
        // Show funding panel — don't finalize yet.
        setPendingBuyDecision({
          sessionId: created.session_id,
          sessionData: created,
          buyMemo,
          themeMemo,
          riskMemo,
          targetFund,
          preflight,
          score,
          suggested,
        })
      }
      setSession(created)
    } catch (reason: any) {
      setError(reason?.response?.data?.detail || '今日讨论启动失败')
    } finally {
      setWorking(false)
    }
  }

  const handleFundingConfirm = async (funding: ExecutionFundingInput) => {
    if (!pendingBuyDecision) return
    setWorking(true)
    setError(null)
    const { sessionId, sessionData, riskMemo, targetFund, preflight, score, suggested } = pendingBuyDecision
    try {
      const finalized = await tradingRoomApi.finalizeSession(sessionId, {
        score,
        has_veto: riskMemo?.memo.new_buy_allowed === false,
        suggested_range: {
          minimum: Number(suggested.minimum),
          maximum: Number(suggested.maximum),
          currency: 'CNY',
        },
        preflight,
        execution_funding: funding,
      })
      setSession({ ...sessionData, status: 'finalized', final_decision: finalized.decision })
      setPendingBuyDecision(null)
    } catch (reason: any) {
      setError(reason?.response?.data?.detail || '资金确认失败')
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
          <SyncedAccountSummary
            connected={portfolio?.connected ?? false}
            positionCount={portfolio?.positions?.length ?? 0}
            totalValue={portfolio?.total_value ?? 0}
            syncedAt={(portfolio as any)?.synced_at ?? null}
            loading={portfolioLoading}
          />
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
                <Button type="primary" icon={<PlayCircleOutlined />} loading={working} onClick={startDiscussion}>
                  开始今日讨论
                </Button>
                <span style={{ fontSize: 12, color: '#888' }}>只读分析，不会自动下单</span>
              </Space>
            </Card>
          )}
          {pendingBuyDecision && (
            <ExecutionFundingPanel
              onConfirm={handleFundingConfirm}
              loading={working}
            />
          )}
        </>
      )}
    </div>
  )
}
