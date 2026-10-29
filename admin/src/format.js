// 管理后台通用的显示格式。

export const number = (value) => (value == null ? '—' : Number(value).toLocaleString())
export const time = (value) => (value ? new Date(value).toLocaleString() : '—')

export function bytes(value) {
  const n = Number(value)
  if (!Number.isFinite(n) || n < 0) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = n
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return `${size >= 100 || unit === 0 ? Math.round(size) : size.toFixed(1)} ${units[unit]}`
}

// 本地日期（YYYY-MM-DD），往前 days 天。
export function localDate(days = 0, today = new Date()) {
  const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() - days)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// 概况卡片：最近 30 天注册的新用户里，多少人跑出了第一个结果（事件研究、回测或 AI 研究员），多快。
export function firstResultCard(stats) {
  if (!stats) return null
  const { days, new_users: total, with_result: done, within_hour: fast, median_minutes: median } = stats
  const share = total ? `（${Math.round((done / total) * 100)}%）` : ''
  const speed = median == null ? '' : ` · 中位数 ${median < 60 ? `${Math.round(median)} 分钟` : `${(median / 60).toFixed(1)} 小时`}`
  return {
    label: '新用户跑出第一个结果',
    value: `${done}/${total}`,
    sub: total ? `最近 ${days} 天注册的人${share}；1 小时内 ${fast} 人${speed}` : `最近 ${days} 天还没有新用户`,
  }
}
