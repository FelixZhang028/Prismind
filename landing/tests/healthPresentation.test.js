import assert from 'node:assert/strict'
import test from 'node:test'
import { healthBadgeClass, healthCardBorderClass, normalizeHealthCheck } from '../src/workspace/healthPresentation.js'

test('回测白话体检卡的语义样式与数据归一化', () => {
  assert.equal(normalizeHealthCheck(null), null)
  assert.equal(normalizeHealthCheck({ items: [] }), null)

  const view = normalizeHealthCheck({
    summary_status: 'warn',
    summary_badge: '2 项高风险提醒',
    items: [
      { key: 'single_stock', title: '单股运气依赖', status: 'warn', tag: '高度依赖单股', headline: '去掉头号牛股后转亏', detail: '说明' },
      { key: 'cost_stress', title: '交易成本翻倍抗压', status: 'ok', tag: '抗成本能力良好', headline: '翻倍后仍盈利', detail: '' },
    ],
  })
  assert.equal(view.summaryStatus, 'warn')
  assert.equal(view.summaryBadge, '2 项高风险提醒')
  assert.equal(view.items.length, 2)
  assert.match(healthBadgeClass('warn'), /rose/)
  assert.match(healthBadgeClass('caution'), /amber/)
  assert.match(healthBadgeClass('ok'), /emerald/)
  assert.match(healthBadgeClass('neutral'), /slate/)
  assert.match(healthCardBorderClass('warn'), /rose/)
  assert.match(healthCardBorderClass('caution'), /amber/)
})
