import assert from 'node:assert/strict'
import test from 'node:test'
import { LEAVE_REASONS, lengthNote, loadAnswered, markAnswered, resetAnswered, shouldAsk, suggestionContext } from '../src/workspace/feedback.js'

test('字数提示：没超时显示用了多少，超了说超出几个字', () => {
  assert.equal(lengthNote('  能导出吗  ', 500), '4/500')            // 前后的空格不算
  assert.equal(lengthNote('x'.repeat(503), 500), '超出 3 个字')
  assert.equal(lengthNote(null, 200), '0/200')
})

test('建议只带上能复现问题的链接信息', () => {
  assert.deepEqual(suggestionContext({ run: '8', symbol: '', mode: 'reuse', preset: 'ret:20::<=:-20' }), { run: '8', preset: 'ret:20::<=:-20' })
  assert.deepEqual(suggestionContext(), {})
})

test('“有用吗”每个功能只问一次；后端读不出来时不问', async () => {
  resetAnswered()
  let calls = 0
  const load = async () => { calls += 1; return { answered: ['event-study'] } }
  const answered = await loadAnswered(load)
  await loadAnswered(load)
  assert.equal(calls, 1)                                         // 整个功能台只问后端一次
  assert.equal(shouldAsk(answered, 'event-study'), false)
  assert.equal(shouldAsk(answered, 'backtest-review'), true)
  markAnswered('backtest-review')                                 // 刚回答过的也不再问
  assert.equal(shouldAsk(answered, 'backtest-review'), false)
  resetAnswered()
  const broken = await loadAnswered(async () => { throw new Error('offline') })
  assert.equal(shouldAsk(broken, 'agent-lab'), false)
  resetAnswered()
})

test('离开原因和后端的五个选项一致', () => {
  assert.deepEqual(LEAVE_REASONS.map((r) => r.value), ['unused', 'hard', 'data', 'trust', 'other'])
})
