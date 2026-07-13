import { Card, Col, Empty, Row, Space, Tag, Typography } from 'antd'
import type { SpecialistMemo } from '@/types/tradingRoom'

const { Paragraph, Text } = Typography

const ROLE_LABEL: Record<string, string> = {
  portfolio_risk: '组合风险',
  market_regime: '市场环境',
  theme_fund: '主题与基金',
  buy: '买入评估',
  sell_protection: '卖出与保护',
  skeptic: '证据质疑',
  recorder: '记录员',
  chair: '主持人',
}

export default function SpecialistRoundtable({ memos }: { memos: SpecialistMemo[] }) {
  if (!memos.length) return <Card size="small" title="专业讨论席"><Empty description="讨论尚未开始" /></Card>
  return (
    <Card size="small" title="专业讨论席">
      <Row gutter={[12, 12]}>
        {memos.map((item, index) => {
          const confidence = item.memo.confidence || item.memo.exposure_confidence
          return (
            <Col xs={24} md={12} key={`${item.role}-${index}`}>
              <Card size="small" type="inner" title={ROLE_LABEL[item.role] || item.role}>
                <Space wrap>
                  <Tag color={item.state === 'unavailable' ? 'red' : 'green'}>
                    {item.state === 'unavailable' ? '不可用' : '已完成'}
                  </Tag>
                  {confidence && <Tag>{confidence}</Tag>}
                </Space>
                <Paragraph style={{ margin: '8px 0' }}>
                  {String(item.memo.summary || item.memo.error || '无摘要')}
                </Paragraph>
                <Space wrap size={[4, 4]}>
                  {(item.memo.evidence_refs || []).map(ref => <Tag key={ref}>{ref}</Tag>)}
                  {Object.entries(item.skill_versions).map(([name, hash]) => (
                    <Text code key={name} title={`${name}: ${hash}`}>{hash.slice(0, 10)}…</Text>
                  ))}
                </Space>
              </Card>
            </Col>
          )
        })}
      </Row>
    </Card>
  )
}
