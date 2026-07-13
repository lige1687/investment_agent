import apiClient from './client'
import type { QuoteData, KlineData, SectorData, IndexData, DiagnosisData, SectorRankingResponse } from '@/types/market'

export const marketApi = {
  getQuotes: (symbols: string[]) =>
    apiClient.get<{ quotes: QuoteData[] }>('/market/quotes', {
      params: { symbols: symbols.join(',') }
    }),

  getKline: (symbol: string, period = 'daily', count = 120) =>
    apiClient.get<{ symbol: string; period: string; klines: KlineData[] }>(
      '/market/kline', { params: { symbol, period, count } }
    ),

  getHeatmap: () =>
    apiClient.get<{ sectors: SectorData[] }>('/market/heatmap'),

  getIndices: (codes?: string[]) =>
    apiClient.get<{ indices: IndexData[] }>('/market/indices', {
      params: codes ? { codes: codes.join(',') } : {}
    }),

  getDiagnosis: () =>
    apiClient.get<DiagnosisData>('/market/diagnosis'),

  getSectorRankings: () =>
    apiClient.get<SectorRankingResponse>('/market/sector/rankings'),
}
