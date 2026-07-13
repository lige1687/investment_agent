import { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import type { YangjibaoPortfolioPosition } from '@/types/portfolio'

interface Props {
  positions: YangjibaoPortfolioPosition[]
  totalValue: number
}

const CHART_COLORS = [
  '#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de',
  '#3ba272', '#fc8452', '#9a60b4',
]

export default function AllocationChart({ positions, totalValue }: Props) {
  const option = useMemo(() => {
    const sorted = [...positions].sort((a, b) => b.market_value - a.market_value)
    const top = sorted.slice(0, 7)
    const rest = sorted.slice(7)
    const restValue = rest.reduce((s, p) => s + p.market_value, 0)

    const data = top.map((p) => ({
      name: p.symbol,
      value: p.market_value,
    }))
    if (restValue > 0) {
      data.push({ name: '其他', value: restValue })
    }

    return {
      title: {
        text: '持仓占比',
        left: 'center',
        textStyle: { fontSize: 14 },
      },
      tooltip: {
        trigger: 'item' as const,
        formatter: (params: { name: string; percent: number }) =>
          `${params.name}<br/>占比: ${params.percent}%`,
      },
      series: [
        {
          type: 'pie',
          radius: ['40%', '65%'],
          center: ['50%', '55%'],
          avoidLabelOverlap: false,
          itemStyle: {
            borderRadius: 4,
            borderColor: '#fff',
            borderWidth: 2,
          },
          label: {
            show: true,
            formatter: '{b}\n{d}%',
            fontSize: 11,
          },
          emphasis: {
            label: {
              show: true,
              fontSize: 13,
              fontWeight: 'bold',
            },
          },
          data: data.map((d, i) => ({
            ...d,
            itemStyle: { color: CHART_COLORS[i % CHART_COLORS.length] },
          })),
        },
      ],
    }
  }, [positions, totalValue])

  return <ReactECharts option={option} style={{ height: 320 }} />
}
