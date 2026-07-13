import { useState, useMemo } from 'react'
import { Typography, Input, Select, Space, Card } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { marketApi } from '@/api/market'
import { deriveDataState } from '@/api/adapters/market'
import DataStatePanel from '@/components/common/DataStatePanel'
import DemoDataBanner from '@/components/common/DemoDataBanner'
import QuoteTable from './QuoteTable'
import KlineChart from './KlineChart'
import type { KlineData } from '@/types/market'

const { Title } = Typography
const { Search } = Input

const DEFAULT_ETFS = ['510050', '510300', '510500', '159915', '588000']

export default function MarketPage() {
  const [symbols, setSymbols] = useState<string[]>(DEFAULT_ETFS)
  const [selectedSymbol, setSelectedSymbol] = useState<string>(DEFAULT_ETFS[0])
  const [period, setPeriod] = useState<string>('daily')

  const { data: quotesData, isLoading, refetch: refetchQuotes } = useQuery({
    queryKey: ['quotes', symbols],
    queryFn: async () => {
      return marketApi.getQuotes(symbols)
    },
    refetchInterval: 30_000, // Refresh every 30s
  })

  const { data: klineData, isLoading: klineLoading, refetch: refetchKline } = useQuery({
    queryKey: ['kline', selectedSymbol, period],
    queryFn: async () => {
      return marketApi.getKline(selectedSymbol, period, 120)
    },
    enabled: !!selectedSymbol,
    refetchInterval: 60_000,
  })

  const quotes = useMemo(() => quotesData?.data || [], [quotesData])
  const klines = useMemo(() => klineData?.data.klines || [], [klineData])
  const quoteState = isLoading
    ? 'loading'
    : quotesData ? deriveDataState(quotesData.meta) : 'unavailable'
  const klineState = klineLoading
    ? 'loading'
    : klineData ? deriveDataState(klineData.meta) : 'unavailable'
  const usesDemoData = quotesData?.meta.isMock || klineData?.meta.isMock

  const handleSearch = (value: string) => {
    const codes = value
      .split(/[,，\s]+/)
      .map((s) => s.trim())
      .filter(Boolean)
    if (codes.length) {
      setSymbols(codes)
      setSelectedSymbol(codes[0])
    }
  }

  return (
    <div>
      {usesDemoData && <DemoDataBanner />}
      <Title level={4}>行情数据</Title>

      <Space style={{ marginBottom: 16 }}>
        <Search
          placeholder="输入代码（多个用逗号分隔），如 510050,159915"
          onSearch={handleSearch}
          style={{ width: 400 }}
          allowClear
        />
        <Select value={period} onChange={setPeriod} style={{ width: 100 }}>
          <Select.Option value="daily">日K</Select.Option>
          <Select.Option value="weekly">周K</Select.Option>
          <Select.Option value="60min">60分</Select.Option>
          <Select.Option value="30min">30分</Select.Option>
        </Select>
      </Space>

      <Card title={`📊 ${selectedSymbol} K线图`} style={{ marginBottom: 16 }}>
        <DataStatePanel
          state={klineState}
          meta={klineData?.meta}
          onRetry={() => { refetchKline() }}
        >
          <KlineChart data={klines as KlineData[]} height={420} />
        </DataStatePanel>
      </Card>

      <Card title="行情列表">
        <DataStatePanel
          state={quoteState}
          meta={quotesData?.meta}
          onRetry={() => { refetchQuotes() }}
        >
          <QuoteTable
            data={quotes}
            loading={isLoading}
            onRowClick={setSelectedSymbol}
          />
        </DataStatePanel>
      </Card>
    </div>
  )
}
