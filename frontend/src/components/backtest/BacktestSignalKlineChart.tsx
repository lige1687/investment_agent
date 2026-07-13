import { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import type { BacktestEvent, BacktestTrade, SignalBar } from '@/types/backtest'

interface Props {
  signalBars: SignalBar[]
  trades: BacktestTrade[]
  events: BacktestEvent[]
  height?: number
  onSelectTrade: (trade: BacktestTrade, event?: BacktestEvent) => void
}

export default function BacktestSignalKlineChart({ signalBars, trades, events, height = 420, onSelectTrade }: Props) {
  const option = useMemo(() => {
    const dates = signalBars.map((item) => item.date)
    const ohlc = signalBars.map((item) => [item.open, item.close, item.low, item.high])
    const volumes = signalBars.map((item) => item.volume)
    const closeByDate = new Map(signalBars.map((item) => [item.date, item.close]))
    const buyPoints = trades
      .filter((trade) => trade.action === 'buy' && closeByDate.has(trade.date))
      .map((trade) => [trade.date, closeByDate.get(trade.date), trade])
    const sellPoints = trades
      .filter((trade) => trade.action === 'sell' && closeByDate.has(trade.date))
      .map((trade) => [trade.date, closeByDate.get(trade.date), trade])

    return {
      animation: false,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
      },
      legend: {
        top: 0,
        data: ['参考ETF K线', '成交量', '买入', '卖出'],
      },
      grid: [
        { left: 56, right: 28, top: 48, height: 230 },
        { left: 56, right: 28, top: 310, height: 54 },
      ],
      xAxis: [
        { type: 'category', data: dates, boundaryGap: true, gridIndex: 0 },
        { type: 'category', data: dates, boundaryGap: true, gridIndex: 1, axisLabel: { show: false } },
      ],
      yAxis: [
        { type: 'value', scale: true, gridIndex: 0, name: '价格' },
        { type: 'value', scale: true, gridIndex: 1, axisLabel: { show: false } },
      ],
      dataZoom: [{ type: 'inside', xAxisIndex: [0, 1] }, { type: 'slider', xAxisIndex: [0, 1], bottom: 8 }],
      series: [
        {
          name: '参考ETF K线',
          type: 'candlestick',
          data: ohlc,
          itemStyle: {
            color: '#cf1322',
            color0: '#3f8600',
            borderColor: '#cf1322',
            borderColor0: '#3f8600',
          },
        },
        {
          name: '成交量',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumes,
          itemStyle: {
            color: (params: any) => {
              const bar = signalBars[params.dataIndex]
              return bar && bar.close >= bar.open ? '#cf1322' : '#3f8600'
            },
          },
        },
        {
          name: '买入',
          type: 'scatter',
          data: buyPoints,
          symbol: 'triangle',
          symbolSize: 14,
          itemStyle: { color: '#cf1322' },
          encode: { x: 0, y: 1 },
        },
        {
          name: '卖出',
          type: 'scatter',
          data: sellPoints,
          symbol: 'pin',
          symbolSize: 16,
          itemStyle: { color: '#3f8600' },
          encode: { x: 0, y: 1 },
        },
      ],
    }
  }, [signalBars, trades])

  return (
    <ReactECharts
      option={option}
      style={{ height, width: '100%' }}
      notMerge
      onEvents={{
        click: (params: any) => {
          const trade = params?.data?.[2] as BacktestTrade | undefined
          if (!trade) return
          const event = findEventForTrade(trade, events)
          onSelectTrade(trade, event)
        },
      }}
    />
  )
}

function findEventForTrade(trade: BacktestTrade, events: BacktestEvent[]) {
  return [...events]
    .reverse()
    .find((event) =>
      event.event_type === trade.event_type
      && event.date <= trade.date
      && event.decision.action === trade.action
    )
}
