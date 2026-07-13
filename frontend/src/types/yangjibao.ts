/* Yangjibao types */
export interface YangjibaoStatus {
  connected: boolean
  has_active_session: boolean
  qr_status: string | null
}

export interface QRLoginResponse {
  qr_id: string
  qr_image: string       // base64 PNG (raw bytes, no data: prefix)
  expires_in: number
  status: string
}

export interface QRCheckResponse {
  status: 'pending' | 'scanned' | 'confirmed' | 'expired' | 'failed'
  connected?: boolean
}

export interface SyncResult {
  success: boolean
  positionsCount: number
  totalValue: number
  newTransactions: number
  error: string | null
}

export interface YangjibaoPosition {
  symbol: string
  type: 'etf' | 'fund'
  shares: number
  avgCost: number
  currentPrice: number | null
  marketValue: number | null
  unrealizedPnl: number | null
  unrealizedPnlPct: number | null
}

export interface YangjibaoPortfolio {
  connected: boolean
  totalValue: number
  totalCost: number
  totalPnl: number
  totalPnlPct: number
  positions: YangjibaoPosition[]
}
