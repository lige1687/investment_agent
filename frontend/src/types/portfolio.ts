/* Portfolio/Position types */
export interface Position {
  id: number
  symbol: string
  positionType: 'etf' | 'fund'
  shares: number
  avgCost: number
  currentPrice?: number
  marketValue?: number
  costBasis?: number
  unrealizedPnl?: number
  unrealizedPnlPct?: number
  realizedPnl: number
  allocationPct?: number
  source: 'manual' | 'yangjibao'
}

export interface Transaction {
  id: number
  positionId: number
  symbol: string
  txType: 'buy' | 'sell' | 'dividend' | 'split'
  shares: number
  price: number
  amount: number
  fee: number
  txDate: string
  notes?: string
  source: 'manual' | 'yangjibao'
}

export interface PortfolioSummary {
  totalValue: number
  totalCost: number
  totalPnl: number
  totalPnlPct: number
  dayPnl: number
  dayPnlPct: number
  positions: Position[]
  allocation: { category: string; value: number; pct: number }[]
}

/* Yangjibao portfolio types (matching API response format) */
export interface YangjibaoPortfolioPosition {
  symbol: string
  name: string
  type: 'fund' | 'etf'
  shares: number
  avg_cost: number
  current_price: number
  market_value: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
}

export interface YangjibaoPortfolioResponse {
  connected: boolean
  total_value: number
  total_cost: number
  total_pnl: number
  total_pnl_pct: number
  positions: YangjibaoPortfolioPosition[]
}
