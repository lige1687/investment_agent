/**
 * Central navigation config used by both the sidebar and the breadcrumb.
 * Placeholder pages (funds/signals/alerts) are kept in the routes but
 * hidden from the menu until their real UI ships.
 */
import type { ReactNode } from 'react'
import {
  DashboardOutlined,
  LineChartOutlined,
  HeatMapOutlined,
  WalletOutlined,
  CommentOutlined,
  RobotOutlined,
  FundProjectionScreenOutlined,
  SafetyOutlined,
  SettingOutlined,
} from '@ant-design/icons'

export const ROOT_LABEL = '基金决策工作台'

export interface NavItem {
  key: string
  label: string
  icon: ReactNode
}

export interface NavGroup {
  key: string
  label: string
  items: NavItem[]
}

export const NAV_GROUPS: NavGroup[] = [
  {
    key: 'market',
    label: '市场',
    items: [
      { key: '/', label: '概览', icon: <DashboardOutlined /> },
      { key: '/market', label: '行情', icon: <LineChartOutlined /> },
      { key: '/sectors', label: '版块监控', icon: <HeatMapOutlined /> },
    ],
  },
  {
    key: 'mine',
    label: '我的',
    items: [
      { key: '/portfolio', label: '持仓', icon: <WalletOutlined /> },
    ],
  },
  {
    key: 'decide',
    label: '决策',
    items: [
      { key: '/trading-room', label: '讨论室', icon: <CommentOutlined /> },
      { key: '/agent', label: 'AI 助手', icon: <RobotOutlined /> },
    ],
  },
  {
    key: 'tools',
    label: '工具',
    items: [
      { key: '/backtest', label: '回测', icon: <FundProjectionScreenOutlined /> },
      { key: '/guardian', label: '守护', icon: <SafetyOutlined /> },
      { key: '/settings', label: '设置', icon: <SettingOutlined /> },
    ],
  },
]

/** path → { group, label } for breadcrumb lookups. */
export const NAV_INDEX: Record<string, { group: string; label: string }> = NAV_GROUPS.reduce(
  (acc, group) => {
    for (const item of group.items) {
      acc[item.key] = { group: group.label, label: item.label }
    }
    return acc
  },
  {} as Record<string, { group: string; label: string }>,
)
