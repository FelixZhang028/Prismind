import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  GUIDE_SEEN_KEY, GUIDE_STEPS, MAIN_STEPS, bubblePlacement, guideSeen, guideStep, isPhone, markGuideSeen,
  scrollTargetY, spotlightBox, stepNumber,
} from '../src/workspace/guideSteps.js'
import { allItems, groups } from '../src/workspace/modules.js'

const read = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')

test('主线四步：条件选股 → 建规则策略 → 回测 → 模拟账户，前后各有开头和结尾', () => {
  assert.deepEqual(GUIDE_STEPS.map((step) => step.key), ['intro', 'screen', 'strategy', 'backtest', 'paper', 'outro'])
  assert.deepEqual(MAIN_STEPS.map((step) => step.view), ['stock-screen', 'strategy-studio', 'backtest-review', 'paper-accounts'])
  assert.deepEqual(stepNumber(guideStep('backtest')), { current: 3, total: 4 })
  assert.equal(stepNumber(guideStep('intro')), null)
  assert.equal(guideStep('nope'), null)
})

test('每一步打开的页面和侧栏项都存在；首页“去做”用的 key 都有对应的一步', () => {
  const keys = new Set(allItems.map((item) => item.key))
  const sidebar = new Set(groups.flatMap((group) => group.items.map((item) => item.key)))
  for (const step of MAIN_STEPS) {
    assert.ok(keys.has(step.view), step.view)
    assert.ok(sidebar.has(step.nav), step.nav)
  }
  for (const key of ['screen', 'strategy', 'backtest', 'paper']) assert.ok(guideStep(key)?.target, key)
})

test('要高亮的元素在页面里都标了 data-guide', () => {
  const pages = {
    'rule-first-condition': 'workspace/ui/RuleConditions.vue',
    'strategy-starts': 'workspace/views/StrategyStudioView.vue',
    'backtest-run': 'workspace/views/BacktestReviewView.vue',
    'paper-create': 'workspace/views/PaperAccountsView.vue',
    'guide-reopen': 'components/WorkspacePage.vue',
    'guide-reopen-mobile': 'components/WorkspacePage.vue',
  }
  for (const step of GUIDE_STEPS) {
    for (const name of [step.target, step.targetMobile].filter(Boolean)) {
      assert.ok(pages[name], name)
      assert.ok(read(pages[name]).includes(`data-guide="${name}"`) || read(pages[name]).includes(`'${name}'`), `${pages[name]} 里没有 data-guide="${name}"`)
    }
  }
  assert.ok(read('components/WorkspacePage.vue').includes(':data-guide-nav="item.key"'))
})

test('文案只说按钮做什么，不给买卖建议', () => {
  const words = /买入|卖出|推荐|建议买|会涨|稳赚|收益保证/
  for (const step of GUIDE_STEPS) assert.ok(!words.test(step.title + step.text), step.key)
})

test('看过一次就不再自动打开；存不了时当作看过，不反复打扰', () => {
  const store = new Map()
  const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) }
  assert.equal(guideSeen(storage), false)
  markGuideSeen(storage)
  assert.equal(store.get(GUIDE_SEEN_KEY), '1')
  assert.equal(guideSeen(storage), true)
  const broken = { getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('blocked') } }
  assert.equal(guideSeen(broken), true)
  assert.doesNotThrow(() => markGuideSeen(broken))
})

test('高亮框比元素大一圈；元素看不见时没有高亮框', () => {
  assert.deepEqual(spotlightBox({ top: 100, left: 50, width: 80, height: 30 }), { top: 94, left: 44, width: 92, height: 42 })
  assert.equal(spotlightBox({ top: 0, left: 0, width: 0, height: 0 }), null)
  assert.equal(spotlightBox(null), null)
})

test('电脑上气泡优先放在按钮下面，放不下放上面，都放不下放在底部；不超出屏幕', () => {
  const viewport = { width: 1024, height: 768 }
  const bubble = { width: 340, height: 200 }
  const below = bubblePlacement({ top: 100, left: 600, width: 120, height: 40 }, bubble, viewport)
  assert.equal(below.side, 'below')
  assert.equal(below.top, 154)
  assert.equal(below.left, 490)                              // 对着按钮中间（660 − 170）
  assert.equal(below.arrow, 170)
  const above = bubblePlacement({ top: 600, left: 600, width: 120, height: 40 }, bubble, viewport)
  assert.deepEqual([above.side, above.top], ['above', 386])
  const edge = bubblePlacement({ top: 100, left: 950, width: 60, height: 40 }, bubble, viewport)
  assert.equal(edge.left, 1024 - 340 - 12)                   // 靠右边时贴着屏幕边，不出界
  assert.equal(edge.arrow, 980 - edge.left)                  // 箭头仍然对着按钮
  const tall = bubblePlacement({ top: 50, left: 100, width: 500, height: 650 }, bubble, viewport)
  assert.deepEqual([tall.side, tall.top, tall.arrow], ['center', 556, null])
  const none = bubblePlacement(null, bubble, viewport)
  assert.deepEqual([none.side, none.top, none.left], ['center', 284, 342])
  assert.equal(bubblePlacement(null, bubble, { width: 300, height: 600 }).width, 276)   // 窄屏不超过屏幕宽
})

test('滚动：已经看得见就不动；电脑上放到中间；手机上放到气泡上面', () => {
  const desktop = { width: 1024, height: 768 }
  assert.equal(scrollTargetY({ top: 200, height: 40 }, desktop, 0), null)
  assert.equal(scrollTargetY({ top: 1200, height: 40 }, desktop, 100), 100 + 1200 - 364)
  assert.equal(scrollTargetY({ top: -300, height: 40 }, desktop, 900), 900 - 300 - 364)
  const phone = { width: 375, height: 812 }
  assert.equal(scrollTargetY({ top: 700, height: 40 }, phone, 0, 220), Math.round(700 - (812 - 220) * 0.3))
  assert.equal(scrollTargetY({ top: 200, height: 40 }, phone, 0, 220), null)
  assert.equal(scrollTargetY({ top: 10, height: 40 }, phone, 0, 220), 0)   // 不会滚到负数
  assert.equal(isPhone(375), true)
  assert.equal(isPhone(1024), false)
})
