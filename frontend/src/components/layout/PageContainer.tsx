import type { ReactNode } from 'react'
import { Space, Typography } from 'antd'

const { Title, Paragraph } = Typography

interface Props {
  title?: ReactNode
  subtitle?: ReactNode
  extra?: ReactNode
  children: ReactNode
  /** 宽度收敛。'default' = 1280,'wide' = 1440,'full' = 100% */
  size?: 'default' | 'wide' | 'full'
}

const MAX_WIDTH = { default: 1280, wide: 1440, full: '100%' } as const

/**
 * Unified page shell. Owns:
 *  - max-width & centering (previously scattered per-page)
 *  - title / subtitle / right-side actions
 *  - vertical rhythm between sections
 * Pages should stop wrapping themselves in a top-level `Card` so we avoid the
 * "card in card" visual noise.
 */
export default function PageContainer({
  title,
  subtitle,
  extra,
  children,
  size = 'default',
}: Props) {
  return (
    <div style={{ maxWidth: MAX_WIDTH[size], margin: '0 auto', width: '100%' }}>
      {(title || extra) && (
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            gap: 16,
            marginBottom: 16,
          }}
        >
          <div style={{ minWidth: 0 }}>
            {title && (
              <Title level={3} style={{ margin: 0, lineHeight: 1.25 }}>
                {title}
              </Title>
            )}
            {subtitle && (
              <Paragraph type="secondary" style={{ marginTop: 4, marginBottom: 0 }}>
                {subtitle}
              </Paragraph>
            )}
          </div>
          {extra && <Space wrap>{extra}</Space>}
        </div>
      )}
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {children}
      </Space>
    </div>
  )
}
