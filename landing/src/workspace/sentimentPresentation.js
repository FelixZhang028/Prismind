// 日频「市场情绪与异动」页面的纯展示与格式化逻辑。
// 遵循 A 股红涨绿跌、只描述客观数据和历史统计、不构成投资建议的口径。

export const SENTIMENT_WINDOWS = [60, 120, 250]

export const SENTIMENT_TABS = [
  {
    key: 'breadth',
    label: '宽度与量能',
    subtitle: '全市场成交额（柱，万亿）与上涨家数占比（线，%）',
  },
  {
    key: 'limits',
    label: '涨跌停周期',
    subtitle: '涨停家数（红柱）、跌停家数（绿柱）与炸板率（琥珀线，%）',
  },
  {
    key: 'ma',
    label: '均线温度',
    subtitle: '站上 20 日 / 60 日均线股票占比（虚线为 15% 冰点与 85% 过热参考）',
  },
  {
    key: 'style',
    label: '大小盘分化',
    subtitle: '区间累计收益对照：沪深 300 vs 中证 500 vs 全市场中位数（%）',
  },
]

export function fmtPct(value, digits = 1) {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  return `${(Number(value) * 100).toFixed(digits)}%`
}

export function fmtSignedPct(value, digits = 2) {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  const pct = Number(value) * 100
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(digits)}%`
}

export function fmtAmount(value) {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  const num = Number(value)
  const abs = Math.abs(num)
  const sign = num < 0 ? '-' : ''
  if (abs >= 1e12) return `${sign}${(abs / 1e12).toFixed(2)} 万亿`
  if (abs >= 1e8) return `${sign}${(abs / 1e8).toFixed(abs >= 1e10 ? 0 : 1)} 亿`
  return `${sign}${Math.round(abs).toLocaleString()} 元`
}

export function fmtSignedAmountDelta(value) {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  const num = Number(value)
  const prefix = num > 0 ? '+' : ''
  return `${prefix}${fmtAmount(num)}`
}

export function fmtRatio(value) {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  return `${Number(value).toFixed(2)}x`
}

export function signedTone(value) {
  if (value == null || !Number.isFinite(Number(value))) return 'text-slate-300'
  if (Number(value) > 0) return 'text-rose-300'
  if (Number(value) < 0) return 'text-emerald-300'
  return 'text-slate-300'
}

export function breadthBadge(upRatio, pct250) {
  if (upRatio == null || !Number.isFinite(Number(upRatio))) {
    return { text: '—', tone: 'bg-white/10 text-slate-300' }
  }
  const pct = pct250 != null && Number.isFinite(Number(pct250)) ? ` · ${Math.round(Number(pct250) * 100)}% 分位` : ''
  const v = Number(upRatio)
  if (v >= 0.8) return { text: `普涨偏热${pct}`, tone: 'bg-rose-500/15 text-rose-300' }
  if (v >= 0.6) return { text: `偏暖${pct}`, tone: 'bg-rose-500/15 text-rose-200' }
  if (v <= 0.2) return { text: `冰点偏冷${pct}`, tone: 'bg-emerald-500/15 text-emerald-300' }
  if (v <= 0.4) return { text: `偏弱${pct}`, tone: 'bg-emerald-500/15 text-emerald-200' }
  return { text: `均衡${pct}`, tone: 'bg-white/10 text-slate-300' }
}

export function volumeBadge(ratio) {
  if (ratio == null || !Number.isFinite(Number(ratio))) {
    return { text: '常规', tone: 'bg-white/10 text-slate-300' }
  }
  const v = Number(ratio)
  if (v >= 1.3) return { text: '放量异动', tone: 'bg-amber-500/15 text-amber-300' }
  if (v >= 1.1) return { text: '温和放量', tone: 'bg-rose-500/15 text-rose-200' }
  if (v <= 0.7) return { text: '显著缩量', tone: 'bg-slate-500/20 text-slate-300' }
  if (v <= 0.9) return { text: '小幅缩量', tone: 'bg-white/10 text-slate-300' }
  return { text: '量能平稳', tone: 'bg-white/10 text-slate-300' }
}

export function limitBadge(burstRate) {
  if (burstRate == null || !Number.isFinite(Number(burstRate))) {
    return { text: '样本较少', tone: 'bg-white/10 text-slate-300' }
  }
  const v = Number(burstRate)
  if (v >= 0.4) return { text: '炸板偏高', tone: 'bg-emerald-500/15 text-emerald-300' }
  if (v <= 0.25) return { text: '封板较稳', tone: 'bg-rose-500/15 text-rose-200' }
  return { text: '承接中性', tone: 'bg-white/10 text-slate-300' }
}

export function maBadge(ma20Ratio) {
  if (ma20Ratio == null || !Number.isFinite(Number(ma20Ratio))) {
    return { text: '—', tone: 'bg-white/10 text-slate-300' }
  }
  const v = Number(ma20Ratio)
  if (v >= 0.85) return { text: '过热区间', tone: 'bg-rose-500/15 text-rose-300' }
  if (v <= 0.15) return { text: '冰点区间', tone: 'bg-emerald-500/15 text-emerald-300' }
  if (v >= 0.6) return { text: '偏强', tone: 'bg-indigo-500/20 text-indigo-200' }
  if (v <= 0.35) return { text: '偏弱', tone: 'bg-slate-500/20 text-slate-300' }
  return { text: '中性区间', tone: 'bg-white/10 text-slate-300' }
}

export function anomalyToneClass(tone) {
  const map = {
    amber: 'bg-amber-500/15 text-amber-300 border-amber-400/25',
    rose: 'bg-rose-500/15 text-rose-300 border-rose-400/25',
    emerald: 'bg-emerald-500/15 text-emerald-300 border-emerald-400/25',
    indigo: 'bg-indigo-500/15 text-indigo-300 border-indigo-400/25',
    slate: 'bg-white/10 text-slate-300 border-white/15',
  }
  return map[tone] || map.slate
}

export function styleNote(spread) {
  if (spread == null || !Number.isFinite(Number(spread))) return '大小盘均衡'
  const v = Number(spread)
  if (v >= 0.008) return '中小盘强于权重'
  if (v <= -0.008) return '权重强于个股'
  return '大小盘走势接近'
}

export function sortIndustries(rows, key = 'vol_ratio_20', descending = true) {
  if (!Array.isArray(rows)) return []
  return [...rows].sort((a, b) => {
    const va = a?.[key]
    const vb = b?.[key]
    const na = va == null || !Number.isFinite(Number(va)) ? -Infinity : Number(va)
    const nb = vb == null || !Number.isFinite(Number(vb)) ? -Infinity : Number(vb)
    return descending ? nb - na : na - nb
  })
}

export function sliceSeriesForWindow(rows, windowDays = 60) {
  if (!Array.isArray(rows) || !rows.length) return []
  const sliced = rows.slice(-Math.max(1, Number(windowDays) || 60))
  const hasDailyRets = sliced.some((r) => r.hs300_ret != null || r.median_ret != null)
  if (!hasDailyRets) return sliced

  let hsFactor = 1
  let z5Factor = 1
  let medFactor = 1
  return sliced.map((row, idx) => {
    if (idx > 0) {
      hsFactor *= 1 + (Number.isFinite(Number(row.hs300_ret)) ? Number(row.hs300_ret) : 0)
      z5Factor *= 1 + (Number.isFinite(Number(row.zz500_ret)) ? Number(row.zz500_ret) : 0)
      medFactor *= 1 + (Number.isFinite(Number(row.median_ret)) ? Number(row.median_ret) : 0)
    }
    return {
      ...row,
      hs300_cum: Number((hsFactor - 1).toFixed(4)),
      zz500_cum: Number((z5Factor - 1).toFixed(4)),
      median_cum: Number((medFactor - 1).toFixed(4)),
    }
  })
}

export function formatReadout(tab, row) {
  if (!row) return '移动鼠标至图表查看单日明细'
  if (tab === 'breadth') {
    return `${row.date} · 成交额 ${fmtAmount(row.amount)} · 上涨占比 ${fmtPct(row.up_ratio)}`
  }
  if (tab === 'limits') {
    return `${row.date} · 涨停 ${row.limit_up ?? 0} · 跌停 ${row.limit_down ?? 0} · 炸板率 ${fmtPct(row.burst_rate)}`
  }
  if (tab === 'ma') {
    return `${row.date} · 站上20日线 ${fmtPct(row.above_ma20_ratio)} · 站上60日线 ${fmtPct(row.above_ma60_ratio)}`
  }
  return `${row.date} · 沪深300 ${fmtSignedPct(row.hs300_cum, 1)} · 中证500 ${fmtSignedPct(row.zz500_cum, 1)} · 中位数 ${fmtSignedPct(row.median_cum, 1)}`
}
