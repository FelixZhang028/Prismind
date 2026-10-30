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

// 用户反馈：在哪个页面提的（页面 key -> 名字，和功能台侧栏一致；没列到的直接显示 key）
const PAGE_NAMES = {
  overview: '首页', 'event-study': '事件研究', 'stock-screen': '条件选股', 'agent-lab': 'AI 个股分析', 'market-chart': '行情图表',
  'strategy-hub': '我的策略', 'strategy-studio': '新建规则策略', 'factor-lab': '因子研究', 'backtest-review': '策略回测',
  'audit-report': '可信度审计', research: '参数验证', 'run-library': '研究记录', 'paper-accounts': '模拟账户',
  'market-lookup': '股票查询', universe: '股票池', 'data-guide': '数据说明', account: '个人中心', points: '积分与打卡', settings: '设置',
}
export function pageName(view) {
  return view ? PAGE_NAMES[view] || view : '—'
}

// “有用吗”的比例：82% 有用（17 次）；还没人回答时说一句。
export function usefulText(item) {
  if (!item?.total) return '最近还没有人回答'
  return `${Math.round((item.useful / item.total) * 100)}% 有用（${item.total} 次）`
}

// 概况卡片：还没看的建议
export function feedbackCard(stats) {
  if (!stats) return null
  return { label: '新建议', value: number(stats.unread), sub: stats.unread ? '点这里看用户反馈' : '没有没看过的建议', tab: 'feedback' }
}
