// 条件选股 / 事件研究和新建规则策略之间带条件或描述：一边存进 sessionStorage，另一边打开时取走。
// 只是页面之间的交接，读不到（例如浏览器禁用了存储）就当作没有。
const KEY = 'fq-rule-handoff'
const DRAFT_KEY = 'fq-strategy-draft'

export function handOffRules(definition) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(definition))
  } catch {
    /* 没有交接也能用，只是要重新填条件 */
  }
}

export function takeHandedRules() {
  try {
    const text = sessionStorage.getItem(KEY)
    sessionStorage.removeItem(KEY)
    return text ? JSON.parse(text) : null
  } catch {
    return null
  }
}

export function handOffStrategyDraft(draft) {
  try {
    sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft))
  } catch {
    /* 没有交接也能用 */
  }
}

export function takeStrategyDraft() {
  try {
    const text = sessionStorage.getItem(DRAFT_KEY)
    sessionStorage.removeItem(DRAFT_KEY)
    return text ? JSON.parse(text) : null
  } catch {
    return null
  }
}
