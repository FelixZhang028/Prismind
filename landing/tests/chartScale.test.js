import assert from 'node:assert/strict'
import test from 'node:test'
import { axisTicks, dateTicks, formatValue } from '../src/workspace/chartScale.js'

test('纵轴刻度是整齐的数，并且盖住全部数值', () => {
  assert.deepEqual(axisTicks(-23.34, 4.1), [-30, -20, -10, 0, 10])
  assert.deepEqual(axisTicks(0, 1), [0, 0.25, 0.5, 0.75, 1])
  const money = axisTicks(784861, 1012000)
  assert.ok(money[0] <= 784861 && money[money.length - 1] >= 1012000)
  assert.ok(money.length >= 3 && money.length <= 7)
  // 只有一个值时上下留一点空间
  const flat = axisTicks(5, 5)
  assert.ok(flat[0] < 5 && flat[flat.length - 1] > 5)
})

test('横轴日期首尾都有；同一年写月-日，跨年写年-月', () => {
  const days = ['2026-01-05', '2026-03-02', '2026-05-06', '2026-07-01', '2026-10-27']
  assert.deepEqual(dateTicks(days, 3), [{ index: 0, label: '01-05' }, { index: 2, label: '05-06' }, { index: 4, label: '10-27' }])
  assert.deepEqual(dateTicks(['2025-12-30', '2026-01-02'], 5).map((t) => t.label), ['2025-12', '2026-01'])
  assert.deepEqual(dateTicks([], 5), [])
  assert.deepEqual(dateTicks(['2026-01-05'], 5), [{ index: 0, label: '01-05' }])
})

test('数字按单位写：收益带正负号，金额用万和亿', () => {
  assert.equal(formatValue(-10, 'percent', true), '-10%')
  assert.equal(formatValue(2.5, 'percent', true), '+2.5%')
  assert.equal(formatValue(0, 'percent', true), '0%')
  assert.equal(formatValue(-23.341, 'percent'), '-23.34%')
  assert.equal(formatValue(1200000, 'money', true), '120万')
  assert.equal(formatValue(250000000, 'money', true), '2.5亿')
  assert.equal(formatValue(894701.17, 'money'), '¥894,701.17')
  assert.equal(formatValue(0.0312, 'number'), '0.0312')
  assert.equal(formatValue(Number.NaN, 'percent'), '—')
})
