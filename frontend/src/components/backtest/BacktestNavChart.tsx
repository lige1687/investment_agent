import { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import type { BacktestEvent, BacktestTrade, PortfolioSnapshot } from '@/types/backtest'

interface Props {
  equityCurve: PortfolioSnapshot[]
  trades: BacktestTrade[]
  events: BacktestEvent[]
  height?: number
  onSelectTrade: (trade: BacktestTrade, event?: BacktestEvent) => void
}

export default function BacktestNavChart({ equityCurve, trades, events, height = 520, onSelectTrade }: Props) {
  const option = useMemo(() => {
    const dates = equityCurve.map((item) => item.date)
    const navSeries = equityCurve.map((item) => item.nav)
    const equitySeries = equityCurve.map((item) => +(item.equity / 1000).toFixed(2))
    const buyPoints = trades
      .filter((trade) => trade.action === 'buy')
      .map((trade) => [trade.date, trade.nav, trade])
    const sellPoints = trades
      .filter((trade) => trade.action === 'sell')
      .map((trade) => [trade.date, trade.nav, trade])

    return {
      animation: false,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
      },
      legend: {
        top: 0,
        data: ['基金净值', '账户资产(千元)', '买入', '卖出'],
      },
      grid: { left: 56, right: 28, top: 48, bottom: 72 },
      xAxis: {
        type: 'category',
        data: dates,
        boundaryGap: false,
      },
      yAxis: [
        { type: 'value', name: '净值', scale: true },
        { type: 'value', name: '资产(千元)', scale: true },
      ],
      dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 18 }],
      series: [
        {
          name: '基金净值',
          type: 'line',
          data: navSeries,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: '#1677ff', width: 2 },
        },
        {
          name: '账户资产(千元)',
          type: 'line',
          yAxisIndex: 1,
          data: equitySeries,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: '#722ed1', width: 1.5, type: 'dashed' },
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
  }, [equityCurve, trades])

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
