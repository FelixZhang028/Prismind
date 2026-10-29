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
