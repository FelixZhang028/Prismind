// 功能台的新手引导：一步一步把页面变暗、只亮一个按钮，旁边用气泡说明。
// 主线和首页“开始使用”卡片的后四项一样：条件选股 → 建规则策略 → 回测 → 模拟账户。
// target：页面上要高亮的元素（data-guide="..."）；view：先打开哪一页；nav：电脑上侧栏里同时亮的那一项。
// 文案只说这个按钮做什么，不说该买什么、会不会涨。

export const GUIDE_STEPS = [
  {
    key: 'intro',
    title: '花 1 分钟认识一下',
    text: '镜思的主线是四步：条件选股 → 建规则策略 → 回测 → 模拟账户。接下来会在每一页把要点的地方亮出来。',
  },
  {
    key: 'screen', view: 'stock-screen', target: 'rule-first-condition', nav: 'stock-screen', short: '选股',
    title: '条件选股',
    text: '在这里设条件，比如“市盈率低于 20”。下面会马上列出今天符合条件的股票，满意后可以直接带去建策略。',
  },
  {
    key: 'strategy', view: 'strategy-studio', target: 'strategy-starts', nav: 'strategy-hub', short: '建策略',
    title: '建规则策略',
    text: '选一种开始方式：从模板开始、用一句话描述，或者自己填，都不用写代码。填好以后点页面下面的“保存策略”。',
  },
  {
    key: 'backtest', view: 'backtest-review', target: 'backtest-run', nav: 'backtest-review', short: '回测',
    title: '回测',
    text: '选好策略和日期，点这里。会用过去的真实行情模拟买卖，看收益、最大回撤和每一笔成交。',
  },
  {
    key: 'paper', view: 'paper-accounts', target: 'paper-create', nav: 'paper-accounts', short: '模拟账户',
    title: '模拟账户',
    text: '回测看完以后，在这里开一个模拟账户（要先有一个规则策略）。从今天起用每天的新行情继续模拟，看策略在没用过的数据上表现怎么样。',
  },
  {
    key: 'outro', target: 'guide-reopen', targetMobile: 'guide-reopen-mobile',
    title: '看完了',
    text: '想先看个例子？首页“开始使用”的第一项点一下，几秒钟出结果。以后在这里可以重新打开引导，右下角的“问 AI”随时能用。',
  },
]

// 中间四步的编号（开头和结尾不算）。
export const MAIN_STEPS = GUIDE_STEPS.filter((step) => step.view)
export function stepNumber(step) {
  const index = MAIN_STEPS.indexOf(step)
  return index < 0 ? null : { current: index + 1, total: MAIN_STEPS.length }
}
export const guideStep = (key) => GUIDE_STEPS.find((step) => step.key === key) || null

// 看过一次（看完或跳过）就不再自动打开。换了新引导，用新的键名，老用户也会看到一次。
export const GUIDE_SEEN_KEY = 'fq_guide_v2_seen'
export function guideSeen(storage = globalThis.localStorage) {
  try { return storage?.getItem(GUIDE_SEEN_KEY) === '1' } catch { return true }
}
export function markGuideSeen(storage = globalThis.localStorage) {
  try { storage?.setItem(GUIDE_SEEN_KEY, '1') } catch { /* 无痕模式等存不了：下次再显示也没关系 */ }
}

// 手机（窄屏）上气泡固定在屏幕底部，高亮的元素滚到上面一部分。
export const PHONE_WIDTH = 640
export const isPhone = (width) => width < PHONE_WIDTH

// 高亮框比元素大一圈。
export function spotlightBox(rect, pad = 6) {
  if (!rect || rect.width <= 0 || rect.height <= 0) return null
  return { top: rect.top - pad, left: rect.left - pad, width: rect.width + pad * 2, height: rect.height + pad * 2 }
}

// 电脑上气泡放在哪里：下面放得下就放下面，不然放上面，都放不下就放在屏幕中间偏下；
// 横向对着元素的中间，但不超出屏幕。arrow 是小箭头离气泡左边多远（对着元素中间）。
export function bubblePlacement(box, bubble, viewport, gap = 14, margin = 12) {
  const { width: vw, height: vh } = viewport
  const width = Math.min(bubble.width, vw - margin * 2)
  if (!box) return { side: 'center', top: Math.max(margin, (vh - bubble.height) / 2), left: (vw - width) / 2, width, arrow: null }
  const center = box.left + box.width / 2
  const left = Math.min(Math.max(center - width / 2, margin), vw - width - margin)
  const arrow = Math.min(Math.max(center - left, 20), width - 20)
  if (box.top + box.height + gap + bubble.height <= vh - margin) return { side: 'below', top: box.top + box.height + gap, left, width, arrow }
  if (box.top - gap - bubble.height >= margin) return { side: 'above', top: box.top - gap - bubble.height, left, width, arrow }
  return { side: 'center', top: Math.max(margin, vh - bubble.height - margin), left, width, arrow: null }
}

// 滚动到哪里：电脑上让元素在屏幕中间；手机上底部有气泡，让元素在上面三分之一左右。
// 返回新的 scrollY；元素已经在合适的位置就返回 null（不动）。
export function scrollTargetY(rect, viewport, scrollY, sheetHeight = 0) {
  const visibleHeight = viewport.height - sheetHeight
  const fits = rect.top >= 72 && rect.top + rect.height <= visibleHeight - (sheetHeight ? 12 : 80)   // 电脑上底下留点地方
  if (fits) return null
  const wanted = sheetHeight ? Math.max(80, visibleHeight * 0.3) : (viewport.height - rect.height) / 2
  return Math.max(0, Math.round(scrollY + rect.top - wanted))
}
