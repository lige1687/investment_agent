export function formatNumber(value: number | null | undefined, precision = 2): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '--'
  return value.toFixed(precision)
}

