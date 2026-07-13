import apiClient from './client'
import type { BacktestPreset, BacktestResponse, RunPresetPayload } from '@/types/backtest'

export const backtestApi = {
  getPresets: () =>
    apiClient.get<{ presets: BacktestPreset[] }>('/backtest/presets'),

  runPreset: (payload: RunPresetPayload) =>
    apiClient.post<BacktestResponse>('/backtest/run-preset', payload, { timeout: 180000 }),
}
