import { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import type { BacktestEvent, BacktestTrade, PortfolioSnapshot, SignalBar } from '@/types/backtest'

interface Props {
  equityCurve: PortfolioSnapshot[]
  signalBars: SignalBar[]
  trades: BacktestTrade[]
  events: BacktestEvent[]
  height?: number
  onSelectTrade: (trade: BacktestTrade, event?: BacktestEvent) => void
  onSelectEvent?: (event: BacktestEvent) => void
}

export default function BacktestLinkedReviewChart({
  equityCurve,
  signalBars,
  trades,
  events,
  height = 760,
  onSelectTrade,
  onSelectEvent,
}: Props) {
  const option = useMemo(() => {
    const dates = equityCurve.map((item) => item.date)
    const signalByDate = new Map(signalBars.map((item) => [item.date, item]))
    const navByDate = new Map(equityCurve.map((item) => [item.date, item.nav]))
    const alignedSignalBars = dates.map((itemDate) => signalByDate.get(itemDate))
    const ohlc = alignedSignalBars.map((item) => (
      item ? [item.open, item.close, item.low, item.high] : ['-', '-', '-', '-']
    ))
    const closes = alignedSignalBars.map((item) => item?.close ?? null)
    const volumes = alignedSignalBars.map((item) => item?.volume ?? 0)
    const navSeries = equityCurve.map((item) => item.nav)
    const equitySeries = equityCurve.map((item) => +(item.equity / 1000).toFixed(2))
    const navBuyPoints = trades
      .filter((trade) => trade.action === 'buy' && navByDate.has(trade.date))
      .map((trade) => [trade.date, navByDate.get(trade.date), trade])
    const navSellPoints = trades
      .filter((trade) => trade.action === 'sell' && navByDate.has(trade.date))
      .map((trade) => [trade.date, navByDate.get(trade.date), trade])
    const klineBuyPoints = trades
      .filter((trade) => trade.action === 'buy' && signalByDate.has(trade.date))
      .map((trade) => [trade.date, signalByDate.get(trade.date)?.close, trade])
    const klineSellPoints = trades
      .filter((trade) => trade.action === 'sell' && signalByDate.has(trade.date))
      .map((trade) => [trade.date, signalByDate.get(trade.date)?.close, trade])
    const auditPoints = events
      .filter((event) => event.event_type === 'system_check' && navByDate.has(event.date))
      .map((event) => [event.date, navByDate.get(event.date), event])

    return {
      animation: false,
      color: ['#1677ff', '#722ed1', '#f59e0b', '#13c2c2', '#eb2f96', '#8b5cf6'],
      axisPointer: {
        link: [{ xAxisIndex: 'all' }],
        label: { backgroundColor: '#434343' },
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        confine: true,
      },
      legend: {
        top: 0,
        type: 'scroll',
        data: ['基金净值', '账户资产(千元)', 'ETF K线', 'MA5', 'MA10', 'MA20', 'MA60', '成交量', '买入', '卖出', '判断'],
      },
      grid: [
        { left: 58, right: 38, top: 48, height: 210 },
        { left: 58, right: 38, top: 304, height: 280 },
        { left: 58, right: 38, top: 620, height: 70 },
      ],
      xAxis: [
        { type: 'category', data: dates, boundaryGap: false, axisLine: { onZero: false }, axisLabel: { show: false } },
        { type: 'category', data: dates, boundaryGap: true, gridIndex: 1, axisLine: { onZero: false }, axisLabel: { show: false } },
        { type: 'category', data: dates, boundaryGap: true, gridIndex: 2, axisLine: { onZero: false }, axisLabel: { fontSize: 11 } },
      ],
      yAxis: [
        { type: 'value', name: '基金净值', scale: true, splitLine: { lineStyle: { color: '#f0f0f0' } } },
        { type: 'value', name: '资产(千元)', scale: true, splitLine: { show: false } },
        { type: 'value', name: 'ETF价格', scale: true, gridIndex: 1, splitLine: { lineStyle: { color: '#f0f0f0' } } },
        { type: 'value', gridIndex: 2, scale: true, axisLabel: { show: false }, splitLine: { show: false } },
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1, 2], filterMode: 'none' },
        { type: 'slider', xAxisIndex: [0, 1, 2], bottom: 10, height: 24, filterMode: 'none' },
      ],
      series: [
        { name: '基金净值', type: 'line', data: navSeries, symbol: 'none', smooth: true, lineStyle: { width: 2 } },
        {
          name: '账户资产(千元)',
          type: 'line',
          yAxisIndex: 1,
          data: equitySeries,
          symbol: 'none',
          smooth: true,
          lineStyle: { width: 1.5, type: 'dashed' },
        },
        tradeScatter('买入', navBuyPoints, 0, 0, '#cf1322', 'triangle', 13),
        tradeScatter('卖出', navSellPoints, 0, 0, '#3f8600', 'pin', 16),
        tradeScatter('判断', auditPoints, 0, 0, '#595959', 'circle', 8),
        {
          name: 'ETF K线',
          type: 'candlestick',
          xAxisIndex: 1,
          yAxisIndex: 2,
          data: ohlc,
          barWidth: '58%',
          itemStyle: {
            color: '#cf1322',
            color0: '#3f8600',
            borderColor: '#cf1322',
            borderColor0: '#3f8600',
          },
        },
        maLine('MA5', closes, 5, '#f59e0b'),
        maLine('MA10', closes, 10, '#13c2c2'),
        maLine('MA20', closes, 20, '#eb2f96'),
        maLine('MA60', closes, 60, '#8b5cf6'),
        tradeScatter('买入', klineBuyPoints, 1, 2, '#cf1322', 'triangle', 13),
        tradeScatter('卖出', klineSellPoints, 1, 2, '#3f8600', 'pin', 16),
        {
          name: '成交量',
          type: 'bar',
          xAxisIndex: 2,
          yAxisIndex: 3,
          data: volumes,
          barWidth: '58%',
          itemStyle: {
            color: (params: any) => {
              const bar = alignedSignalBars[params.dataIndex]
              return bar && bar.close >= bar.open ? 'rgba(207,19,34,0.55)' : 'rgba(63,134,0,0.55)'
            },
          },
        },
      ],
    }
  }, [equityCurve, signalBars, trades, events])

  return (
    <ReactECharts
      option={option}
      style={{ height, width: '100%' }}
      notMerge
      onEvents={{
        click: (params: any) => {
          const trade = params?.data?.[2] as BacktestTrade | undefined
          if (!trade) return
          if ('action' in trade) {
            onSelectTrade(trade, findEventForTrade(trade, events))
            return
          }
          onSelectEvent?.(trade as unknown as BacktestEvent)
        },
      }}
    />
  )
}

function tradeScatter(
  name: string,
  data: unknown[],
  xAxisIndex: number,
  yAxisIndex: number,
  color: string,
  symbol: string,
  symbolSize: number,
) {
  return {
    name,
    type: 'scatter',
    xAxisIndex,
    yAxisIndex,
    data,
    symbol,
    symbolSize,
    itemStyle: { color },
    emphasis: { scale: 1.4 },
    encode: { x: 0, y: 1 },
    z: 20,
  }
}

function maLine(name: string, closes: Array<number | null>, period: number, color: string) {
  return {
    name,
    type: 'line',
    xAxisIndex: 1,
    yAxisIndex: 2,
    data: calcMA(closes, period),
    symbol: 'none',
    smooth: true,
    lineStyle: { width: 1.2, color },
  }
}

function calcMA(values: Array<number | null>, period: number) {
  return values.map((_, index) => {
    if (index < period - 1) return null
    const slice = values.slice(index - period + 1, index + 1)
    if (slice.some((item) => item == null)) return null
    const sum = slice.reduce<number>((acc, item) => acc + (item ?? 0), 0)
    return +(sum / period).toFixed(4)
  })
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
