export type MarketDataMode = 'live' | 'demo'
export type MarketDataStatus = 'ok' | 'empty' | 'unavailable' | 'invalid'
export type DataViewState = 'ok' | 'loading' | 'empty' | 'unavailable' | 'invalid' | 'stale' | 'demo'

export interface MarketDataMeta {
  source: string
  fetchedAt: string
  mode: MarketDataMode
  status: MarketDataStatus
  stale: boolean
  isMock: boolean
  message: string | null
}

export interface TrustedData<T> {
  data: T
  meta: MarketDataMeta
}

