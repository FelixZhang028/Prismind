import test from 'node:test'
import assert from 'node:assert/strict'
import {
  anomalyToneClass,
  breadthBadge,
  fmtAmount,
  fmtPct,
  fmtRatio,
  fmtSignedAmountDelta,
  fmtSignedPct,
  formatReadout,
  limitBadge,
  maBadge,
  sortIndustries,
  styleNote,
  volumeBadge,
} from '../src/workspace/sentimentPresentation.js'

test('formats percentages, amounts, ratios, and deltas cleanly', () => {
  assert.equal(fmtPct(0.7423), '74.2%')
  assert.equal(fmtPct(null), '—')
  assert.equal(fmtSignedPct(0.0118), '+1.18%')
  assert.equal(fmtSignedPct(-0.0042), '-0.42%')
  assert.equal(fmtAmount(1.86e12), '1.86 万亿')
  assert.equal(fmtAmount(3.12e11), '3120 亿')
  assert.equal(fmtSignedAmountDelta(2.5e10), '+250 亿')
  assert.equal(fmtSignedAmountDelta(-1.2e10), '-120 亿')
  assert.equal(fmtRatio(1.344), '1.34x')
})

test('derives objective status badges without advice wording', () => {
  assert.match(breadthBadge(0.85, 0.92).text, /普涨偏热.*92%/)
  assert.match(breadthBadge(0.12, 0.05).text, /冰点偏冷.*5%/)
  assert.equal(volumeBadge(1.35).text, '放量异动')
  assert.equal(volumeBadge(0.65).text, '显著缩量')
  assert.equal(limitBadge(0.45).text, '炸板偏高')
  assert.equal(limitBadge(0.2).text, '封板较稳')
  assert.equal(maBadge(0.88).text, '过热区间')
  assert.equal(maBadge(0.12).text, '冰点区间')
  assert.equal(styleNote(0.015), '中小盘强于权重')
  assert.equal(styleNote(-0.015), '权重强于个股')
  assert.ok(anomalyToneClass('amber').includes('amber'))
})

test('sorts industries and formats hover readouts across all four chart tabs', () => {
  const rows = [
    { name: 'A', vol_ratio_20: 1.1, change: 0.03 },
    { name: 'B', vol_ratio_20: 1.8, change: -0.01 },
    { name: 'C', vol_ratio_20: null, change: 0.05 },
  ]
  assert.deepEqual(sortIndustries(rows, 'vol_ratio_20', true).map((r) => r.name), ['B', 'A', 'C'])
  assert.deepEqual(sortIndustries(rows, 'change', true).map((r) => r.name), ['C', 'A', 'B'])

  const sample = {
    date: '2026-11-18',
    amount: 1.86e12,
    up_ratio: 0.742,
    limit_up: 78,
    limit_down: 6,
    burst_rate: 0.212,
    above_ma20_ratio: 0.684,
    above_ma60_ratio: 0.591,
    hs300_cum: 0.042,
    zz500_cum: 0.078,
    median_cum: 0.095,
  }
  assert.match(formatReadout('breadth', sample), /1\.86 万亿.*74\.2%/)
  assert.match(formatReadout('limits', sample), /涨停 78.*跌停 6.*21\.2%/)
  assert.match(formatReadout('ma', sample), /68\.4%.*59\.1%/)
  assert.match(formatReadout('style', sample), /\+4\.2%.*\+7\.8%.*\+9\.5%/)
  assert.match(formatReadout('breadth', null), /移动鼠标/)
})
