import type {
  CapitalFlowItem,
  DiagnosisData,
  IndexData,
  KlineData,
  QuoteData,
  SectorData,
  SectorRankingItem,
  SectorRankingResponse,
  SectorRotationItem,
  SentimentData,
} from '@/types/market'
import type { DataViewState, MarketDataMeta, TrustedData } from '@/types/dataTrust'

type RawMeta = {
  source: string
  fetched_at: string
  mode: 'live' | 'demo'
  status: 'ok' | 'empty' | 'unavailable' | 'invalid'
  stale: boolean
  is_mock: boolean
  message: string | null
}

type RawIndexResponse = {
  indices: Array<Record<string, unknown>>
  meta: RawMeta
}

type RawEnvelope<T> = T & { meta: RawMeta }

const normalizeMeta = (meta: RawMeta): MarketDataMeta => ({
  source: meta.source,
  fetchedAt: meta.fetched_at,
  mode: meta.mode,
  status: meta.status,
  stale: meta.stale,
  isMock: meta.is_mock,
  message: meta.message,
})

const finiteNumber = (value: unknown): number | null => (
  typeof value === 'number' && Number.isFinite(value) ? value : null
)

const optionalFiniteNumber = (value: unknown): number | undefined => {
  if (value == null) return undefined
  return finiteNumber(value) ?? undefined
}

const markInvalid = (meta: MarketDataMeta, message: string): MarketDataMeta => ({
  ...meta,
  status: 'invalid',
  message,
})

export function adaptIndicesResponse(response: RawIndexResponse): TrustedData<IndexData[]> {
  const meta = normalizeMeta(response.meta)
  let invalid = false
  const data = response.indices.flatMap((row): IndexData[] => {
    const price = finiteNumber(row.price)
    const change = finiteNumber(row.change)
    const changePct = finiteNumber(row.change_pct)
    if (
      typeof row.code !== 'string'
      || typeof row.name !== 'string'
      || price == null
      || price <= 0
      || change == null
      || changePct == null
    ) {
      invalid = true
      return []
    }
    return [{ code: row.code, name: row.name, price, change, changePct }]
  })

  return {
    data,
    meta: invalid
      ? {
          ...meta,
          status: 'invalid',
          message: '指数响应字段异常，本次不可用于交易决策',
        }
      : meta,
  }
}

export function deriveDataState(meta: RawMeta | MarketDataMeta): DataViewState {
  const isMock = 'is_mock' in meta ? meta.is_mock : meta.isMock
  if (meta.mode === 'demo' || isMock) return 'demo'
  if (meta.stale) return 'stale'
  return meta.status
}

export function adaptQuotesResponse(
  response: RawEnvelope<{ quotes: Array<Record<string, unknown>> }>,
): TrustedData<QuoteData[]> {
  const meta = normalizeMeta(response.meta)
  let invalid = false
  const data = response.quotes.flatMap((row): QuoteData[] => {
    const price = finiteNumber(row.price)
    const change = finiteNumber(row.change)
    const changePct = finiteNumber(row.change_pct)
    const volume = finiteNumber(row.volume)
    if (
      typeof row.symbol !== 'string'
      || price == null
      || price <= 0
      || change == null
      || changePct == null
      || volume == null
      || typeof row.timestamp !== 'string'
    ) {
      invalid = true
      return []
    }
    return [{
      symbol: row.symbol,
      name: typeof row.name === 'string' ? row.name : '',
      price,
      change,
      changePct,
      volume,
      turnover: optionalFiniteNumber(row.turnover),
      high: optionalFiniteNumber(row.high),
      low: optionalFiniteNumber(row.low),
      open: optionalFiniteNumber(row.open),
      prevClose: optionalFiniteNumber(row.prev_close),
      timestamp: row.timestamp,
    }]
  })
  return {
    data,
    meta: invalid ? markInvalid(meta, '行情响应字段异常，本次不可用于交易决策') : meta,
  }
}

export function adaptHeatmapResponse(
  response: RawEnvelope<{ sectors: Array<Record<string, unknown>> }>,
): TrustedData<SectorData[]> {
  const meta = normalizeMeta(response.meta)
  let invalid = false
  const data = response.sectors.flatMap((row): SectorData[] => {
    const changePct = finiteNumber(row.change_pct)
    if (typeof row.code !== 'string' || typeof row.name !== 'string' || changePct == null) {
      invalid = true
      return []
    }
    return [{
      code: row.code,
      name: row.name,
      sectorType: typeof row.sector_type === 'string' ? row.sector_type : '',
      changePct,
      turnover: optionalFiniteNumber(row.turnover),
      volume: optionalFiniteNumber(row.volume),
      capitalFlow: optionalFiniteNumber(row.capital_flow),
      rank: optionalFiniteNumber(row.rank),
      rankChange: optionalFiniteNumber(row.rank_change),
    }]
  })
  return {
    data,
    meta: invalid ? markInvalid(meta, '板块响应字段异常，本次不可用于交易决策') : meta,
  }
}

export function adaptKlineResponse(
  response: RawEnvelope<{
    symbol: string
    period: string
    klines: Array<Record<string, unknown>>
  }>,
): TrustedData<{ symbol: string; period: string; klines: KlineData[] }> {
  const meta = normalizeMeta(response.meta)
  let invalid = false
  const klines = response.klines.flatMap((row): KlineData[] => {
    const open = finiteNumber(row.open)
    const high = finiteNumber(row.high)
    const low = finiteNumber(row.low)
    const close = finiteNumber(row.close)
    const volume = finiteNumber(row.volume)
    if (
      typeof row.timestamp !== 'string'
      || open == null
      || high == null
      || low == null
      || close == null
      || volume == null
    ) {
      invalid = true
      return []
    }
    return [{
      timestamp: row.timestamp,
      open,
      high,
      low,
      close,
      volume,
      amount: optionalFiniteNumber(row.amount),
    }]
  })
  return {
    data: { symbol: response.symbol, period: response.period, klines },
    meta: invalid ? markInvalid(meta, 'K线响应字段异常，本次不可用于交易决策') : meta,
  }
}

const adaptSentiment = (row: Record<string, unknown> | null): SentimentData | null => {
  if (!row) return null
  return {
    fearGreedIndex: optionalFiniteNumber(row.fear_greed_index),
    fearGreedLabel: typeof row.fear_greed_label === 'string' ? row.fear_greed_label : '',
    putCallRatio: optionalFiniteNumber(row.put_call_ratio),
    marginBalance: optionalFiniteNumber(row.margin_balance),
    shortBalance: optionalFiniteNumber(row.short_balance),
    marginShortRatio: optionalFiniteNumber(row.margin_short_ratio),
    turnoverRate: optionalFiniteNumber(row.turnover_rate),
    northBoundFlow: optionalFiniteNumber(row.north_bound_flow),
    updatedAt: typeof row.updated_at === 'string' ? row.updated_at : '',
  }
}

const adaptCapitalFlow = (row: Record<string, unknown>): CapitalFlowItem => ({
  sectorName: typeof row.sector_name === 'string' ? row.sector_name : '',
  sectorCode: typeof row.sector_code === 'string' ? row.sector_code : '',
  netFlow: finiteNumber(row.net_flow) ?? 0,
  changePct: finiteNumber(row.change_pct) ?? 0,
  largeOrderFlow: optionalFiniteNumber(row.large_order_flow),
  consecutiveDays: optionalFiniteNumber(row.consecutive_days),
  rank: finiteNumber(row.rank) ?? 0,
})

const adaptRotation = (row: Record<string, unknown>): SectorRotationItem => ({
  sectorName: typeof row.sector_name === 'string' ? row.sector_name : '',
  sectorCode: typeof row.sector_code === 'string' ? row.sector_code : '',
  momentumScore: finiteNumber(row.momentum_score) ?? 0,
  heatLevel: finiteNumber(row.heat_level) ?? 0,
  trend: typeof row.trend === 'string' ? row.trend : '',
  change1w: optionalFiniteNumber(row.change_1w),
  change1m: optionalFiniteNumber(row.change_1m),
  capitalFlow5d: optionalFiniteNumber(row.capital_flow_5d),
})

export function adaptDiagnosisResponse(
  response: RawEnvelope<{
    sentiment: Record<string, unknown> | null
    top_capital_inflow: Array<Record<string, unknown>>
    top_capital_outflow: Array<Record<string, unknown>>
    sector_rotation: Array<Record<string, unknown>>
    north_bound_sectors: Array<Record<string, unknown>>
    summary: string
  }>,
): TrustedData<DiagnosisData> {
  return {
    data: {
      sentiment: adaptSentiment(response.sentiment),
      topCapitalInflow: response.top_capital_inflow.map(adaptCapitalFlow),
      topCapitalOutflow: response.top_capital_outflow.map(adaptCapitalFlow),
      sectorRotation: response.sector_rotation.map(adaptRotation),
      northBoundSectors: response.north_bound_sectors.map(adaptCapitalFlow),
      summary: response.summary,
    },
    meta: normalizeMeta(response.meta),
  }
}

const adaptRankingItem = (row: Record<string, unknown>): SectorRankingItem => {
  const breakdown = (
    typeof row.breakdown === 'object' && row.breakdown !== null
      ? row.breakdown
      : {}
  ) as Record<string, unknown>
  return {
    rank: finiteNumber(row.rank) ?? 0,
    code: typeof row.code === 'string' ? row.code : '',
    name: typeof row.name === 'string' ? row.name : '',
    matchedSector: typeof row.matched_sector === 'string' ? row.matched_sector : '',
    changePct: finiteNumber(row.change_pct) ?? 0,
    flowValue: finiteNumber(row.flow_value) ?? 0,
    turnover: finiteNumber(row.turnover) ?? 0,
    baseScore: finiteNumber(row.base_score) ?? 0,
    breakdown: {
      price: finiteNumber(breakdown.price) ?? 0,
      flow: finiteNumber(breakdown.flow) ?? 0,
      heat: finiteNumber(breakdown.heat) ?? 0,
      momentum: finiteNumber(breakdown.momentum) ?? 0,
    },
    signal: typeof row.signal === 'string' ? row.signal : 'WATCH',
    confidence: finiteNumber(row.confidence) ?? 0,
    technical: typeof row.technical === 'string' ? row.technical : '',
    volume: typeof row.volume === 'string' ? row.volume : '',
    opportunity: typeof row.opportunity === 'string' ? row.opportunity : '',
    relatedHoldings: Array.isArray(row.related_holdings)
      ? row.related_holdings.filter((value): value is string => typeof value === 'string')
      : [],
  }
}

export function adaptSectorRankingResponse(
  response: RawEnvelope<{
    timestamp: string
    total_sectors: number
    strong_signals: Array<Record<string, unknown>>
    watch_signals: Array<Record<string, unknown>>
    weak_signals: Array<Record<string, unknown>>
    all_rankings: Array<Record<string, unknown>>
  }>,
): TrustedData<SectorRankingResponse> {
  return {
    data: {
      timestamp: response.timestamp,
      totalSectors: response.total_sectors,
      strongSignals: response.strong_signals.map(adaptRankingItem),
      watchSignals: response.watch_signals.map(adaptRankingItem),
      weakSignals: response.weak_signals.map(adaptRankingItem),
      allRankings: response.all_rankings.map(adaptRankingItem),
    },
    meta: normalizeMeta(response.meta),
  }
}
