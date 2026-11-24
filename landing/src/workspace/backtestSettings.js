// 回测页通用运行参数的本地记忆：让持仓数、调仓频率、换手缓冲、日期区间与成本/过滤设置
// 在刷新页面或从「因子研究 → 用此组合回测」跳转时保持不变，不再反复回到默认值。

export const BACKTEST_SETTINGS_KEY = 'fq-backtest-settings-v1'
const VALID_REBALANCES = new Set(['daily', 'weekly', 'monthly', 'quarterly'])
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/

function finiteNum(value) {
  if (value === null || value === undefined || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function defaultStorage() {
  try {
    return typeof localStorage !== 'undefined' ? localStorage : null
  } catch {
    return null
  }
}

export function sanitizeBacktestSettings(raw) {
  if (!raw || typeof raw !== 'object') return null
  const out = {}
  if (typeof raw.from_date === 'string' && ISO_DATE.test(raw.from_date)) out.from_date = raw.from_date
  if (typeof raw.to_date === 'string' && ISO_DATE.test(raw.to_date)) out.to_date = raw.to_date
  const capital = finiteNum(raw.initial_capital)
  if (capital !== null && capital > 0) out.initial_capital = capital
  const maxPos = finiteNum(raw.max_positions)
  if (maxPos !== null && maxPos >= 1 && maxPos <= 500) out.max_positions = Math.round(maxPos)
  if (typeof raw.rebalance === 'string' && VALID_REBALANCES.has(raw.rebalance)) out.rebalance = raw.rebalance
  const buffer = finiteNum(raw.hold_buffer)
  if (buffer !== null && buffer >= 0 && buffer <= 200) out.hold_buffer = Math.round(buffer)

  if (raw.exec && typeof raw.exec === 'object') {
    const exec = {}
    const comm = finiteNum(raw.exec.commission_wan)
    if (comm !== null && comm >= 0 && comm <= 100) exec.commission_wan = comm
    const minComm = finiteNum(raw.exec.minimum_commission)
    if (minComm !== null && minComm >= 0 && minComm <= 100) exec.minimum_commission = minComm
    if (typeof raw.exec.historical_fees === 'boolean') exec.historical_fees = raw.exec.historical_fees
    const stamp = finiteNum(raw.exec.stamp_tax_wan)
    if (stamp !== null && stamp >= 0 && stamp <= 100) exec.stamp_tax_wan = stamp
    const slip = finiteNum(raw.exec.slippage_bps)
    if (slip !== null && slip >= 0 && slip <= 200) exec.slippage_bps = slip
    if (Object.keys(exec).length) out.exec = exec
  }

  if (raw.filter && typeof raw.filter === 'object') {
    const filter = {}
    if (typeof raw.filter.exclude_st === 'boolean') filter.exclude_st = raw.filter.exclude_st
    if (typeof raw.filter.exclude_suspended === 'boolean') filter.exclude_suspended = raw.filter.exclude_suspended
    const listDays = finiteNum(raw.filter.minimum_listing_days)
    if (listDays !== null && listDays >= 0 && listDays <= 1000) filter.minimum_listing_days = Math.round(listDays)
    const histDays = finiteNum(raw.filter.minimum_history_days)
    if (histDays !== null && histDays >= 0 && histDays <= 500) filter.minimum_history_days = Math.round(histDays)
    const minAmt = finiteNum(raw.filter.minimum_average_amount)
    if (minAmt !== null && minAmt >= 0) filter.minimum_average_amount = minAmt
    if (Object.keys(filter).length) out.filter = filter
  }

  return Object.keys(out).length ? out : null
}

export function loadBacktestSettings(storage = defaultStorage()) {
  if (!storage) return null
  try {
    const raw = storage.getItem(BACKTEST_SETTINGS_KEY)
    if (!raw) return null
    return sanitizeBacktestSettings(JSON.parse(raw))
  } catch {
    return null
  }
}

export function saveBacktestSettings(snapshot, storage = defaultStorage()) {
  if (!storage) return false
  const clean = sanitizeBacktestSettings(snapshot)
  if (!clean) return false
  try {
    storage.setItem(BACKTEST_SETTINGS_KEY, JSON.stringify(clean))
    return true
  } catch {
    return false
  }
}
