/* Signal and alert types */
export interface Signal {
  id: number
  symbol: string
  signalType: 'buy' | 'sell' | 'hold' | 'strong_buy' | 'strong_sell'
  signalSource: string
  confidence: number
  priceAtSignal: number
  timeframe: string
  reason?: string
  patternName?: string
  status: 'active' | 'executed' | 'expired' | 'cancelled'
  generatedAt: string
}

export interface AlertRule {
  id: number
  symbol: string
  alertType: string
  threshold: number
  direction?: string
  enabled: boolean
  lastTriggered?: string
  cooldownMin: number
}

export interface AlertHistoryItem {
  id: number
  alertRuleId?: number
  symbol: string
  alertType: string
  triggeredValue: number
  threshold: number
  message?: string
  pushedToFeishu: boolean
  createdAt: string
}
