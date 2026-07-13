import { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import type { KlineData } from '@/types/market'

interface Props {
  data: KlineData[]
  height?: number
  showMA?: boolean
  showVolume?: boolean
}

export default function KlineChart({ data, height = 400, showMA = true, showVolume = true }: Props) {
  const option = useMemo(() => {
    if (!data.length) return {}

    const dates = data.map((d) => d.timestamp)
    const ohlc = data.map((d) => [d.open, d.close, d.low, d.high])
    const volumes = data.map((d) => d.volume)

    // Calculate MAs
    const ma5 = calcMA(data, 5)
    const ma10 = calcMA(data, 10)
    const ma20 = calcMA(data, 20)

    const series: any[] = [
      {
        name: 'K线',
        type: 'candlestick',
        data: ohlc,
        itemStyle: {
          color: '#cf1322',
          color0: '#3f8600',
          borderColor: '#cf1322',
          borderColor0: '#3f8600',
        },
      },
    ]

    if (showMA) {
      series.push(
        { name: 'MA5', type: 'line', data: ma5, smooth: true, lineStyle: { width: 1, color: '#e6a23c' }, symbol: 'none' },
        { name: 'MA10', type: 'line', data: ma10, smooth: true, lineStyle: { width: 1, color: '#409eff' }, symbol: 'none' },
        { name: 'MA20', type: 'line', data: ma20, smooth: true, lineStyle: { width: 1, color: '#f56c6c' }, symbol: 'none' },
      )
    }

    if (showVolume) {
      series.push({
        name: '成交量',
        type: 'bar',
        data: volumes,
        yAxisIndex: 1,
        itemStyle: {
          color: (params: any) => {
            const idx = params.dataIndex
            if (idx >= 0 && idx < data.length) {
              return data[idx].close >= data[idx].open ? '#cf1322' : '#3f8600'
            }
            return '#cf1322'
          },
        },
      })
    }

    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
      },
      legend: {
        data: showMA ? ['K线', 'MA5', 'MA10', 'MA20'] : ['K线'],
        top: 0,
      },
      grid: [
        { left: '3%', right: '3%', top: '15%', height: '60%' },
        { left: '3%', right: '3%', top: '80%', height: '15%' },
      ],
      xAxis: [
        {
          type: 'category',
          data: dates,
          gridIndex: 0,
          axisLabel: { rotate: 45, fontSize: 10 },
        },
        {
          type: 'category',
          data: dates,
          gridIndex: 1,
          axisLabel: { show: false },
        },
      ],
      yAxis: [
        {
          type: 'value',
          gridIndex: 0,
          scale: true,
        },
        {
          type: 'value',
          gridIndex: 1,
          axisLabel: { show: false },
        },
      ],
      series,
      dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 0 }],
    }
  }, [data, showMA, showVolume])

  return <ReactECharts option={option} style={{ height, width: '100%' }} notMerge />
}

function calcMA(data: KlineData[], period: number): (number | null)[] {
  const result: (number | null)[] = []
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) {
      result.push(null)
    } else {
      let sum = 0
      for (let j = i - period + 1; j <= i; j++) sum += data[j].close
      result.push(+(sum / period).toFixed(2))
    }
  }
  return result
}
