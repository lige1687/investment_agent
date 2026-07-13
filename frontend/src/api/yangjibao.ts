import apiClient from './client'
import type {
  YangjibaoStatus, QRLoginResponse, QRCheckResponse,
  SyncResult, YangjibaoPortfolio,
} from '@/types/yangjibao'

export const yangjibaoApi = {
  getStatus: () =>
    apiClient.get<YangjibaoStatus>('/yangjibao/status'),

  startLogin: () =>
    apiClient.post<QRLoginResponse>('/yangjibao/login'),

  checkLogin: () =>
    apiClient.get<QRCheckResponse>('/yangjibao/login/check'),

  syncPortfolio: () =>
    apiClient.post<SyncResult>('/yangjibao/sync'),

  getPortfolio: () =>
    apiClient.get<YangjibaoPortfolio>('/yangjibao/portfolio'),
}
