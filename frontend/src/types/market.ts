/* Market data types */
export interface QuoteData {
  symbol: string
  name: string
  price: number
  change: number
  changePct: number
  volume: number
  turnover?: number
  high?: number
  low?: number
  open?: number
  prevClose?: number
  timestamp: string
}

export interface KlineData {
  timestamp: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  amount?: number
}

export interface IndexData {
  code: string
  name: string
  price: number
  change: number
  changePct: number
}

export interface SectorData {
  code: string
  name: string
  sectorType: string
  changePct: number
  turnover?: number
  volume?: number
  capitalFlow?: number
  rank?: number
  rankChange?: number
}

// ── Market Diagnosis Types ──

export interface SentimentData {
  fearGreedIndex?: number        // 0-100
  fearGreedLabel?: string        // "极度恐惧"/"恐惧"/"中性"/"贪婪"/"极度贪婪"
  putCallRatio?: number
  marginBalance?: number         // 融资余额 (亿元)
  shortBalance?: number          // 融券余额
  marginShortRatio?: number
  turnoverRate?: number
  northBoundFlow?: number        // 北向资金净流入
  updatedAt?: string
}

export interface CapitalFlowItem {
  sectorName: string
  sectorCode: string
  netFlow: number                // 净流入 (亿元)
  changePct: number
  largeOrderFlow?: number
  consecutiveDays?: number
  rank: number
}

export interface SectorRotationItem {
  sectorName: string
  sectorCode: string
  momentumScore: number
  heatLevel: number              // 1-5
  trend: string                  // "leading"/"improving"/"weakening"/"lagging"
  change_1w?: number
  change_1m?: number
  capitalFlow5d?: number
}

export interface DiagnosisData {
  sentiment: SentimentData | null
  topCapitalInflow: CapitalFlowItem[]
  topCapitalOutflow: CapitalFlowItem[]
  sectorRotation: SectorRotationItem[]
  northBoundSectors: CapitalFlowItem[]
  summary: string
}

// ── Global Index Config ──

export interface IndexConfig {
  code: string
  name: string
  market: string
  enabled: boolean
}

export const DEFAULT_INDICES: IndexConfig[] = [
  { code: '000001', name: '上证指数', market: 'A股', enabled: true },
  { code: '399001', name: '深证成指', market: 'A股', enabled: true },
  { code: '000300', name: '沪深300', market: 'A股', enabled: true },
  { code: '399006', name: '创业板指', market: 'A股', enabled: true },
  { code: '000688', name: '科创50', market: 'A股', enabled: true },
  { code: 'HSI', name: '恒生指数', market: '港股', enabled: true },
  { code: 'N225', name: '日经225', market: '日股', enabled: true },
  { code: 'KOSPI', name: '韩国KOSPI', market: '韩股', enabled: false },
  { code: 'IXIC', name: '纳斯达克', market: '美股', enabled: true },
  { code: 'SPX', name: '标普500', market: '美股', enabled: true },
  { code: 'DJI', name: '道琼斯', market: '美股', enabled: true },
]

export const AVAILABLE_INDICES: IndexConfig[] = [
  ...DEFAULT_INDICES,
  { code: 'GDAXI', name: '德国DAX', market: '欧股', enabled: false },
  { code: 'FTSE', name: '英国富时100', market: '欧股', enabled: false },
  { code: 'AS51', name: '澳洲标普200', market: '其他', enabled: false },
  { code: 'VIX', name: '恐慌指数VIX', market: '美股', enabled: false },
  { code: 'CNY', name: '在岸人民币', market: '汇率', enabled: false },
  { code: 'USCNH', name: '离岸人民币', market: '汇率', enabled: false },
]

// ── Sector Ranking Types ──

export interface SectorScoreDimension {
  price: number  // 技术面 (0-10)
  flow: number   // 资金面 (0-10)
  heat: number   // 热度面 (0-10)
  momentum: number  // 动量面 (0-10)
}

export interface SectorRankingItem {
  rank: number
  code: string
  name: string
  matched_sector: string  // 实际匹配的板块名称
  change_pct: number  // 涨跌幅%
  flow_value: number  // 主力净流入 (亿元)
  turnover: number  // 成交额 (亿元)

  // Comprehensive scoring
  base_score: number  // 综合评分 (0-10)
  breakdown: SectorScoreDimension  // 维度分数

  // Signal & confidence
  signal: string  // STRONG/WATCH/WEAK/AVOID
  confidence: number  // 信号置信度 (0-1)

  // Supporting technical analysis
  technical: string  // 技术面评价
  volume: string  // 量能评价
  opportunity: string  // 机会评价

  // Related holdings (可选)
  related_holdings?: string[]  // 相关持仓基金代码
}

export interface SectorRankingResponse {
  timestamp: string
  total_sectors: number
  strong_signals: SectorRankingItem[]  // 信号强的 TOP
  watch_signals: SectorRankingItem[]   // 观察信号的
  weak_signals: SectorRankingItem[]    // 弱势信号的
  all_rankings: SectorRankingItem[]    // 全部排序
}
