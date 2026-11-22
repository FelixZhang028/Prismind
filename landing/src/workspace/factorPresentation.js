// 因子库的显示规则：方向、历史长度、一行说明，以及 Alpha101 因子统一的提示。

// Alpha101 的说明末尾都是这一句；表格里不再每行重复，筛选到 Alpha101 时在表格上方提示一次。
export const ALPHA101_SUFFIX = '按原公式计算，正向输出；A股有效性需独立评估。'
export const ALPHA101_NOTE = 'Alpha101 因子来自 WorldQuant 的《101 Formulaic Alphas》，按原公式计算，都是正向；在 A 股是否有效需要自己评估，可以先在「因子评估」里看 IC 和分层收益。'

// 方向：正向是因子值越大越好，反向是越小越好。正向绿色、反向红色。
export function directionText(direction) {
  if (direction === 1) return '正向'
  if (direction === -1) return '反向'
  return '—'
}
export function directionTone(direction) {
  if (direction === 1) return 'text-emerald-300'
  if (direction === -1) return 'text-rose-300'
  return 'text-slate-400'
}

export function historyText(days) {
  const value = Number(days)
  return Number.isFinite(value) && value > 0 ? `${value} 天` : '—'
}

// 说明去掉 Alpha101 统一的结尾。
function plainDescription(factor) {
  const text = String(factor?.description || '').trim()
  if (!text.endsWith(ALPHA101_SUFFIX)) return text
  return text.slice(0, -ALPHA101_SUFFIX.length).trim().replace(/[。；;，,]+$/, '')
}

// 表格里的一行说明；说明和名字一样时（Alpha101 就是这样），改为显示公式。
export function factorSummary(factor) {
  const text = plainDescription(factor)
  const name = String(factor?.display_name || factor?.name || '').trim()
  if (!text || text === name) return { text: factor?.formula || '—', formula: Boolean(factor?.formula) }
  return { text, formula: false }
}

// 详情里的“是什么 / 有什么作用”：有专门写的说明就用；Alpha101 和自定义因子各有通用说明。
export function factorNote(factor, notes = {}) {
  if (!factor) return null
  if (notes[factor.name]) return notes[factor.name]
  if (factor.source === 'Alpha101') {
    return { meaning: `${plainDescription(factor) || factor.display_name}。`, usage: ALPHA101_NOTE }
  }
  if (factor.category === '自定义') {
    return {
      meaning: factor.description || '自定义因子：由基础字段与算子组合计算而成。',
      usage: '在「自定义因子」页配置生成，可在因子评估、因子组合与组合研究中与其他因子一样参与合成与验证。',
    }
  }
  return {
    meaning: factor.description || '—',
    usage: '可以在「因子评估」里单独检验，也可以和其他因子一起合成、做组合研究。',
  }
}

// Newey-West HAC 统计显著性展示：用于判断均值 Rank IC 是否显著异于 0。
export function significanceSummary(significance) {
  const obs = Number(significance?.observations ?? 0)
  const t = significance?.hac_t
  const p = significance?.hac_p
  const pos = significance?.positive_ratio
  if (t == null || p == null || !Number.isFinite(Number(t)) || !Number.isFinite(Number(p))) {
    return {
      value: '—',
      badge: '样本不足',
      sub: obs > 0 ? `有效 ${obs} 日，不足以估计 HAC t 值` : '有效样本不足',
      tone: 'text-slate-400',
    }
  }
  const tNum = Number(t)
  const pNum = Number(p)
  const pText = pNum < 0.001 ? 'p < 0.001' : `p = ${pNum.toFixed(3)}`
  const posText = pos != null && Number.isFinite(Number(pos)) ? ` · 正 IC 占比 ${(Number(pos) * 100).toFixed(1)}%` : ''
  const badge = pNum < 0.01 ? '高度显著' : pNum < 0.05 ? '显著' : '未达 5% 显著'
  return {
    value: tNum.toFixed(2),
    badge,
    sub: `${pText}${posText}（${badge}）`,
    tone: pNum < 0.05 ? 'text-indigo-200' : 'text-slate-300',
  }
}

// Rank IC 与平均头尾组收益差符号相反时给出白话口径说明。
export function longShortSignMismatchNote(report) {
  const ic = Number(report?.rank_ic_mean)
  const ls = Number(report?.long_short_mean)
  if (!Number.isFinite(ic) || !Number.isFinite(ls)) return ''
  if (ic * ls < 0 && Math.abs(ic) >= 0.005 && Math.abs(ls) >= 0.0005) {
    return '当前 Rank IC 与平均头尾组收益差符号相反：Rank IC 反映全市场排序的整体单调性，而头尾组收益差是最高组与最低组等权收益均值之差，容易受组内少数极端涨跌幅股票影响；建议结合下方分组净值、排除 ST 或查看常见风格相关性后再判断。'
  }
  return ''
}

export function annualIcRows(annual) {
  if (!Array.isArray(annual) || !annual.length) return []
  const fmt = (value, digits = 3) => (value == null || !Number.isFinite(Number(value)) ? '—' : Number(value).toFixed(digits))
  return annual.map((row) => {
    const p = row.hac_p
    const pText = p == null || !Number.isFinite(Number(p)) ? '—' : Number(p) < 0.001 ? '< 0.001' : Number(p).toFixed(3)
    const pos = row.positive_ratio
    return {
      year: String(row.year),
      observations: row.observations ?? 0,
      rankIc: fmt(row.rank_ic, 3),
      ir: fmt(row.rank_ic_ir, 3),
      positiveRatio: pos == null || !Number.isFinite(Number(pos)) ? '—' : `${(Number(pos) * 100).toFixed(1)}%`,
      hacT: fmt(row.hac_t, 2),
      hacP: pText,
    }
  })
}

export function styleCorrelationSummary(items) {
  if (!Array.isArray(items) || !items.length) {
    return { rows: [], highOverlapLabels: [], warning: '' }
  }
  const rows = items.map((item) => {
    const corr = Number(item.correlation)
    const sign = Number.isFinite(corr) && corr > 0 ? '+' : ''
    return {
      style: item.style,
      label: item.label,
      corrText: Number.isFinite(corr) ? `${sign}${corr.toFixed(3)}` : '—',
      tilt: item.tilt || '关联较弱',
      observations: item.observations ?? 0,
      high_overlap: Boolean(item.high_overlap),
    }
  })
  const highOverlapLabels = rows.filter((row) => row.high_overlap).map((row) => row.label)
  const warning = highOverlapLabels.length
    ? `当前因子与 ${highOverlapLabels.join('、')} 相关性较高（|r| ≥ 0.40），建议开启行业/市值中性化后再核查增量选股能力。`
    : ''
  return { rows, highOverlapLabels, warning }
}

// 统一 p 值 / BH-FDR q 值格式化。
export function formatPValue(value) {
  if (value == null || value === '' || !Number.isFinite(Number(value))) return '—'
  const num = Number(value)
  return num < 0.001 ? '< 0.001' : num.toFixed(3)
}

// BH-FDR 多重检验校正后的徽章文案与颜色。
export function fdrBadge(qValue) {
  if (qValue == null || qValue === '' || !Number.isFinite(Number(qValue))) {
    return { label: '样本不足', tone: 'text-slate-400' }
  }
  const q = Number(qValue)
  if (q < 0.05) return { label: '通过 (FDR<5%)', tone: 'text-emerald-300' }
  if (q < 0.10) return { label: '边缘显著 (FDR<10%)', tone: 'text-amber-300' }
  return { label: '未通过 (可能偶然)', tone: 'text-slate-400' }
}

export function fdrVerdictTone(verdict) {
  const text = String(verdict || '')
  if (text.includes('FDR<5%') || text.includes('p<0.05')) return 'text-emerald-300'
  if (text.includes('FDR<10%')) return 'text-amber-300'
  return 'text-slate-400'
}

// 组合研究页的多重检验白话结论摘要。
export function multipleTestingSummary(summary) {
  if (!summary || typeof summary !== 'object') return null
  const tested = Number(summary.tested_factors ?? 0)
  const total = Number(summary.total_factors ?? tested)
  const rawPassed = Number(summary.raw_passed_005 ?? 0)
  const passed = Number(summary.passed_005 ?? 0)
  const passed10 = Number(summary.passed_010 ?? passed)
  if (tested <= 0) {
    return {
      text: `多重检验校正（BH-FDR）：本次候选 ${total} 个单因子的测试期有效样本均不足，暂无法给出校正后显著性结论。`,
      tone: 'border-white/10 bg-white/5 text-slate-300',
    }
  }
  const filteredOut = Math.max(0, rawPassed - passed)
  const filterNote = filteredOut > 0
    ? `（过滤掉 ${filteredOut} 个单看 p<0.05 但多重检验未通过、可能碰运气的因子）`
    : ''
  const marginalNote = passed === 0 && passed10 > 0 ? `；另有 ${passed10} 个处于 FDR < 10% 边缘显著区间` : ''
  const text = `多重检验校正（BH-FDR）：本次测试期共检验 ${tested} 个候选单因子，未校正 p < 0.05 有 ${rawPassed} 个，经 BH-FDR 校正后 q < 0.05 有 ${passed} 个${filterNote}${marginalNote}。`
  const tone = filteredOut > 0 || passed === 0
    ? 'border-amber-400/30 bg-amber-500/10 text-amber-200'
    : 'border-emerald-400/30 bg-emerald-500/10 text-emerald-200'
  return { text, tone }
}
