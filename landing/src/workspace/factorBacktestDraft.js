import { openResearch } from './researchNavigation.js'

let draft = null

export function openFactorBacktest(result) {
  draft = {
    factors: result.composite_spec,
    market: result.universe,
    from_date: result.test_start,
    to_date: result.test_end,
  }
  openResearch('backtest-review', { strategy: 'factor_composite', mode: 'factor-combination' })
}

export function takeFactorBacktestDraft() {
  const pending = draft
  draft = null
  return pending
}

export const FACTOR_STANDARDIZATIONS = [
  { value: 'zscore', label: 'Z-score' },
  { value: 'rank', label: '百分位排名' },
]
