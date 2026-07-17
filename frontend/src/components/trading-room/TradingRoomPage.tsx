import { useCallback, useEffect, useState } from 'react'
import { Alert, Space, Spin } from 'antd'
import { CommentOutlined } from '@ant-design/icons'

import { portfolioApi } from '@/api/portfolio'
import { yangjibaoApi } from '@/api/yangjibao'
import PageContainer from '@/components/layout/PageContainer'
import SyncedAccountSummary from './SyncedAccountSummary'
import ConversationView from './ConversationView'

export default function TradingRoomPage() {
  const [portfolio, setPortfolio] = useState<{
    connected: boolean
    positions: Array<{ symbol: string, name: string, type: string,
                       market_value: number, [key: string]: any }>
    total_value: number
    synced_at?: string | null
  } | null>(null)
  const [loading, setLoading] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const loadPortfolio = useCallback(async () => {
    setLoading(true)
    try {
      const res = await portfolioApi.getPortfolio()
      setPortfolio(res.data)
    } catch {
      setNotice('持仓读取失败')
    } finally {
      setLoading(false)
    }
  }, [])

  const syncNow = useCallback(async () => {
    setLoading(true)
    try {
      await yangjibaoApi.syncPortfolio()
      await loadPortfolio()
    } catch (e: any) {
      setNotice(e?.response?.data?.detail || '同步失败')
    } finally {
      setLoading(false)
    }
  }, [loadPortfolio])

  useEffect(() => { void loadPortfolio() }, [loadPortfolio])

  return (
    <PageContainer
      title={<><CommentOutlined /> 今日交易讨论室</>}
      subtitle="问答式多专家讨论 · 真实仓位以养基宝同步为准"
    >
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        {notice && (
          <Alert type="warning" showIcon message={notice}
                 closable onClose={() => setNotice(null)} />
        )}
        <SyncedAccountSummary
          connected={portfolio?.connected ?? false}
          positionCount={portfolio?.positions?.length ?? 0}
          totalValue={portfolio?.total_value ?? 0}
          syncedAt={portfolio?.synced_at ?? null}
          loading={loading}
          onSync={syncNow}
        />
        {loading && !portfolio ? <Spin /> : <ConversationView />}
      </Space>
    </PageContainer>
  )
}
