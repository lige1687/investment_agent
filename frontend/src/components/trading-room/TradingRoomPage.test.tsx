import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import TradingRoomPage, { TradingRoomView } from './TradingRoomPage'
import DecisionDraftPanel from './DecisionDraftPanel'
import SpecialistRoundtable from './SpecialistRoundtable'
import { tradingRoomApi } from '@/api/tradingRoom'
import type { TradingPolicy, TradingRoomSession } from '@/types/tradingRoom'

vi.mock('@/api/tradingRoom', () => ({
  tradingRoomApi: {
    getCurrentPolicy: vi.fn(),
    importPolicy: vi.fn(),
    createSession: vi.fn(),
    recordAction: vi.fn(),
  },
}))

const incompletePolicy: TradingPolicy = {
  template_id: 'mid-term-theme-v1',
  display_name: '中线题材波段',
  buy_obvious_threshold: 80,
  conditional_buy_min: 65,
  account_drawdown_warning_pct: 5,
  account_drawdown_derisk_pct: 7.5,
  account_drawdown_protection_pct: 10,
  percentage_stop_enabled: false,
  percentage_stop_pct: null,
  stop_priority: ['logic_failure', 'effective_trend_break', 'percentage_stop'],
  trend_break: {
    consecutive_closes_min: 2,
    consecutive_closes_max: 3,
    breakdown_magnitude_min_pct: 2,
    breakdown_magnitude_max_pct: 3,
    reclaim_required: true,
    volume_break_confirms: true,
  },
  version_id: 'policy-1',
  created_at: '2026-07-13T14:00:00+08:00',
  target_allocations: [],
  ready: false,
  missing_confirmations: ['target_allocations'],
}

const session: TradingRoomSession = {
  session_id: 'session-1',
  status: 'finalized',
  policy_version_id: 'policy-1',
  context: {
    as_of: '2026-07-13T14:30:00+08:00',
    data_mode: 'demo',
    market_dates: { CN: '2026-07-13', US: '2026-07-10' },
    positions: [],
    cash: 50000,
    equity: 100000,
    peak_equity: 102000,
    pending_orders: [],
    themes: {},
    funds: {},
    policy_version_id: 'policy-1',
    skill_versions: { 'batch-trading-router': 'router-hash' },
    critical_inputs: [{
      key: 'quotes', source: 'demo/mock', as_of: null,
      confidence: 'LOW', is_mock: true, stale: false,
    }],
    status: 'incomplete',
    formally_actionable: false,
    blockers: ['demo_data_mode', 'critical_input_mock:quotes'],
    context_hash: 'ctx-hash-1234567890',
  },
  specialist_memos: [{
    role: 'market_regime',
    state: 'completed',
    memo: {
      summary: '通信处于启动确认期', phase: 'startup',
      evidence_refs: ['ev-market-1'], confidence: 'MEDIUM',
    },
    skill_versions: { 'batch-trading-market-regime': 'sha256-abcdef123456' },
    created_at: '2026-07-13T14:31:00+08:00',
  }, {
    role: 'theme_fund', state: 'unavailable',
    memo: { error: 'verified_skill_unavailable' }, skill_versions: {},
    created_at: '2026-07-13T14:31:00+08:00',
  }],
  messages: [],
  exposure_snapshots: [{
    fund_code: '001513', theme: '信息产业', confidence: 'LOW',
    report_period_end: '2026-03-31',
  }],
  trade_status_snapshots: [{
    fund_code: '001513', share_class: 'A', channel: '支付宝',
    availability: 'UNKNOWN', queried_at: '2026-07-13T14:25:00+08:00',
  }],
  policy_proposals: [],
  final_decision: {
    action_class: 'IMMEDIATE',
    suggested_range: { minimum: 1000, maximum: 3000, currency: 'CNY' },
    guarded_range: null,
    immediately_executable: false,
    reasons: ['demo_data_mode'],
    applied_caps: [],
    score: 82,
    selected_amount: null,
    policy_version_id: 'policy-1',
    context_hash: 'ctx-hash-1234567890',
    manual_execution_only: true,
  },
  feedback_state: null,
  selected_amount: null,
  feedback_note: null,
  created_at: '2026-07-13T14:30:00+08:00',
  manual_execution_only: true,
}

describe('TradingRoomPage', () => {
  beforeEach(() => vi.clearAllMocks())

  it('cold-starts from the default template and asks only for target allocations', async () => {
    vi.mocked(tradingRoomApi.getCurrentPolicy).mockRejectedValue({ response: { status: 404 } })
    vi.mocked(tradingRoomApi.importPolicy).mockResolvedValue(incompletePolicy)

    render(<TradingRoomPage />)

    await waitFor(() => expect(tradingRoomApi.importPolicy).toHaveBeenCalledWith({
      template_id: 'mid-term-theme-v1', target_allocations: [],
    }))
    expect(await screen.findByText('还需确认目标仓位')).toBeInTheDocument()
    expect(screen.getByText(/不会像查户口一样逐项追问/)).toBeInTheDocument()
  })

  it('shows mock/incomplete reasons and disables executable confirmation', () => {
    render(<TradingRoomView policy={incompletePolicy} session={session} />)

    expect(screen.getByText('当前上下文不可用于实盘执行')).toBeInTheDocument()
    expect(screen.getAllByText(/demo_data_mode/).length).toBeGreaterThan(0)
    expect(screen.getByText('演示数据，不可用于真实交易')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '确认采用' })).toBeDisabled()
  })
})

describe('SpecialistRoundtable', () => {
  it('shows role, evidence, confidence, skill hash and unavailable state', () => {
    render(<SpecialistRoundtable memos={session.specialist_memos} />)
    expect(screen.getByText('市场环境')).toBeInTheDocument()
    expect(screen.getByText('MEDIUM')).toBeInTheDocument()
    expect(screen.getByText('ev-market-1')).toBeInTheDocument()
    expect(screen.getByText(/sha256-abc/)).toBeInTheDocument()
    expect(screen.getByText('主题与基金')).toBeInTheDocument()
    expect(screen.getByText('不可用')).toBeInTheDocument()
  })
})

describe('DecisionDraftPanel', () => {
  it('distinguishes conditional action and submits an amount inside guarded range', () => {
    const onConfirm = vi.fn()
    render(
      <DecisionDraftPanel
        decision={{
          ...session.final_decision!,
          action_class: 'CONDITIONAL',
          guarded_range: { minimum: 1000, maximum: 2000, currency: 'CNY' },
        }}
        contextActionable
        onConfirm={onConfirm}
      />,
    )
    expect(screen.getByText('条件操作')).toBeInTheDocument()
    expect(screen.getByText('建议区间：¥1,000 - ¥3,000')).toBeInTheDocument()
    expect(screen.getByText('护栏后：¥1,000 - ¥2,000')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '确认采用' }))
    expect(onConfirm).toHaveBeenCalledWith(1000)
  })
})
