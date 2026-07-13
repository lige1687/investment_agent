import apiClient from './client'
import type { YangjibaoPortfolioResponse } from '@/types/portfolio'

export const portfolioApi = {
  getPortfolio: () =>
    apiClient.get<YangjibaoPortfolioResponse>('/yangjibao/portfolio'),
}
