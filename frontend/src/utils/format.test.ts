import { describe, expect, it } from 'vitest'

import { formatNumber } from './format'

describe('formatNumber', () => {
  it.each([null, undefined, Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY])(
    'renders non-finite input %s as a placeholder',
    (value) => {
      expect(formatNumber(value, 2)).toBe('--')
    },
  )

  it('formats valid values with the requested precision', () => {
    expect(formatNumber(12.345, 2)).toBe('12.35')
    expect(formatNumber(12, 0)).toBe('12')
  })
})

