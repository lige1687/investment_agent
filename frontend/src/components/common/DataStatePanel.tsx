import type { ReactNode } from 'react'
import { Alert, Button, Empty, Space, Spin, Typography } from 'antd'

import type { DataViewState, MarketDataMeta } from '@/types/dataTrust'

const { Text } = Typography

interface Props {
  state: DataViewState
  meta?: MarketDataMeta
  onRetry?: () => void
  children: ReactNode
}

export default function DataStatePanel({ state, meta, onRetry, children }: Props) {
  if (state === 'loading') {
    return (
      <Space direction="vertical" align="center" style={{ width: '100%', padding: 24 }}>
        <Spin />
        <Text type="secondary">正在获取数据</Text>
      </Space>
    )
  }

  if (state === 'empty') {
    return <Empty description={meta?.message || '数据源正常，当前无数据'} />
  }

  if (state === 'unavailable') {
    return (
      <Alert
        type="error"
        showIcon
        message="数据获取失败"
        description={meta?.message || '数据源当前不可用，请稍后重试'}
        action={onRetry ? <Button aria-label="重试" onClick={onRetry}>重试</Button> : undefined}
      />
    )
  }

  if (state === 'invalid') {
    return (
      <Alert
        type="error"
        showIcon
        message="数据格式异常，本次不用于决策"
        description={meta?.message || '关键字段缺失或未通过合理性校验'}
      />
    )
  }

  if (state === 'stale') {
    return (
      <Space direction="vertical" style={{ width: '100%' }}>
        <Alert
          type="warning"
          showIcon
          message={`数据已过期，最近成功时间：${meta?.fetchedAt || '未知'}`}
        />
        {children}
      </Space>
    )
  }

  if (state === 'demo') {
    return (
      <Space direction="vertical" style={{ width: '100%' }}>
        <Alert type="warning" showIcon message="演示数据，不可用于真实交易" />
        {children}
      </Space>
    )
  }

  return <>{children}</>
}
