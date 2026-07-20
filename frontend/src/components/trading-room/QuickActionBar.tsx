import { Button, Space } from 'antd'
import {
  BulbOutlined, FireOutlined, SafetyCertificateOutlined, LineChartOutlined,
} from '@ant-design/icons'
import type { ReactNode } from 'react'
import type { PresetId } from '@/types/conversation'

const PRESETS: Array<{ id: PresetId, label: string, icon: ReactNode }> = [
  { id: 'daily_action', label: '🎯 今日操作', icon: <BulbOutlined /> },
  { id: 'discovery',    label: '🔍 机会发现', icon: <FireOutlined /> },
  { id: 'risk_scan',    label: '⚠️ 风险扫描', icon: <SafetyCertificateOutlined /> },
  { id: 'market_read',  label: '📊 市场解读', icon: <LineChartOutlined /> },
]

interface Props {
  onPreset: (id: PresetId) => void
  disabled?: boolean
}

export default function QuickActionBar({ onPreset, disabled }: Props) {
  return (
    <Space wrap size={8}>
      {PRESETS.map(p => (
        <Button
          key={p.id}
          icon={p.icon}
          disabled={disabled}
          onClick={() => onPreset(p.id)}
        >
          {p.label}
        </Button>
      ))}
    </Space>
  )
}
