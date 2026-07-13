import { Layout, Tag, Space } from 'antd'
import { ClockCircleOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

const { Header } = Layout

export default function HeaderBar() {
  const now = dayjs()
  const hour = now.hour()
  const minute = now.minute()
  const isMarketOpen =
    (hour === 9 && minute >= 30) ||
    (hour === 10) ||
    (hour === 11 && minute <= 30) ||
    (hour === 13) ||
    (hour === 14) ||
    (hour === 15 && minute === 0)

  return (
    <Header
      style={{
        background: '#fff',
        padding: '0 24px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        borderBottom: '1px solid #f0f0f0',
      }}
    >
      <Space>
        <ClockCircleOutlined />
        <span>{now.format('YYYY-MM-DD HH:mm:ss')}</span>
      </Space>
      <Space>
        <Tag color={isMarketOpen ? 'green' : 'default'}>
          {isMarketOpen ? '🔴 交易中' : '⚪ 休市'}
        </Tag>
      </Space>
    </Header>
  )
}
