import { Alert, Card, Empty, Space, Tag, Typography } from 'antd'
import type { SpecialistMemo } from '@/types/tradingRoom'

const { Text } = Typography

export default function ConflictPanel({ memos }: { memos: SpecialistMemo[] }) {
  const skeptic = memos.filter(item => item.role === 'skeptic')
  const findings = skeptic.flatMap(item => Array.isArray(item.memo.findings) ? item.memo.findings : [])
  return (
    <Card size="small" title="共识、分歧与证据质疑">
      {!findings.length ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有进入正式列表的证据质疑" /> : (
        <Space direction="vertical" style={{ width: '100%' }}>
          {findings.map((finding, index) => (
            <Alert
              key={index}
              type="warning"
              showIcon
              message={String(finding.description || finding.issue_type || '证据问题')}
              description={(
                <Space wrap>
                  <Text>{String(finding.impact || '')}</Text>
                  {finding.evidence_ref ? <Tag>{String(finding.evidence_ref)}</Tag> : null}
                  {finding.missing_field ? <Tag color="orange">缺少 {String(finding.missing_field)}</Tag> : null}
                </Space>
              )}
            />
          ))}
        </Space>
      )}
    </Card>
  )
}
