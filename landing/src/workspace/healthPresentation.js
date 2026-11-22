// 回测白话体检卡的语义样式与归一化辅助函数。

export function healthBadgeClass(status) {
  if (status === 'warn') {
    return 'inline-flex items-center rounded-full border border-rose-400/35 bg-rose-500/15 px-2.5 py-0.5 text-xs font-medium text-rose-200'
  }
  if (status === 'caution') {
    return 'inline-flex items-center rounded-full border border-amber-400/35 bg-amber-400/15 px-2.5 py-0.5 text-xs font-medium text-amber-200'
  }
  if (status === 'ok') {
    return 'inline-flex items-center rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2.5 py-0.5 text-xs font-medium text-emerald-200'
  }
  return 'inline-flex items-center rounded-full border border-white/15 bg-white/5 px-2.5 py-0.5 text-xs font-medium text-slate-300'
}

export function healthCardBorderClass(status) {
  if (status === 'warn') return 'border-rose-400/30 bg-rose-500/5'
  if (status === 'caution') return 'border-amber-400/25 bg-amber-500/5'
  return 'border-white/10 bg-white/5'
}

export function normalizeHealthCheck(health) {
  if (!health || !Array.isArray(health.items) || !health.items.length) return null
  return {
    summaryStatus: health.summary_status || 'neutral',
    summaryBadge: health.summary_badge || '体检结果',
    items: health.items.map((item) => ({
      key: item.key,
      title: item.title || '',
      status: item.status || 'neutral',
      tag: item.tag || '',
      headline: item.headline || '',
      detail: item.detail || '',
    })),
  }
}
