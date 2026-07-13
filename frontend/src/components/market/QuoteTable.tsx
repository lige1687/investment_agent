import { Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { QuoteData } from '@/types/market'

interface Props {
  data: QuoteData[]
  loading?: boolean
  onRowClick?: (symbol: string) => void
}

export default function QuoteTable({ data, loading, onRowClick }: Props) {
  const columns: ColumnsType<QuoteData> = [
    {
      title: '代码',
      dataIndex: 'symbol',
      key: 'symbol',
      width: 100,
      render: (v: string) => <Tag>{v}</Tag>,
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 120,
    },
    {
      title: '最新价',
      dataIndex: 'price',
      key: 'price',
      width: 100,
      align: 'right',
      render: (v: number) => v?.toFixed(3) || '-',
    },
    {
      title: '涨跌额',
      dataIndex: 'change',
      key: 'change',
      width: 100,
      align: 'right',
      render: (v: number) => (
        <span style={{ color: v > 0 ? '#cf1322' : v < 0 ? '#3f8600' : '#666' }}>
          {v > 0 ? '+' : ''}{v?.toFixed(3) || '-'}
        </span>
      ),
    },
    {
      title: '涨跌幅',
      dataIndex: 'changePct',
      key: 'changePct',
      width: 100,
      align: 'right',
      render: (v: number) => (
        <Tag color={v > 0 ? 'red' : v < 0 ? 'green' : 'default'}>
          {v > 0 ? '+' : ''}{v?.toFixed(2)}%
        </Tag>
      ),
    },
    {
      title: '成交量',
      dataIndex: 'volume',
      key: 'volume',
      width: 120,
      align: 'right',
      render: (v: number) => formatVolume(v),
    },
    {
      title: '成交额',
      dataIndex: 'turnover',
      key: 'turnover',
      width: 120,
      align: 'right',
      render: (v: number | undefined) => (v ? formatAmount(v) : '-'),
    },
  ]

  return (
    <Table
      columns={columns}
      dataSource={data}
      rowKey="symbol"
      loading={loading}
      size="small"
      pagination={false}
      onRow={(record) => ({
        onClick: () => onRowClick?.(record.symbol),
        style: { cursor: 'pointer' },
      })}
      locale={{ emptyText: '暂无行情数据' }}
    />
  )
}

function formatVolume(v: number): string {
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(0) + '万'
  return v.toString()
}

function formatAmount(v: number): string {
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(2) + '万'
  return v.toFixed(0)
}
