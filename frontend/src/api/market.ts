import apiClient from './client'
import {
  adaptDiagnosisResponse,
  adaptHeatmapResponse,
  adaptIndicesResponse,
  adaptKlineResponse,
  adaptQuotesResponse,
  adaptSectorRankingResponse,
} from './adapters/market'

export const marketApi = {
  getQuotes: async (symbols: string[]) => {
    const response = await apiClient.get('/market/quotes', {
      params: { symbols: symbols.join(',') }
    })
    return adaptQuotesResponse(response.data)
  },

  getKline: async (symbol: string, period = 'daily', count = 120) => {
    const response = await apiClient.get(
      '/market/kline', { params: { symbol, period, count } }
    )
    return adaptKlineResponse(response.data)
  },

  getHeatmap: async () => {
    const response = await apiClient.get('/market/heatmap')
    return adaptHeatmapResponse(response.data)
  },

  getIndices: async (codes?: string[]) => {
    const response = await apiClient.get('/market/indices', {
      params: codes ? { codes: codes.join(',') } : {}
    })
    return adaptIndicesResponse(response.data)
  },

  getDiagnosis: async () => {
    const response = await apiClient.get('/market/diagnosis')
    return adaptDiagnosisResponse(response.data)
  },

  getSectorRankings: async () => {
    const response = await apiClient.get('/market/sector/rankings')
    return adaptSectorRankingResponse(response.data)
  },
}
