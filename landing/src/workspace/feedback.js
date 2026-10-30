// 用户反馈的显示规则：提建议弹窗、第一次出结果后的“有用吗”、注销时的离开原因。后端见 app/quant/feedback.py。
// 这里不直接引用 api.js（测试在 Node 里跑），读后端的函数由组件传进来。

export const SUGGESTION_MAX = 500
export const LEAVE_TEXT_MAX = 200
// 和后端 LEAVE_REASONS 一致
export const LEAVE_REASONS = [
  { value: 'unused', label: '用不上' },
  { value: 'hard', label: '太难用' },
  { value: 'data', label: '数据不够' },
  { value: 'trust', label: '结果不可信' },
  { value: 'other', label: '其他' },
]

// 还能写几个字；超了给一句提示。
export function lengthNote(text, max) {
  const used = String(text || '').trim().length
  return used > max ? `超出 ${used - max} 个字` : `${used}/${max}`
}

// 链接上下文里有用的部分（哪次回测、哪只股票、哪个条件），跟着建议一起发，方便复现。
export function suggestionContext(routeContext = {}) {
  const keep = {}
  for (const key of ['run', 'strategy', 'symbol', 'brief', 'preset', 'account']) {
    if (routeContext[key]) keep[key] = String(routeContext[key]).slice(0, 120)
  }
  return keep
}

// “有用吗”：已经回答过的功能。整个功能台只问后端一次，回答以后记在这里。
let answeredOnce = null
const answeredNow = new Set()
export function loadAnswered(load) {
  if (!answeredOnce) answeredOnce = load().then((data) => new Set(data.answered || [])).catch(() => new Set(['*']))
  return answeredOnce
}
export function markAnswered(feature) { answeredNow.add(feature) }
// 读不出来时（answered 里有 '*'）宁可不问。
export function shouldAsk(answered, feature) {
  return !answeredNow.has(feature) && !answered.has('*') && !answered.has(feature)
}
export function resetAnswered() { answeredOnce = null; answeredNow.clear() }
