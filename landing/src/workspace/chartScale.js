// 折线图的刻度和数字格式：纵轴取整齐的刻度，横轴挑几个日期，提示里的数字按单位写。

// 纵轴刻度：覆盖 [min, max]，大约 count 个，间隔是 1、2、2.5、5 乘以 10 的幂。
export function axisTicks(min, max, count = 5) {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1]
  if (min === max) {
    const pad = Math.abs(min) * 0.05 || 1
    min -= pad
    max += pad
  }
  const raw = (max - min) / Math.max(1, count - 1)
  const power = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw) || 10 * power
  const start = Math.floor(min / step + 1e-9) * step
  const ticks = [Number(start.toFixed(10))]
  while (ticks[ticks.length - 1] < max - step * 1e-9 || ticks.length < 2) {
    ticks.push(Number((ticks[ticks.length - 1] + step).toFixed(10)))
  }
  return ticks
}

// 横轴日期：首尾一定有，中间平均挑；同一年内写“月-日”，跨年写“年-月”。
export function dateTicks(dates, count = 5) {
  const valid = (dates || []).length
  if (!valid) return []
  const crossYear = String(dates[0]).slice(0, 4) !== String(dates[valid - 1]).slice(0, 4)
  const label = (day) => (crossYear ? String(day).slice(0, 7) : String(day).slice(5, 10))
  if (valid === 1) return [{ index: 0, label: label(dates[0]) }]
  const n = Math.max(2, Math.min(count, valid))
  const indexes = [...new Set(Array.from({ length: n }, (_, k) => Math.round((k * (valid - 1)) / (n - 1))))]
  return indexes.map((index) => ({ index, label: label(dates[index]) }))
}

const trim = (text) => text.replace(/\.?0+$/, '')

// axis 为 true 时是刻度上的短写法；否则是提示里的完整写法。
export function formatValue(value, unit = 'number', axis = false) {
  if (!Number.isFinite(value)) return '—'
  if (unit === 'percent') {
    const text = axis ? trim(value.toFixed(2)) : value.toFixed(2)
    return `${value > 0 ? '+' : ''}${text === '-0' ? '0' : text}%`
  }
  if (unit === 'money') {
    if (axis) {
      const abs = Math.abs(value)
      if (abs >= 1e8) return `${trim((value / 1e8).toFixed(2))}亿`
      if (abs >= 1e4) return `${trim((value / 1e4).toFixed(1))}万`
      return trim(value.toFixed(0))
    }
    return `¥${value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
  }
  return axis ? trim(value.toFixed(Math.abs(value) < 1 ? 3 : 2)) : value.toFixed(Math.abs(value) < 1 ? 4 : 2)
}
