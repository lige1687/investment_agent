import type { ReactNode } from 'react'
import { Typography } from 'antd'

const { Text } = Typography

interface Props {
  index: number
  title: string
  hint?: string
  active?: boolean
  children: ReactNode
}

/**
 * Lightweight stage separator for a linear workflow (e.g. Trading Room).
 * Not a Steps component yet — this is the smallest possible visual hierarchy
 * that answers "what am I looking at" without changing behaviour.
 * We can upgrade this to <Steps/> + collapsible sections once the layout
 * pattern is confirmed.
 */
export default function SectionHeader({ index, title, hint, active, children }: Props) {
  return (
    <section>
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          gap: 12,
          padding: '4px 0 10px',
          borderBottom: active ? '2px solid #1677ff' : '1px solid #f0f0f0',
          marginBottom: 12,
        }}
      >
        <div
          style={{
            width: 26,
            height: 26,
            borderRadius: 13,
            background: active ? '#1677ff' : '#d9d9d9',
            color: '#fff',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 13,
            fontWeight: 600,
            alignSelf: 'center',
          }}
        >
          {index}
        </div>
        <Text strong style={{ fontSize: 15 }}>{title}</Text>
        {hint && <Text type="secondary" style={{ fontSize: 12 }}>{hint}</Text>}
      </div>
      {children}
    </section>
  )
}
