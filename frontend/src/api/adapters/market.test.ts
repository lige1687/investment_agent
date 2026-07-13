import { describe, expect, it } from 'vitest'

import {
  adaptDiagnosisResponse,
  adaptHeatmapResponse,
  adaptIndicesResponse,
  adaptKlineResponse,
  adaptQuotesResponse,
  adaptSectorRankingResponse,
  deriveDataState,
} from './market'

const liveMeta = {
  source: 'westock',
  fetched_at: '2026-07-13T14:30:00+08:00',
  mode: 'live',
  status: 'ok',
  stale: false,
  is_mock: false,
  message: null,
} as const

describe('market trust adapter', () => {
  it('maps snake_case values and provenance to the frontend model', () => {
    const result = adaptIndicesResponse({
      indices: [
        {
          code: 'IXIC',
          name: '纳斯达克',
          price: 20000,
          change: 150,
          change_pct: 0.75,
        },
      ],
      meta: liveMeta,
    })

    expect(result.data[0].changePct).toBe(0.75)
    expect(result.meta.fetchedAt).toBe(liveMeta.fetched_at)
    expect(result.meta.isMock).toBe(false)
  })

  it('never substitutes point change for a missing percentage', () => {
    const result = adaptIndicesResponse({
      indices: [
        {
          code: 'IXIC',
          name: '纳斯达克',
          price: 20000,
          change: 150,
        },
      ],
      meta: liveMeta,
    })

    expect(result.data).toEqual([])
    expect(result.meta.status).toBe('invalid')
  })

  it.each([
    [{ ...liveMeta, status: 'empty' as const }, 'empty'],
    [{ ...liveMeta, status: 'unavailable' as const }, 'unavailable'],
    [{ ...liveMeta, status: 'invalid' as const }, 'invalid'],
    [{ ...liveMeta, stale: true }, 'stale'],
    [{ ...liveMeta, mode: 'demo' as const, is_mock: true }, 'demo'],
    [liveMeta, 'ok'],
  ])('derives the visible state from trusted metadata', (meta, expected) => {
    expect(deriveDataState(meta)).toBe(expected)
  })

  it('normalizes quote and heatmap percentages', () => {
    const quotes = adaptQuotesResponse({
      quotes: [{ symbol: '510050', price: 2.5, change: 0.1, change_pct: 4, volume: 100, timestamp: 'now' }],
      meta: liveMeta,
    })
    const heatmap = adaptHeatmapResponse({
      sectors: [{ code: 'TMT', name: '通信', sector_type: 'industry', change_pct: 2.5 }],
      meta: liveMeta,
    })

    expect(quotes.data[0].changePct).toBe(4)
    expect(heatmap.data[0].sectorType).toBe('industry')
    expect(heatmap.data[0].changePct).toBe(2.5)
  })

  it('keeps kline values and attaches normalized metadata', () => {
    const result = adaptKlineResponse({
      symbol: '510050',
      period: 'daily',
      klines: [{ timestamp: '2026-07-13', open: 1, high: 1.1, low: 0.9, close: 1.05, volume: 100 }],
      meta: liveMeta,
    })

    expect(result.data.symbol).toBe('510050')
    expect(result.data.klines[0].close).toBe(1.05)
    expect(result.meta.source).toBe('westock')
  })

  it('normalizes nested diagnosis fields', () => {
    const result = adaptDiagnosisResponse({
      sentiment: { fear_greed_index: 40, fear_greed_label: '中性', north_bound_flow: 12.5 },
      top_capital_inflow: [{ sector_name: '通信', sector_code: 'TMT', net_flow: 8, change_pct: 2, rank: 1 }],
      top_capital_outflow: [],
      sector_rotation: [{ sector_name: '通信', sector_code: 'TMT', momentum_score: 0.8, heat_level: 4, trend: 'leading' }],
      north_bound_sectors: [],
      summary: '通信领先',
      meta: liveMeta,
    })

    expect(result.data.sentiment?.fearGreedIndex).toBe(40)
    expect(result.data.topCapitalInflow[0].sectorName).toBe('通信')
    expect(result.data.sectorRotation[0].momentumScore).toBe(0.8)
  })

  it('normalizes sector ranking fields once at the API boundary', () => {
    const row = {
      rank: 1,
      code: 'TMT',
      name: '通信',
      matched_sector: '通信设备',
      change_pct: 2.5,
      flow_value: 8,
      turnover: 100,
      base_score: 8.2,
      breakdown: { price: 8, flow: 9, heat: 7, momentum: 8 },
      signal: 'STRONG',
      confidence: 0.9,
      technical: '上升',
      volume: '放量',
      opportunity: '回踩确认',
      related_holdings: ['001513'],
    }
    const result = adaptSectorRankingResponse({
      timestamp: '2026-07-13T15:00:00+08:00',
      total_sectors: 1,
      strong_signals: [row],
      watch_signals: [],
      weak_signals: [],
      all_rankings: [row],
      meta: liveMeta,
    })

    expect(result.data.totalSectors).toBe(1)
    expect(result.data.allRankings[0].matchedSector).toBe('通信设备')
    expect(result.data.allRankings[0].changePct).toBe(2.5)
    expect(result.data.allRankings[0].baseScore).toBe(8.2)
  })
})
