// 事件研究页的显示规则：条件的默认值、写进链接的条件（从 AI研究员跳过来时预先填好）、条件写成一句话、
// 结果里“满足条件”和“全部交易日”的对照、几句话的读法、走势图和每年的柱子，
// 以及从 AI研究员的数据表推出“这只股票现在的状态”。

const ok = (value) => typeof value === 'number' && Number.isFinite(value)
export const pct = (value, digits = 1) => (ok(value) ? `${(value * 100).toFixed(digits)}%` : '—')
export const signedPct = (value, digits = 2) => (ok(value) ? `${value > 0 ? '+' : ''}${(value * 100).toFixed(digits)}%` : '—')
// 涨跌的颜色：A 股习惯红涨绿跌。
export const tone = (value) => (!ok(value) || value === 0 ? 'text-slate-300' : value > 0 ? 'text-rose-300' : 'text-emerald-300')

// 新加一个条件时的默认值。
export function defaultCondition(kind) {
  const condition = { type: kind.type }
  if (kind.days?.length) condition.days = kind.days.includes(20) ? 20 : kind.days[0]
  if (kind.directions?.length) condition.direction = kind.directions[0].value
  if (kind.compare) Object.assign(condition, { op: kind.example < 0 ? '<=' : '>=', value: kind.example })
  return condition
}

// 条件写进链接：type:days:direction:op:value，多个条件用 | 分开。
export function encodePreset(conditions) {
  return (conditions || []).map((c) => [c.type, c.days ?? '', c.direction ?? '', c.op ?? '', c.value ?? ''].join(':')).join('|')
}
export function decodePreset(text, kinds = []) {
  const known = new Set(kinds.map((k) => k.type))
  return String(text || '').split('|').filter(Boolean).slice(0, 3).map((part) => {
    const [type, days, direction, op, value] = part.split(':')
    const condition = { type }
    if (days) condition.days = Number(days)
    if (direction) condition.direction = direction
    if (op) condition.op = op
    if (value !== undefined && value !== '') condition.value = Number(value)
    return condition
  }).filter((c) => !known.size || known.has(c.type))
}

// 对照表的一行：满足条件 vs 全部交易日，以及差多少。
export function compareRows(horizon) {
  if (!horizon?.events?.count) return []
  const ev = horizon.events
  const all = horizon.all || {}
  return [
    { label: '平均涨跌', event: signedPct(ev.mean), all: signedPct(all.mean), diff: ok(ev.mean) && ok(all.mean) ? ev.mean - all.mean : null, signed: true },
    { label: '中位数', event: signedPct(ev.median), all: signedPct(all.median), diff: ok(ev.median) && ok(all.median) ? ev.median - all.median : null, signed: true },
    { label: '上涨的比例', event: pct(ev.up_share), all: pct(all.up_share), diff: ok(ev.up_share) && ok(all.up_share) ? ev.up_share - all.up_share : null, points: true },
    { label: '中间一半落在', event: `${signedPct(ev.p25, 1)} ～ ${signedPct(ev.p75, 1)}`, all: `${signedPct(all.p25, 1)} ～ ${signedPct(all.p75, 1)}`, diff: null },
  ]
}
export const diffText = (row) => (!ok(row.diff) ? '' : row.points ? `${row.diff > 0 ? '+' : ''}${(row.diff * 100).toFixed(1)} 个百分点` : signedPct(row.diff))

// 分布图两组柱子的高度（相对最高的那一格）。
export function histogramBars(histogram) {
  const top = Math.max(0, ...(histogram?.events || []), ...(histogram?.all || []))
  return (histogram?.labels || []).map((label, i) => ({
    label, event: histogram.events[i] || 0, all: histogram.all[i] || 0,
    eventHeight: top ? Math.round(((histogram.events[i] || 0) / top) * 100) : 0,
    allHeight: top ? Math.round(((histogram.all[i] || 0) / top) * 100) : 0,
  }))
}

// ---------------------------------------------------------------- 条件写成一句话

// 条件种类在句子里的简短说法（下拉框里显示）。
export const SHORT_NAMES = {
  ret: '涨跌幅', from_high: '离一年最高价', from_low: '离一年最低价', ma_gap: '和均线的距离', ma_cross: '穿过均线',
  limit: '涨停或跌停', amount_ratio: '成交额放大', turnover: '换手率', pe: '市盈率', pb: '市净率',
  profit_yoy: '净利润同比', roe: '净资产收益率',
}
export const OP_WORDS = { '<=': '不超过', '>=': '不低于' }

// 选好种类以后，句子后面的几段：文字、天数、方向、比较、数值。
export function sentenceParts(kind) {
  if (!kind) return []
  const text = (value) => ({ part: 'text', text: value })
  const compare = [{ part: 'op' }, { part: 'value' }, ...(kind.unit ? [text(kind.unit)] : [])]
  switch (kind.type) {
    case 'ret': return [text('近'), { part: 'days' }, text('个交易日'), ...compare]
    case 'ma_gap': return [text('收盘价相对'), { part: 'days' }, text('日均线'), ...compare]
    case 'ma_cross': return [text('收盘价当天'), { part: 'direction' }, { part: 'days' }, text('日均线')]
    case 'limit': return [text('当天'), { part: 'direction' }]
    case 'amount_ratio': return [text('当天成交额是近 20 日平均的'), ...compare]
    case 'pe': return [text('（只算盈利的公司）'), ...compare]
    case 'roe': return [text('（最新财报，年初至报告期）'), ...compare]
    case 'profit_yoy': return [text('（最新财报）'), ...compare]
    default: return compare
  }
}

// ---------------------------------------------------------------- 结果怎么读

const CLOSE = 0.005           // 差不到 0.5 个百分点，算“差不多”
const MIN_YEAR_EVENTS = 10    // 一年里至少这么多次，才拿来比
const points = (value) => `${(Math.abs(value) * 100).toFixed(1)} 个百分点`

// 三个大数字：之后平均涨跌、上涨的比例、和同一天全部股票比。
export function bigNumbers(horizonKey, h) {
  if (!h?.events?.count) return []
  const ev = h.events
  const all = h.all || {}
  const ex = h.excess || {}
  const days = h.significance?.event_days
  const excessNote = ok(days) && days > 0
    ? `跑赢的占 ${pct(ex.up_share, 0)} · 覆盖 ${days.toLocaleString('zh-CN')} 天`
    : `跑赢的占 ${pct(ex.up_share, 0)}`
  return [
    { label: `之后 ${horizonKey} 个交易日平均涨跌`, value: signedPct(ev.mean, 1), tone: tone(ev.mean), note: `平时 ${signedPct(all.mean, 1)}` },
    { label: '上涨的比例', value: pct(ev.up_share, 0), tone: 'text-white', note: `平时 ${pct(all.up_share, 0)}` },
    { label: '和同一天的全部股票比', value: signedPct(ex.mean, 1), tone: tone(ex.mean), note: excessNote },
  ]
}

export function entryLabel(entry) {
  return entry === 'next_open' ? '次日开盘入场' : '事件当天收盘'
}

export function hasLimitUpCloseWarning(conditions, entry) {
  if (entry === 'next_open') return false
  return (conditions || []).some((c) => c?.type === 'limit' && c?.direction === 'up')
}

export function significanceBadge(h) {
  const sig = h?.significance
  if (!sig) return null
  const days = Number(sig.event_days || 0)
  const p = sig.p_value
  const t = sig.t_stat
  const pText = ok(p) ? (p < 0.001 ? 'p < 0.001' : `p = ${p.toFixed(3)}`) : null
  const detailParts = [`独立事件日 ${days.toLocaleString('zh-CN')} 天`]
  if (ok(sig.daily_mean)) detailParts.push(`日均超额 ${signedPct(sig.daily_mean, 2)}`)
  if (ok(t)) detailParts.push(`t = ${t.toFixed(2)}`)
  if (pText) detailParts.push(pText)
  const detail = ok(t) ? detailParts.join(' · ') : (sig.label || detailParts.join(' · '))
  if (days < 5) {
    return { tone: 'slate', text: '独立事件日太少，暂不做检验', detail }
  }
  if (sig.significant && ok(sig.daily_mean) && sig.daily_mean > 0) {
    return { tone: 'indigo', text: '统计较稳定（按事件日检验）', detail }
  }
  if (sig.significant && ok(sig.daily_mean) && sig.daily_mean < 0) {
    return { tone: 'slate', text: '统计较稳定 · 弱于同期市场', detail }
  }
  return { tone: 'amber', text: '统计不显著（波动或同日共振较大）', detail }
}

// 几句话读结果：和平时比、和同一天的全部股票比、每年是不是都这样、统计是否稳定。只描述历史。
export function reading(result, horizonKey) {
  const h = result?.horizons?.[String(horizonKey)]
  if (!result?.events || !h?.events?.count) return '这段时间里没有满足条件的情况。'
  const m = h.events.mean
  const a = h.all?.mean
  const x = h.excess?.mean
  const sentences = [`历史上出现过 ${result.events.toLocaleString('zh-CN')} 次。`]
  let first = `之后 ${horizonKey} 个交易日`
  const diff = ok(m) && ok(a) ? m - a : null
  if (ok(diff)) first += Math.abs(diff) < CLOSE ? `的平均涨跌和平时差不多` : `平均比平时${diff > 0 ? '高' : '低'} ${points(diff)}`
  if (ok(x)) {
    if (Math.abs(x) < CLOSE) {
      first += ok(diff) && Math.abs(diff) >= CLOSE
        ? `，但主要是因为那段时间大部分股票也在${m - x > a ? '涨' : '跌'}；和同一天的全部股票比，差不多。`
        : `；和同一天的全部股票比，也差不多。`
    } else {
      first += `；和同一天的全部股票比，平均${x > 0 ? '高' : '低'} ${points(x)}，跑赢的占 ${pct(h.excess.up_share, 0)}。`
    }
  } else first += '。'
  sentences.push(first)
  if (h.significance && ok(x) && Math.abs(x) >= CLOSE && Number(h.significance.event_days || 0) >= 5) {
    sentences.push(
      h.significance.significant
        ? '按发生日期合并检验，这一差异在统计上较稳定。'
        : '不过按发生日期合并检验后，这一差异暂未达显著水平，可能受少数波动日影响。',
    )
  }
  if (String(horizonKey) === String(result.main_horizon)) {
    const years = (result.by_year || []).filter((y) => y.events >= MIN_YEAR_EVENTS && ok(y.mean) && ok(y.all_mean))
    if (years.length >= 3) {
      const higher = years.filter((y) => y.mean - y.all_mean >= CLOSE).length
      const lower = years.filter((y) => y.mean - y.all_mean <= -CLOSE).length
      const similar = years.length - higher - lower
      const all = (count) => count === years.length
      const counts = [higher && `${higher} 年比平时高`, lower && `${lower} 年比平时低`, similar && `${similar} 年和平时差不多`].filter(Boolean)
      sentences.push(`次数够多的 ${years.length} 年里，${all(higher) ? '每一年都比平时高' : all(lower) ? '每一年都比平时低' : all(similar) ? '每一年都和平时差不多' : counts.join('，')}。`)
    }
  }
  if (result.entry === 'next_open' && Number(h.untradable_entry || 0) > 0) {
    sentences.push(`另有 ${Number(h.untradable_entry).toLocaleString('zh-CN')} 次因次日一字涨停或停牌无法买入，已从统计中剔除。`)
  }
  if (result.events < 30) sentences.push('次数太少，结果很不稳定，看看就好。')
  return sentences.join('')
}

// ---------------------------------------------------------------- 走势图、每年的柱子

function niceStep(span) {
  const steps = [0.005, 0.01, 0.02, 0.025, 0.05, 0.1, 0.2, 0.25, 0.5, 1]
  return steps.find((s) => span / s <= 5) || 1
}

// 之后每一天的平均累计涨跌：三条线的 SVG 路径、纵轴刻度、每一天的横坐标。
export const PATH_LINES = ['events', 'market', 'all']
export function pathChart(path, { width = 640, height = 220, left = 48, right = 12, top = 12, bottom = 26 } = {}) {
  if (!path?.days?.length) return null
  const days = path.days
  const values = PATH_LINES.flatMap((key) => (path[key] || []).filter(ok))
  let low = Math.min(0, ...values)
  let high = Math.max(0, ...values)
  if (high - low < 0.01) { high += 0.005; low -= 0.005 }
  const step = niceStep(high - low)
  low = Math.floor(low / step) * step
  high = Math.ceil(high / step) * step
  const lastDay = days[days.length - 1]
  const x = (day) => left + (day / lastDay) * (width - left - right)
  const y = (value) => top + ((high - value) / (high - low)) * (height - top - bottom)
  const line = (key) => {
    let d = ''
    let open = false
    days.forEach((day, i) => {
      const v = path[key]?.[i]
      if (!ok(v)) { open = false; return }
      d += `${open ? 'L' : 'M'}${x(day).toFixed(1)} ${y(v).toFixed(1)} `
      open = true
    })
    return d.trim()
  }
  const ticks = []
  for (let v = low; v <= high + 1e-9; v += step) ticks.push({ y: y(v), label: Math.abs(v) < 1e-9 ? '0%' : signedPct(v, step < 0.01 ? 1 : 0), zero: Math.abs(v) < 1e-9 })
  return {
    width, height, left, right, top, bottom, ticks,
    lines: Object.fromEntries(PATH_LINES.map((key) => [key, line(key)])),
    xs: days.map(x), days,
    point: (key, day) => { const i = days.indexOf(Number(day)); const v = path[key]?.[i]; return ok(v) ? { x: x(Number(day)), y: y(v), value: v } : null },
    x,
  }
}

// 每一年的平均涨跌（满足条件以后）的柱子，和那一年“平时”的位置；次数太少的年份画淡一些。
export function yearChart(byYear, { width = 640, height = 160, top = 14, bottom = 22, gap = 6 } = {}) {
  const years = (byYear || []).filter((y) => ok(y.mean))
  if (!years.length) return null
  // 纵轴只留有数据的那一侧：都在涨的话 0 线在下面，柱子能画得高一些。
  const values = years.flatMap((y) => [y.mean, ok(y.all_mean) ? y.all_mean : 0])
  const high = Math.max(0, ...values)
  const low = Math.min(0, ...values)
  const scale = (height - top - bottom) / Math.max(0.01, high - low)
  const zero = top + high * scale
  const slot = width / years.length
  const w = Math.max(4, slot - gap)
  return {
    width, height, zero,
    bars: years.map((y, i) => {
      const h = Math.abs(y.mean) * scale
      return {
        year: y.year, events: y.events, mean: y.mean, all_mean: y.all_mean, few: y.events < MIN_YEAR_EVENTS,
        x: i * slot + (slot - w) / 2, w, y: y.mean >= 0 ? zero - h : zero, h: Math.max(1, h), up: y.mean >= 0,
        allY: ok(y.all_mean) ? zero - y.all_mean * scale : null, center: i * slot + slot / 2,
      }
    }),
  }
}

// AI研究员的数据表 -> 这只股票现在满足的几个状态，每个都可以在事件研究里看全市场的历史。
// 阈值取整到常用的数，只列明显的状态。
export function statesFromFacts(facts) {
  const value = (key) => (facts || []).find((f) => f.key === key)?.value
  const states = []
  const fall = value('ret_20d')
  if (ok(fall) && fall <= -0.15) states.push({ text: `近 20 个交易日跌了 ${Math.round(-fall * 100)}%`, conditions: [{ type: 'ret', days: 20, op: '<=', value: -15 }] })
  if (ok(fall) && fall >= 0.15) states.push({ text: `近 20 个交易日涨了 ${Math.round(fall * 100)}%`, conditions: [{ type: 'ret', days: 20, op: '>=', value: 15 }] })
  const high = value('from_high_250d')
  if (ok(high) && high <= -0.2) {
    const level = Math.floor(-high * 10) * 10
    states.push({ text: `距近一年最高价 ${Math.round(high * 100)}%`, conditions: [{ type: 'from_high', op: '<=', value: -level }] })
  }
  const ma60 = value('ma60_gap')
  if (ok(ma60)) states.push({ text: ma60 >= 0 ? '收盘价在 60 日均线上方' : '收盘价在 60 日均线下方', conditions: [{ type: 'ma_gap', days: 60, op: ma60 >= 0 ? '>=' : '<=', value: 0 }] })
  const amount = value('amount_ratio')
  if (ok(amount) && amount >= 2) states.push({ text: `当日成交额是近 20 日平均的 ${amount.toFixed(1)} 倍`, conditions: [{ type: 'amount_ratio', op: '>=', value: 2 }] })
  const pe = value('pe_ttm')
  if (ok(pe) && pe > 0) {
    const cap = pe <= 15 ? 15 : pe <= 30 ? 30 : null
    if (cap) states.push({ text: `市盈率 ${pe.toFixed(1)}`, conditions: [{ type: 'pe', op: '<=', value: cap }] })
    else if (pe >= 60) states.push({ text: `市盈率 ${pe.toFixed(1)}`, conditions: [{ type: 'pe', op: '>=', value: 60 }] })
  }
  const growth = value('profit_growth')
  if (ok(growth) && Math.abs(growth) >= 0.3) {
    states.push({ text: `最新财报净利润同比 ${signedPct(growth, 0)}`, conditions: [{ type: 'profit_yoy', op: growth > 0 ? '>=' : '<=', value: growth > 0 ? 30 : -30 }] })
  }
  return states.slice(0, 5)
}

// ---------------------------------------------------------------- 一键转成规则策略

const roundRatio = (percent) => Math.round(Number(percent) * 1e4) / 1e6
const mapOp = (op) => (op === '<=' ? 'less_or_equal' : 'greater_or_equal')

function convertCondition(condition) {
  if (!condition?.type) return null
  const value = Number(condition.value)
  switch (condition.type) {
    case 'ret':
      if (!Number.isFinite(value)) return null
      return {
        rules: [{ left: { name: 'return', window: Number(condition.days || 20) }, operator: mapOp(condition.op), value: roundRatio(value) }],
        ranking: { indicator: { name: 'return', window: Number(condition.days || 20) }, direction: condition.op === '<=' ? 'ascending' : 'descending' },
      }
    case 'from_high':
      if (!Number.isFinite(value)) return null
      return {
        rules: [{ left: { name: 'drawdown', window: 250 }, operator: mapOp(condition.op), value: roundRatio(value) }],
        ranking: { indicator: { name: 'drawdown', window: 250 }, direction: condition.op === '<=' ? 'ascending' : 'descending' },
      }
    case 'ma_gap':
      if (!Number.isFinite(value) || value !== 0) return null
      return {
        rules: [{ left: { name: 'close' }, operator: mapOp(condition.op), right: { name: 'moving_average', window: Number(condition.days || 20) } }],
        ranking: { indicator: { name: 'return', window: Number(condition.days || 20) }, direction: condition.op === '<=' ? 'ascending' : 'descending' },
      }
    case 'pe':
      if (!Number.isFinite(value)) return null
      return {
        rules: [
          ...(condition.op === '<=' || value <= 0 ? [{ left: { name: 'pe_ttm' }, operator: 'greater_than', value: 0 }] : []),
          { left: { name: 'pe_ttm' }, operator: mapOp(condition.op), value },
        ],
        ranking: { indicator: { name: 'pe_ttm' }, direction: condition.op === '<=' ? 'ascending' : 'descending' },
      }
    case 'pb':
      if (!Number.isFinite(value)) return null
      return {
        rules: [
          ...(condition.op === '<=' || value <= 0 ? [{ left: { name: 'pb_mrq' }, operator: 'greater_than', value: 0 }] : []),
          { left: { name: 'pb_mrq' }, operator: mapOp(condition.op), value },
        ],
        ranking: { indicator: { name: 'pb_mrq' }, direction: condition.op === '<=' ? 'ascending' : 'descending' },
      }
    case 'roe':
      if (!Number.isFinite(value)) return null
      return {
        rules: [{ left: { name: 'roe_avg' }, operator: mapOp(condition.op), value: roundRatio(value) }],
        ranking: { indicator: { name: 'roe_avg' }, direction: condition.op === '<=' ? 'ascending' : 'descending' },
      }
    default:
      return null
  }
}

// 把事件研究的条件转换成可带入“新建规则策略”的草稿；不支持的条件明确列出，绝不静默丢弃。
export function strategyHandoffFromEvent(conditions = [], labels = []) {
  const convertedRules = []
  const convertedLabels = []
  const skippedLabels = []
  let ranking = null
  conditions.forEach((condition, index) => {
    const label = labels[index] || SHORT_NAMES[condition?.type] || '条件'
    const mapped = convertCondition(condition)
    if (mapped) {
      convertedRules.push(...mapped.rules)
      convertedLabels.push(label)
      if (!ranking) ranking = mapped.ranking
    } else {
      skippedLabels.push(label)
    }
  })
  const joined = (labels.length ? labels : convertedLabels.concat(skippedLabels)).join('，并且')
  const nlPrompt = joined ? `当股票满足“${joined}”时买入，按近20日涨跌幅排序选前5只` : ''
  if (!convertedRules.length) {
    return {
      mode: 'describe',
      definition: null,
      convertedLabels: [],
      skippedLabels,
      nlPrompt,
      note: '当前条件属于单日盘面触发或规则表单暂不支持的指标，已为你填好一句话描述，可以直接生成近似规则。',
    }
  }
  const shortTitle = `事件研究：${convertedLabels[0]}`.slice(0, 30)
  return {
    mode: 'rules',
    definition: {
      name: shortTitle,
      entry_logic: 'all',
      entry_rules: convertedRules,
      ranking: ranking || { indicator: { name: 'return', window: 20 }, direction: 'descending' },
    },
    convertedLabels,
    skippedLabels,
    nlPrompt,
    note: skippedLabels.length
      ? `已带入「${convertedLabels.join('、')}」；规则策略表单暂不支持「${skippedLabels.join('、')}」，可以按需补充。`
      : '',
  }
}
