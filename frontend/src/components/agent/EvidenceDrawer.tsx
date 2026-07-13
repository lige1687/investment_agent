import { useEffect, useState } from 'react'
import { Drawer, Descriptions, Tag, Typography, Spin, Alert, Space } from 'antd'
import { agentApi } from '@/api/agent'
import type { Evidence } from '@/types/agent'

const { Text, Paragraph } = Typography

interface Props {
  evId: string | null
  open: boolean
  onClose: () => void
}

/** Fetches an Evidence snapshot on open (lazy) and shows raw query + data.
 *  This is the click-through target from every `evidence_ref` tag in the
 *  decision card. */
export default function EvidenceDrawer({ evId, open, onClose }: Props) {
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<Evidence | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open || !evId) return
    setLoading(true)
    setError(null)
    setData(null)
    agentApi.getEvidence(evId)
      .then(r => setData(r.data))
      .catch(e => setError(e?.response?.data?.detail || e.message))
      .finally(() => setLoading(false))
  }, [evId, open])

  return (
    <Drawer
      title={<span style={{ fontFamily: 'monospace' }}>{evId}</span>}
      open={open}
      onClose={onClose}
      width={520}
      destroyOnClose
    >
      {loading && (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin /> <Text type="secondary">拉取证据快照...</Text>
        </div>
      )}
      {error && <Alert type="error" message={error} showIcon />}

      {data && (
        <>
          <Descriptions size="small" column={1} bordered>
            <Descriptions.Item label="来源">{data.source}</Descriptions.Item>
            <Descriptions.Item label="agent">{data.agent}</Descriptions.Item>
            <Descriptions.Item label="session">
              <Text style={{ fontFamily: 'monospace', fontSize: 12 }}>{data.session_id}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="拉取时间">{data.fetched_at}</Descriptions.Item>
            <Descriptions.Item label="TTL">
              <Space>
                <Tag color={data.is_fresh ? 'green' : 'default'}>
                  {data.is_fresh ? '新鲜' : '已过期'}
                </Tag>
                <span>{data.ttl_seconds === 0 ? '永久' : `${data.ttl_seconds}s`}</span>
              </Space>
            </Descriptions.Item>
          </Descriptions>

          <Paragraph strong style={{ marginTop: 16, marginBottom: 4 }}>调用参数</Paragraph>
          <pre style={{
            background: '#fafafa',
            padding: 12,
            borderRadius: 4,
            fontSize: 12,
            overflow: 'auto',
            border: '1px solid #f0f0f0',
          }}>
            {JSON.stringify(data.query, null, 2)}
          </pre>

          <Paragraph strong style={{ marginTop: 16, marginBottom: 4 }}>返回数据</Paragraph>
          <pre style={{
            background: '#fafafa',
            padding: 12,
            borderRadius: 4,
            fontSize: 12,
            overflow: 'auto',
            border: '1px solid #f0f0f0',
            maxHeight: 400,
          }}>
            {prettyJson(data.data)}
          </pre>
        </>
      )}
    </Drawer>
  )
}

function prettyJson(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
}
