import { Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { YangjibaoPortfolioPosition } from '@/types/portfolio'

interface TableRow extends YangjibaoPortfolioPosition {
  allocationPct: number
  key: string
}

interface Props {
  positions: YangjibaoPortfolioPosition[]
  totalValue: number
  loading?: boolean
}

export default function PositionTable({ positions, totalValue, loading }: Props) {
  const columns: ColumnsType<TableRow> = [
    {
      title: '基金名称',
      dataIndex: 'name',
      key: 'name',
      width: 180,
      ellipsis: true,
      render: (name: string, r: TableRow) => (
        <span>
          <span style={{ fontSize: 13 }}>{name || r.symbol}</span>
          <Tag style={{ fontSize: 10, marginTop: 2 }}>{r.symbol}</Tag>
        </span>
      ),
    },
    {
      title: '代码',
      dataIndex: 'symbol',
      key: 'symbol',
      width: 80,
      responsive: ['md'],
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 80,
      render: (type: string) => (
        <Tag color={type === 'fund' ? 'blue' : 'purple'}>
          {type === 'fund' ? '基金' : 'ETF'}
        </Tag>
      ),
    },
    {
      title: '持有份额',
      dataIndex: 'shares',
      key: 'shares',
      width: 120,
      align: 'right',
      render: (v: number) =>
        v.toLocaleString(undefined, {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        }),
    },
    {
      title: '成本价',
      dataIndex: 'avg_cost',
      key: 'avg_cost',
      width: 100,
      align: 'right',
      render: (v: number) => v.toFixed(4),
    },
    {
      title: '现价',
      dataIndex: 'current_price',
      key: 'current_price',
      width: 100,
      align: 'right',
      render: (v: number) => v.toFixed(4),
    },
    {
      title: '市值',
      dataIndex: 'market_value',
      key: 'market_value',
      width: 120,
      align: 'right',
      render: (v: number) =>
        v.toLocaleString(undefined, {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        }),
      sorter: (a, b) => a.market_value - b.market_value,
    },
    {
      title: '浮动盈亏',
      dataIndex: 'unrealized_pnl',
      key: 'unrealized_pnl',
      width: 130,
      align: 'right',
      render: (v: number) => (
        <span style={{ color: v >= 0 ? '#cf1322' : '#3f8600' }}>
          {v >= 0 ? '+' : ''}
          {v.toFixed(2)}
        </span>
      ),
      sorter: (a, b) => a.unrealized_pnl - b.unrealized_pnl,
    },
    {
      title: '盈亏%',
      dataIndex: 'unrealized_pnl_pct',
      key: 'unrealized_pnl_pct',
      width: 100,
      align: 'right',
      render: (v: number) => (
        <span style={{ color: v >= 0 ? '#cf1322' : '#3f8600' }}>
          {v >= 0 ? '+' : ''}
          {v.toFixed(2)}%
        </span>
      ),
      sorter: (a, b) => a.unrealized_pnl_pct - b.unrealized_pnl_pct,
    },
    {
      title: '占比',
      dataIndex: 'allocationPct',
      key: 'allocationPct',
      width: 100,
      align: 'right',
      render: (v: number) => `${v.toFixed(2)}%`,
      sorter: (a, b) => a.allocationPct - b.allocationPct,
    },
  ]

  const dataSource: TableRow[] = positions.map((p) => ({
    ...p,
    allocationPct: (p.market_value / totalValue) * 100,
    key: p.symbol,
  }))

  return (
    <Table
      columns={columns}
      dataSource={dataSource}
      loading={loading}
      pagination={false}
      size="small"
      scroll={{ x: 950 }}
    />
  )
}
