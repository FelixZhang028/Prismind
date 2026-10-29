// 模拟账户页面的显示规则。账户来自 /api/v1/paper-accounts。

export const PAPER_STATUS = {
  WAITING: { label: '等待第一个交易日', tone: 'text-slate-300 bg-white/5 border-white/10' },
  ACTIVE: { label: '运行中', tone: 'text-emerald-300 bg-emerald-400/10 border-emerald-400/30' },
  FAILED: { label: '推进失败', tone: 'text-rose-300 bg-rose-400/10 border-rose-400/30' },
}

export function statusLabel(status) {
  return PAPER_STATUS[status]?.label || status || ''
}

export function statusTone(status) {
  return PAPER_STATUS[status]?.tone || PAPER_STATUS.WAITING.tone
}

// 状态下面的一句说明。失败时写出原因；以前成功过的结果仍然显示。
export function statusNote(account) {
  if (!account) return ''
  if (account.status === 'WAITING') {
    return `从 ${account.start_date} 开始：开始那天收盘时第一次调仓，下一个交易日开盘成交。等下一个交易日的数据更新后出第一份结果。`
  }
  if (account.status === 'FAILED') {
    const kept = account.last_date ? `下面仍是推进到 ${account.last_date} 的结果。` : ''
    return `最近一次推进没有完成：${account.error || '原因未知'}。${kept}有新的一天数据时会自动再试，也可以点「马上推进」。`
  }
  if (account.latest_data_date && account.last_date && account.last_date < account.latest_data_date) {
    return `已推进到 ${account.last_date}；本地行情已有 ${account.latest_data_date} 的数据，稍后会自动推进。`
  }
  return account.last_date ? `已推进到 ${account.last_date}，每个交易日数据更新后自动推进。` : ''
}

// 检查项的颜色：通过是绿色，需要留意是黄色，只是说明是灰色。
export function checkTone(severity) {
  if (severity === 'ok') return 'text-emerald-300'
  if (severity === 'warning') return 'text-amber-300'
  return 'text-slate-300'
}

export function checkMark(severity) {
  return severity === 'ok' ? '✓' : severity === 'warning' ? '!' : '·'
}

// 从一次回测打开“用这套设置开模拟账户”：只有规则策略可以，带上回测时的股票范围、资金、持股数和调仓频率。
export function paperPrefill(config) {
  const reference = String(config?.strategy_reference || '')
  if (!reference.startsWith('package:')) return null
  const prefill = { package_id: reference.slice('package:'.length) }
  if (config.market) prefill.market = config.market
  if (Number(config.initial_capital) > 0) prefill.initial_cash = Number(config.initial_capital)
  if (Number(config.max_positions) > 0) prefill.top_n = Number(config.max_positions)
  if (['daily', 'weekly', 'monthly'].includes(config.rebalance)) prefill.rebalance = config.rebalance
  return prefill
}

// 还能建几个；limit 为 null 时不限（管理员）。
export function accountsLeft(count, limit) {
  return limit === null || limit === undefined ? Infinity : Math.max(0, limit - count)
}

// 列表里的收益：还没有结果时显示占位符。
export function returnText(value) {
  if (value === null || value === undefined || value === '' || Number.isNaN(Number(value))) return '—'
  const number = Number(value)
  return `${number > 0 ? '+' : ''}${number.toFixed(2)}%`
}

export function returnTone(value) {
  if (value === null || value === undefined || value === '' || Number.isNaN(Number(value))) return 'text-slate-400'
  // A 股习惯：涨红跌绿
  return Number(value) > 0 ? 'text-rose-300' : Number(value) < 0 ? 'text-emerald-300' : 'text-slate-300'
}
