// 规则策略的表单与接口里的 definition 之间的转换。
// 模板、一句话生成、自己填写，最后都落在同一张表单上。
//
// definition（接口）：{ name, entry_logic, entry_rules: [{ left, operator, value | right }], ranking: { indicator, direction }, hold_buffer?, market_timing? }
// 其中 left / right / indicator 是 { name, window? }；收盘价没有周期。

export const QUANTILE_OPERATORS = new Set([
  'exclude_worst_pct',
  'exclude_bottom_pct',
  'exclude_top_pct',
  'top_pct',
  'bottom_pct',
])

export function isQuantileOperator(operator, options = null) {
  if (Array.isArray(options?.quantile_operators) && options.quantile_operators.length) {
    return options.quantile_operators.includes(operator)
  }
  return QUANTILE_OPERATORS.has(operator)
}

export function quantileHint(operator, value) {
  const pct = Number(value)
  if (!Number.isFinite(pct) || pct <= 0 || pct >= 100) return '请填写 1 ~ 99 之间的百分比（如 20 表示 20%）'
  const keep = Number((100 - pct).toFixed(1))
  if (operator === 'exclude_worst_pct') return `按因子方向剔除全样本最差 ${pct}%，保留较优的 ${keep}%`
  if (operator === 'exclude_bottom_pct') return `剔除数值最低的 ${pct}%，保留较高 ${keep}%`
  if (operator === 'exclude_top_pct') return `剔除数值最高的 ${pct}%，保留较低 ${keep}%`
  if (operator === 'top_pct') return `仅保留数值最高的前 ${pct}%`
  if (operator === 'bottom_pct') return `仅保留数值最低的后 ${pct}%`
  return ''
}

export const HOLD_BUFFER_OPTIONS = [
  { value: 0, label: '关闭（严格按前 N 名换股）' },
  { value: 5, label: '轻度缓冲（已持股跌出前 N+5 再卖）' },
  { value: 10, label: '适中缓冲（已持股跌出前 N+10 再卖，推荐）' },
  { value: 20, label: '强力缓冲（已持股跌出前 N+20 再卖）' },
]

export const DEFAULT_TIMING_BENCHMARKS = [
  { value: '000300.SH', label: '沪深 300' },
  { value: '000905.SH', label: '中证 500' },
  { value: '000016.SH', label: '上证 50' },
  { value: '399006.SZ', label: '创业板指' },
]

export const TIMING_MA_OPTIONS = [
  { value: 20, label: '20 日均线（短线敏感）' },
  { value: 60, label: '60 日均线（中期，常用）' },
  { value: 120, label: '120 日均线（半年线）' },
  { value: 250, label: '250 日均线（年线）' },
]

export const TIMING_WEIGHT_OPTIONS = [
  { value: 0, label: '空仓观望（0%）' },
  { value: 0.3, label: '保留轻仓（30%）' },
  { value: 0.5, label: '保留半仓（50%）' },
]

export const STOP_LOSS_OPTIONS = [
  { value: '', label: '关闭（不设个股止损）' },
  { value: 0.08, label: '较成本亏损 8% 止损' },
  { value: 0.1, label: '较成本亏损 10% 止损（常用）' },
  { value: 0.15, label: '较成本亏损 15% 止损' },
  { value: 0.2, label: '较成本亏损 20% 止损' },
]

export const TRAILING_STOP_OPTIONS = [
  { value: '', label: '关闭（不设移动止盈）' },
  { value: 0.1, label: '较持仓高点回撤 10% 止盈' },
  { value: 0.15, label: '较持仓高点回撤 15% 止盈（常用）' },
  { value: 0.2, label: '较持仓高点回撤 20% 止盈' },
  { value: 0.25, label: '较持仓高点回撤 25% 止盈' },
]

function defaultMarketTiming() {
  return { enabled: false, benchmark: '000300.SH', ma_window: 60, off_weight: 0 }
}

function defaultExitRules() {
  return { stop_loss_pct: '', trailing_stop_pct: '' }
}

// windows: { 指标名: { default, minimum, maximum } | null }
function side(name, windows, window) {
  const limits = windows?.[name]
  return { name, window: limits ? Number(window ?? limits.default) : null }
}

function firstIndicator(options) {
  return Object.keys(options.indicators)[0]
}

export function blankRule(options) {
  const name = firstIndicator(options)
  return {
    left: side(name, options.indicator_windows),
    operator: Object.keys(options.operators)[0],
    compare: 'value',
    value: 0,
    right: side(name, options.indicator_windows),
  }
}

export function blankForm(options) {
  return {
    name: '',
    entry_logic: 'all',
    rules: [blankRule(options)],
    ranking: { ...side(firstIndicator(options), options.indicator_windows), direction: 'descending' },
    top_n: 5,
    rebalance: 'weekly',
    hold_buffer: 0,
    market_timing: defaultMarketTiming(),
    exit_rules: defaultExitRules(),
  }
}

// 换指标时周期回到该指标的默认值；没有周期的指标清空周期。
export function chooseIndicator(target, name, options) {
  Object.assign(target, side(name, options.indicator_windows))
}

export function formFromDefinition(definition, settings, options) {
  const windows = options.indicator_windows
  const fallback = blankRule(options)
  const timing = definition.market_timing
  const exitRules = definition.exit_rules
  const rawBuffer = Number(definition.hold_buffer ?? 0)
  return {
    name: definition.name || '',
    entry_logic: definition.entry_logic === 'any' ? 'any' : 'all',
    rules: (definition.entry_rules || []).map((rule) => {
      const quantile = isQuantileOperator(rule.operator, options)
      return {
        left: side(rule.left.name, windows, rule.left.window),
        operator: rule.operator,
        compare: quantile ? 'value' : (rule.right ? 'indicator' : 'value'),
        value: quantile ? Number(rule.value ?? 20) : (rule.right ? 0 : Number(rule.value)),
        // 每条规则各有一份，改一条不会影响另一条。
        right: !quantile && rule.right ? side(rule.right.name, windows, rule.right.window) : { ...fallback.right },
      }
    }),
    ranking: {
      ...side(definition.ranking.indicator.name, windows, definition.ranking.indicator.window),
      direction: definition.ranking.direction === 'ascending' ? 'ascending' : 'descending',
    },
    top_n: Number(settings.top_n),
    rebalance: settings.rebalance,
    hold_buffer: Number.isFinite(rawBuffer) && rawBuffer > 0 ? Math.trunc(rawBuffer) : 0,
    market_timing: timing && timing.enabled !== false
      ? {
          enabled: true,
          benchmark: timing.benchmark || '000300.SH',
          ma_window: Number(timing.ma_window ?? 60),
          off_weight: Number(timing.off_weight ?? 0),
        }
      : defaultMarketTiming(),
    exit_rules: exitRules && exitRules.enabled !== false
      ? {
          stop_loss_pct: exitRules.stop_loss_pct > 0 ? Number(exitRules.stop_loss_pct) : '',
          trailing_stop_pct: exitRules.trailing_stop_pct > 0 ? Number(exitRules.trailing_stop_pct) : '',
        }
      : defaultExitRules(),
  }
}

function indicator(item) {
  return item.window == null ? { name: item.name } : { name: item.name, window: Number(item.window) }
}

export function definitionFromForm(form) {
  const result = {
    name: form.name.trim(),
    entry_logic: form.entry_logic,
    entry_rules: form.rules.map((rule) => {
      const quantile = isQuantileOperator(rule.operator)
      return {
        left: indicator(rule.left),
        operator: rule.operator,
        ...(quantile || rule.compare !== 'indicator'
          ? { value: Number(rule.value) }
          : { right: indicator(rule.right) }),
      }
    }),
    ranking: { indicator: indicator(form.ranking), direction: form.ranking.direction },
  }
  const buffer = Number(form.hold_buffer ?? 0)
  if (Number.isFinite(buffer) && buffer > 0) {
    result.hold_buffer = Math.trunc(buffer)
  }
  if (form.market_timing?.enabled) {
    result.market_timing = {
      benchmark: String(form.market_timing.benchmark || '000300.SH'),
      ma_window: Math.trunc(Number(form.market_timing.ma_window ?? 60)),
      off_weight: Number(form.market_timing.off_weight ?? 0),
    }
  }
  const rawStop = form.exit_rules?.stop_loss_pct
  const rawTrail = form.exit_rules?.trailing_stop_pct
  const stopLoss = rawStop === '' || rawStop == null ? 0 : Number(rawStop)
  const trailingStop = rawTrail === '' || rawTrail == null ? 0 : Number(rawTrail)
  if ((Number.isFinite(stopLoss) && stopLoss > 0) || (Number.isFinite(trailingStop) && trailingStop > 0)) {
    result.exit_rules = {
      ...(Number.isFinite(stopLoss) && stopLoss > 0 ? { stop_loss_pct: stopLoss } : {}),
      ...(Number.isFinite(trailingStop) && trailingStop > 0 ? { trailing_stop_pct: trailingStop } : {}),
    }
  }
  return result
}

// 保存和检查共用的请求体。origin 记录表单是从哪里开始的，后端据此标注来源。
export function packagePayload(form, origin) {
  const payload = {
    definition: definitionFromForm(form),
    top_n: Number(form.top_n),
    rebalance: form.rebalance,
    source: 'visual_builder',
  }
  if (origin?.kind === 'template') Object.assign(payload, { source: `template:${origin.template_id}`, style: origin.style })
  else if (origin?.kind === 'describe') payload.source = 'nl_builder'
  return payload
}

// 策略列表里的来源小标签。
export function sourceLabel(source) {
  const text = String(source || '')
  if (text.startsWith('template_modified:')) return '基于模板修改'
  if (text.startsWith('template:')) return '模板'
  if (text.startsWith('copy:')) return '副本'
  return { visual_builder: '自己填写', nl_builder: '一句话生成' }[text] || '规则策略'
}

// 回测页顶部摘要里展示策略保护设置与触发次数。
export function strategyProtectionSummary(result, benchmarks = DEFAULT_TIMING_BENCHMARKS) {
  if (!result || typeof result !== 'object') return ''
  const parts = []
  const buffer = Number(result.hold_buffer ?? 0)
  if (Number.isFinite(buffer) && buffer > 0) {
    parts.push(`防换手缓冲：已持股跌出前 N+${Math.trunc(buffer)} 名再卖`)
  }
  const timing = result.market_timing
  if (timing && typeof timing === 'object') {
    const label = benchmarks.find((item) => item.value === timing.benchmark)?.label || timing.benchmark || '大盘指数'
    const maWindow = Math.trunc(Number(timing.ma_window ?? 60))
    const offWeight = Number(timing.off_weight ?? 0)
    const action = offWeight <= 0 ? '空仓等待' : `降至 ${Math.round(offWeight * 100)}%`
    const triggers = Math.max(0, Math.trunc(Number(result.market_timing_triggers ?? 0)))
    parts.push(`大盘择时：${label}低于 ${maWindow} 日均线${action}（共触发 ${triggers} 个调仓日）`)
  }
  const exitRules = result.exit_rules
  if (exitRules && typeof exitRules === 'object') {
    const stopPct = Number(exitRules.stop_loss_pct ?? 0)
    if (Number.isFinite(stopPct) && stopPct > 0) {
      const stopCount = Math.max(0, Math.trunc(Number(result.stop_loss_triggers ?? 0)))
      parts.push(`个股止损：-${Math.round(stopPct * 100)}%（触发 ${stopCount} 次）`)
    }
    const trailPct = Number(exitRules.trailing_stop_pct ?? 0)
    if (Number.isFinite(trailPct) && trailPct > 0) {
      const trailCount = Math.max(0, Math.trunc(Number(result.trailing_stop_triggers ?? 0)))
      parts.push(`移动止盈：高点回撤 ${Math.round(trailPct * 100)}%（触发 ${trailCount} 次）`)
    }
  }
  return parts.join(' · ')
}

// 交易明细表“说明”列的语义样式：保护性卖出高亮，常规调仓保持低调。
export function tradeReasonClass(reason) {
  if (reason === 'STOP_LOSS' || reason === 'RISK_LIQUIDATE') {
    return 'inline-block rounded-full border border-amber-400/30 bg-amber-400/10 px-2 py-0.5 text-xs text-amber-200'
  }
  if (reason === 'TRAILING_STOP') {
    return 'inline-block rounded-full border border-sky-400/30 bg-sky-400/10 px-2 py-0.5 text-xs text-sky-200'
  }
  if (reason === 'MARKET_TIMING_SELL' || reason === 'RISK_REDUCE') {
    return 'inline-block rounded-full border border-indigo-400/30 bg-indigo-500/15 px-2 py-0.5 text-xs text-indigo-200'
  }
  return 'text-xs text-slate-400'
}
