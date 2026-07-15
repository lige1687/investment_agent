import { useMemo } from 'react'
import { Breadcrumb, Layout, Space, Tag, Tooltip } from 'antd'
import {
  CheckCircleFilled,
  ExclamationCircleFilled,
  CloseCircleFilled,
  ExperimentOutlined,
} from '@ant-design/icons'
import { Link, useLocation } from 'react-router-dom'
import { NAV_INDEX, ROOT_LABEL } from './navConfig'

const { Header } = Layout

interface DataHealth {
  status: 'healthy' | 'degraded' | 'down' | 'demo'
  label: string
  detail?: string
}

/**
 * Placeholder for the real hook that will subscribe to
 * market / portfolio / policy queries' `isMock/stale/error` flags.
 * We return a stub for now so the UI shape is settled.
 */
function useDataHealth(): DataHealth {
  return { status: 'healthy', label: '数据正常', detail: '所有数据源实时' }
}

function DataHealthPill({ health }: { health: DataHealth }) {
  const map = {
    healthy: { icon: <CheckCircleFilled />, color: 'success' as const },
    degraded: { icon: <ExclamationCircleFilled />, color: 'warning' as const },
    down: { icon: <CloseCircleFilled />, color: 'error' as const },
    demo: { icon: <ExperimentOutlined />, color: 'processing' as const },
  }
  const cfg = map[health.status]
  return (
    <Tooltip title={health.detail}>
      <Tag color={cfg.color} icon={cfg.icon} style={{ marginInlineEnd: 0 }}>
        {health.label}
      </Tag>
    </Tooltip>
  )
}

export default function MainHeader() {
  const location = useLocation()
  const health = useDataHealth()

  const crumbs = useMemo(() => {
    const entry = NAV_INDEX[location.pathname]
    if (!entry) return [{ title: ROOT_LABEL }]
    return [{ title: entry.group }, { title: entry.label }]
  }, [location.pathname])

  return (
    <Header
      style={{
        background: '#fff',
        padding: '0 24px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        borderBottom: '1px solid #f0f0f0',
        position: 'sticky',
        top: 0,
        zIndex: 5,
      }}
    >
      <Breadcrumb items={crumbs} />
      <Space size={12}>
        <DataHealthPill health={health} />
        <Tag color="blue" style={{ marginInlineEnd: 0 }}>
          <Link to="/settings" style={{ color: 'inherit' }}>实盘</Link>
        </Tag>
      </Space>
    </Header>
  )
}
