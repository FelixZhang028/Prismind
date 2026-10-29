// “一键试试”：官网首页和新手引导里的几个问题，点一下就打开填好条件的事件研究，几秒钟出结果。
// 条件和后端 event_study.PRESETS 里同名的常见问题一样；链接格式见 workspace/eventStudy.js 的 encodePreset。
import { encodePreset } from './workspace/eventStudy.js'

export const TRY_QUESTIONS = [
  {
    key: 'drop',
    zh: { question: '大跌之后会反弹吗？', hint: '近 20 个交易日跌了 20% 以上' },
    en: { question: 'Do big drops bounce back?', hint: 'Down 20% or more over 20 trading days' },
    conditions: [{ type: 'ret', days: 20, op: '<=', value: -20 }],
  },
  {
    key: 'limit_up',
    zh: { question: '涨停以后呢？', hint: '当天涨停' },
    en: { question: 'What happens after a limit-up day?', hint: 'Closed at the daily limit-up price' },
    conditions: [{ type: 'limit', direction: 'up' }],
  },
  {
    key: 'cross_up',
    zh: { question: '站上 60 日均线以后呢？', hint: '收盘价从下往上穿过 60 日均线' },
    en: { question: 'After crossing above the 60-day average?', hint: 'Close crosses above the 60-day moving average' },
    conditions: [{ type: 'ma_cross', days: 60, direction: 'up' }],
  },
]

// 打开事件研究并直接算出结果的链接（没登录时会先去登录，登录后回到这里）。
export function tryHref(question) {
  return `/app.html?view=event-study&preset=${encodeURIComponent(encodePreset(question.conditions))}`
}
