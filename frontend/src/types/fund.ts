/* Fund/ETF types */
export interface FundProfile {
  code: string
  name: string
  fundType: string
  riskLevel?: string
  managerName?: string
  fundCompany?: string
  nav?: number
  navDate?: string
  cumulativeNav?: number
  aum?: number
  performance1y?: number
  performance3y?: number
  performance5y?: number
  maxDrawdown?: number
  sharpeRatio?: number
}

export interface ETFProfile extends FundProfile {
  underlyingIndex?: string
  managementFee?: number
  custodianFee?: number
  fundSize?: number
  establishmentDate?: string
}

export interface FundFilterParams {
  type?: string
  riskLevel?: string
  managerName?: string
  fundCompany?: string
  perf1yMin?: number
  perf1yMax?: number
  page?: number
  size?: number
}
