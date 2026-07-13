import { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import type { YangjibaoPortfolioPosition } from '@/types/portfolio'

interface Props {
  positions: YangjibaoPortfolioPosition[]
}

export default function PnLChart({ positions }: Props) {
  const option = useMemo(() => {
    const sorted = [...positions].sort(
      (a, b) => b.unrealized_pnl - a.unrealized_pnl
    )

    return {
      title: {
        text: '持仓盈亏',
        left: 'center',
        textStyle: { fontSize: 14 },
      },
      tooltip: {
        trigger: 'axis' as const,
        axisPointer: { type: 'shadow' as const },
        formatter: (params: Array<{ name: string; value: number }>) => {
          const p = params[0]
          return `${p.name}<br/>盈亏: ${p.value >= 0 ? '+' : ''}${p.value.toFixed(2)}`
        },
      },
      grid: {
        left: 60,
        right: 20,
        top: 40,
        bottom: 20,
      },
      xAxis: {
        type: 'value' as const,
        axisLabel: {
          formatter: (v: number) => `${v.toFixed(0)}`,
        },
      },
      yAxis: {
        type: 'category' as const,
        data: sorted.map((p) => p.symbol),
        axisLabel: { fontSize: 11 },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: [
        {
          type: 'bar',
          data: sorted.map((p) => ({
            value: Math.round(p.unrealized_pnl * 100) / 100,
            itemStyle: {
              color: p.unrealized_pnl >= 0 ? '#cf1322' : '#3f8600',
              borderRadius: [0, 3, 3, 0],
            },
          })),
          barMaxWidth: 18,
        },
      ],
    }
  }, [positions])

  return <ReactECharts option={option} style={{ height: 400 }} />
}
