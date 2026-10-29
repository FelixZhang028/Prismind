import assert from 'node:assert/strict'
import test from 'node:test'
import { accountsLeft, checkMark, checkTone, paperPrefill, returnText, returnTone, statusLabel, statusNote } from '../src/workspace/paperPresentation.js'

test('状态显示成中文，不认识的原样显示', () => {
  assert.equal(statusLabel('WAITING'), '等待第一个交易日')
  assert.equal(statusLabel('ACTIVE'), '运行中')
  assert.equal(statusLabel('FAILED'), '推进失败')
  assert.equal(statusLabel('OTHER'), 'OTHER')
})

test('状态说明：等待时说清楚什么时候出结果，失败时写原因并说明以前的结果还在', () => {
  assert.match(statusNote({ status: 'WAITING', start_date: '2026-10-29' }), /从 2026-10-29 开始.*下一个交易日开盘成交/)
  const failed = statusNote({ status: 'FAILED', error: '缺少分红明细', last_date: '2026-10-28' })
  assert.match(failed, /缺少分红明细/)
  assert.match(failed, /推进到 2026-10-28 的结果/)
  assert.doesNotMatch(statusNote({ status: 'FAILED', error: 'x', last_date: null }), /的结果/)
  assert.match(statusNote({ status: 'ACTIVE', last_date: '2026-10-28', latest_data_date: '2026-10-29' }), /稍后会自动推进/)
  assert.match(statusNote({ status: 'ACTIVE', last_date: '2026-10-29', latest_data_date: '2026-10-29' }), /已推进到 2026-10-29/)
  assert.equal(statusNote(null), '')
})

test('只有规则策略的回测能带着设置开模拟账户', () => {
  assert.deepEqual(paperPrefill({ strategy_reference: 'package:abc', market: '000300.SH', initial_capital: 500000, max_positions: 8, rebalance: 'monthly' }),
    { package_id: 'abc', market: '000300.SH', initial_cash: 500000, top_n: 8, rebalance: 'monthly' })
  assert.deepEqual(paperPrefill({ strategy_reference: 'package:abc', rebalance: 'yearly' }), { package_id: 'abc' })
  assert.equal(paperPrefill({ strategy_reference: 'momentum' }), null)
  assert.equal(paperPrefill(null), null)
})

test('数量上限：管理员不限，其他人不会是负数', () => {
  assert.equal(accountsLeft(1, 3), 2)
  assert.equal(accountsLeft(5, 3), 0)
  assert.equal(accountsLeft(5, null), Infinity)
})

test('收益带正负号，没有结果时显示占位符', () => {
  assert.equal(returnText(1.234), '+1.23%')
  assert.equal(returnText(-2), '-2.00%')
  assert.equal(returnText(null), '—')
  assert.equal(returnTone(null), 'text-slate-400')
  assert.equal(returnTone(-1), 'text-rose-300')
  assert.equal(checkTone('ok'), 'text-emerald-300')
  assert.equal(checkTone('warning'), 'text-amber-300')
  assert.equal(checkMark('info'), '·')
})
