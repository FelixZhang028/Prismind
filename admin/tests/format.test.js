import test from 'node:test'
import assert from 'node:assert/strict'
import { firstResultCard } from '../src/format.js'

test('新用户跑出第一个结果：人数、比例、一小时内的人数和中位数', () => {
  assert.deepEqual(firstResultCard({ days: 30, new_users: 4, with_result: 3, within_hour: 2, median_minutes: 30 }), {
    label: '新用户跑出第一个结果', value: '3/4', sub: '最近 30 天注册的人（75%）；1 小时内 2 人 · 中位数 30 分钟',
  })
  assert.match(firstResultCard({ days: 30, new_users: 2, with_result: 1, within_hour: 0, median_minutes: 180 }).sub, /中位数 3\.0 小时$/)
  assert.equal(firstResultCard({ days: 30, new_users: 3, with_result: 0, within_hour: 0, median_minutes: null }).sub,
    '最近 30 天注册的人（0%）；1 小时内 0 人')
  assert.equal(firstResultCard({ days: 30, new_users: 0, with_result: 0, within_hour: 0, median_minutes: null }).sub, '最近 30 天还没有新用户')
  assert.equal(firstResultCard(undefined), null)
})

test('用户反馈：页面名称、有用的比例、概况卡片', async () => {
  const { feedbackCard, pageName, usefulText } = await import('../src/format.js')
  assert.equal(pageName('backtest-review'), '策略回测')
  assert.equal(pageName('some-new-page'), 'some-new-page')
  assert.equal(pageName(''), '—')
  assert.equal(usefulText({ total: 17, useful: 14 }), '82% 有用（17 次）')
  assert.equal(usefulText({ total: 0, useful: 0 }), '最近还没有人回答')
  assert.deepEqual(feedbackCard({ unread: 3 }), { label: '新建议', value: '3', sub: '点这里看用户反馈', tab: 'feedback' })
  assert.equal(feedbackCard({ unread: 0 }).sub, '没有没看过的建议')
  assert.equal(feedbackCard(undefined), null)
})
